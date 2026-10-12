"""GBB demo data: load and remove in one click.

How removal works
-----------------
Before loading, the wizard records the highest id of every database table.
After loading, every row above that mark is demo data (including what Odoo
created on its own: pickings, stock moves, work orders, journal items,
timesheets, chatter). Those ids are stored in gbb.demo.record. Removal
deletes exactly those rows (business documents are cancelled / reset first,
then rows are deleted in dependency order), restores the company details,
document sequences and settings that the load changed, and leaves everything
else in the database untouched.
"""
import json
import logging
import random
from datetime import datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..models.project import DESIGN_STAGES

_logger = logging.getLogger(__name__)

DEMO_PASSWORD = 'gbb@demo'

# Tables never tracked (logs, transient state, the tracker itself)
SKIP_TABLES = {
    'gbb_demo_record', 'gbb_demo_loader', 'bus_bus', 'bus_presence', 'ir_logging', 'res_users_log',
    'ir_cron_progress', 'ir_cron_trigger', 'ir_sessions', 'res_device_log', 'res_device',
    'mail_presence', 'ir_attachment', 'gbb_demo_loader', 'base_module_update', 'base_language_install',
}

# ---------------------------------------------------------------- demo masters
USERS = [
    # login, name, department, job, role
    ('girish', 'Girish Biradar', 'Management', 'Director', 'director'),
    ('arun', 'Arun Dubile', 'Marketing', 'Sales / Inquiry Booking', 'sales'),
    ('sachin', 'Sachin', 'Marketing', 'Service / Complaints', 'sales'),
    ('vishal', 'Vishal Patil', 'Marketing', 'Service', 'sales'),
    ('sandip', 'Sandip Puse', 'Design', 'Design Engineer', 'design'),
    ('netaji', 'Netaji Mane', 'Design', 'Design Engineer', 'design'),
    ('rushikesh', 'Rushikesh', 'Design', 'Design Engineer', 'design'),
    ('stores', 'Store Incharge', 'Store', 'Purchase & Stores', 'store'),
    ('planning', 'Production Planner', 'Planning', 'Planning & Production', 'ops'),
    ('quality', 'Quality Incharge', 'Quality', 'Quality', 'ops'),
    ('accounts', 'Accounts Executive', 'Accounts & HR', 'Accounts & HR', 'accounts'),
    ('security', 'Security Desk', 'Security', 'Security', 'security'),
]
OPERATORS = [
    ('Ganesh Jadhav', 'Production', 'VMC Operator'), ('Mahesh Pawar', 'Production', 'VMC Operator'),
    ('Santosh Kale', 'Production', 'CNC Operator'), ('Rahul Shinde', 'Production', 'CNC Operator'),
    ('Vijay Gaikwad', 'Production', 'Grinding Operator'), ('Amol Patil', 'Production', 'HMC Operator'),
    ('Nitin More', 'Assembly', 'Fitter'), ('Sagar Deshmukh', 'Assembly', 'Fitter'),
    ('Prakash Wagh', 'Assembly', 'Hydraulic Piping'), ('Kiran Bhosale', 'Quality', 'Inspector'),
    ('Dnyaneshwar Salunke', 'Store', 'Store Keeper'), ('Akash Chavan', 'Helper', 'Helper'),
    ('Balu Kamble', 'Driver', 'Driver'), ('Shankar Rathod', 'Security', 'Watchman'),
]
DEPARTMENTS = ['Management', 'Marketing', 'Design', 'Planning', 'Production', 'Assembly', 'Quality', 'Store',
               'Accounts & HR', 'Driver', 'Security', 'Helper']

CUSTOMERS = [
    # name, ref, city, segment, machine types
    ('Alicon Castalloy Ltd', '', 'Pune', 'Auto Components', 'VMC, HMC'),
    ('TVS Motor Company', '', 'Hosur', 'Automotive', 'VMC, HMC'),
    ('CIE Automotive India', '', 'Pune', 'Auto Components', 'VTL, HMC'),
    ('Linamar India', '', 'Pune', 'Auto Components', 'HMC, VMC 4th Axis'),
    ('Heller India', '1014 Heller', '', 'Machine Tools', 'HMC'),
    ('Steel Strips Wheels Ltd', 'SSWL', 'Chennai', 'Auto Components', 'VTL, VMC'),
    ('Bharat Fritz Werner (BFW)', '9002-BFW', 'Bengaluru', 'Machine Tools', 'VMC, Cradle'),
    ('Endurance Technologies', '', 'Aurangabad', 'Auto Components', 'VMC, HMC'),
    ('Mahindra & Mahindra', 'M&M', 'Nashik', 'Automotive', 'HMC'),
]
VENDORS = [
    # name, city, role
    ('Shree Hydraulics (Kosmek dealer) [demo]', 'Pune', 'hyd'),
    ('Precision Gauges & Tools (Mitutoyo dealer) [demo]', 'Aurangabad', 'gauge'),
    ('Deccan Steels [demo]', 'Aurangabad', 'rm'),
    ('Ajanta Heat Treaters [demo]', 'Waluj', 'hardening'),
    ('Sai Surface Coatings [demo]', 'Waluj', 'plating'),
    ('Godavari Fasteners [demo]', 'Aurangabad', 'fasteners'),
    ('Om Transport Co. [demo]', 'Aurangabad', 'transport'),
]
GRADES = [
    # grade, density, rate/kg (demo rates)
    ('20MnCr5', 7.85, 95.0), ('EN31', 7.81, 110.0), ('EN8', 7.85, 72.0), ('EN24', 7.84, 105.0),
    ('MS IS2062', 7.85, 62.0), ('C45', 7.85, 75.0), ('AL 6061', 2.70, 320.0),
]
RM_SIZES = [
    ('ROUND', 16, 100, 0), ('ROUND', 20, 100, 0), ('ROUND', 25, 120, 0), ('ROUND', 32, 150, 0),
    ('ROUND', 40, 150, 0), ('ROUND', 50, 200, 0), ('FLAT', 0, 100, 100), ('FLAT', 0, 150, 100),
    ('FLAT', 0, 200, 150), ('FLAT', 0, 300, 200), ('FLAT', 0, 410, 310), ('FLAT', 0, 500, 400),
]
STD_ITEMS = [
    # name, make, price, vendor role
    ('HYD Work Support (Kosmek)', 'Kosmek', 25500, 'hyd'), ('HYD CYL (GBB Make)', 'GBB', 9500, 'hyd'),
    ('Sequence Valve', 'Kosmek', 10500, 'hyd'), ('Flow Control Valve', 'Kosmek', 5500, 'hyd'),
    ('Dial Gauge', 'Mitutoyo', 3000, 'gauge'), ('Swing Clamp Cylinder', 'Kosmek', 12000, 'hyd'),
    ('Work Support Spring', 'Kosmek', 8500, 'hyd'), ('Hydraulic Coupler', 'Vega', 1200, 'hyd'),
    ('Rest Pad / Locator', 'GBB', 1800, 'hyd'), ('Pull Stud', 'GBB', 900, 'hyd'),
    ('Tombstone Casting', 'GBB', 0, 'rm'),
    ('Dowel Pin 8x30', 'STD', 18, 'fasteners'), ('Allen Bolt M10x40', 'STD', 22, 'fasteners'),
    ('T-Nut M16', 'STD', 140, 'fasteners'), ('Eye Bolt M12', 'STD', 95, 'fasteners'),
]
MACHINES = [
    # name, type, group, cost/hr (demo)
    ('SURYA 1', 'VMC', 'G1', 650), ('SURYA 2', 'VMC', 'G1', 650), ('SURYA 3', 'VMC', 'G2', 650),
    ('SURYA 4', 'VMC', 'G2', 650), ('CHAKARA', 'VMC', 'COMMON', 650), ('SOORAJ', 'VMC', 'COMMON', 650),
    ('MAZAK', 'VMC', 'COMMON', 900), ('HASS', 'VMC', 'COMMON', 750), ('VAYU', 'VMC', 'COMMON', 650),
    ('ROBO 1', 'VMC', 'COMMON', 700), ('ROBO 2', 'VMC', 'COMMON', 700),
    ('CNC JOBBER JUNIOR', 'CNC', 'G1', 450), ('CNC LM JOBER', 'CNC', 'G2', 450), ('DOOSAN', 'CNC', 'COMMON', 550),
    ('CNC SJE 10 LM', 'CNC', 'COMMON', 450), ('DRO', 'CNC', 'COMMON', 300), ('OKUMA', 'CNC', 'COMMON', 600),
    ('CYL GRINDING 350', 'GRIND', 'COMMON', 400), ('CYL GRINDING 260', 'GRIND', 'COMMON', 400),
    ('CYL GRINDING ECO 200', 'GRIND', 'COMMON', 380), ('SURFACE PORTH', 'GRIND', 'COMMON', 380),
    ('SURFACE BHURJI', 'GRIND', 'COMMON', 380), ('SURFACE', 'GRIND', 'COMMON', 350),
    ('Assembly Bench 1', 'ASM', 'G1', 450), ('Assembly Bench 2', 'ASM', 'G2', 450),
    ('Design (3D Programming)', 'DESIGN', 'COMMON', 600),
]
INSTRUMENTS = [
    # name, spec, serial, maker, least count, status
    ('Bore Gauge', '18-35 mm', '22829179', 'Mitutoyo', '0.001', 'new'),
    ('Bore Gauge', '18-35 mm', '22835037', 'Mitutoyo', '0.001', 'new'),
    ('Bore Gauge', '18-35 mm', '9587169', 'Mitutoyo', '0.001', 'ok'),
    ('Bore Gauge', '18-35 mm', '8537716', 'Mitutoyo', '0.001', 'ok'),
    ('Bore Gauge', '10-18.5 mm', '232053', 'Mitutoyo', '0.001', 'ok'),
    ('Bore Gauge', '10-18.5 mm', '968374', 'Mitutoyo', '0.001', 'ok'),
    ('Digital External Micrometer', '0-25 mm', '71864356', 'Mitutoyo', '0.001', 'ok'),
    ('Digital External Micrometer', '0-25 mm', '66585729', 'Mitutoyo', '0.001', 'ok'),
    ('External Micrometer', '0-25 mm', 'X-6536', 'Baker', '0.01', 'ok'),
    ('External Micrometer', '0-25 mm', '2578422', 'Mitutoyo', '0.01', 'ok'),
    ('External Micrometer', '125-150 mm', 'P-2200', 'Baker', '0.01', 'ok'),
    ('Bevel Protractor', '0°-90°-0°', '184603', 'Mitutoyo', '5 min', 'ok'),
    ('External Micrometer', '75-100 mm', '71130922', 'Mitutoyo', '0.01', 'ok'),
    ('Plunger Dial Gauge', '0-1 mm', 'BCWH33', 'Mitutoyo', '0.001', 'ok'),
    ('Plunger Dial Gauge', '0-1 mm', 'BXA207', 'Mitutoyo', '0.001', 'notok'),
    ('Plunger Dial Gauge', '0-1 mm', 'BURN48', 'Mitutoyo', '0.001', 'ok'),
]

# Inquiries: days ago, customer idx, fixture type, qty, component, material, machine, stage, booked by, group, value
INQUIRIES = [
    (170, 0, 'HMC HYD', 2, 'JLR Rear Housing', 'AL Casting', 'MAZAK HCN 5000', 'won', 'arun', 'G1', 3764400),
    (160, 6, 'VMC', 18, 'Pneumatic Tail Support', 'Steel', 'BFW VMC', 'won', 'girish', 'G2', 2106000),
    (150, 5, 'VTL', 1, 'Wheel Disc', 'Steel', 'VTL 1250', 'won', 'arun', 'G1', 863200),
    (140, 1, 'VMC HYD', 4, 'JD Bearing Cap', 'CI', 'MAZAK VC510', 'won', 'arun', 'G1', 1932350),
    (125, 6, 'Cradle', 1, '4th Axis Cradle', 'Steel', 'BFW Gaurav 5 Axis', 'won', 'girish', 'G2', 161500),
    (110, 3, 'HMC', 2, 'K06 Swing Arm OP-10', 'AL', 'HMC 630', 'quote', 'arun', 'G1', 1450000),
    (95, 2, 'VTL', 1, 'RAC VTL Fixture', 'CI', 'VTL 800', 'quote', 'arun', 'G2', 680000),
    (80, 7, 'VMC 4TH AXIS', 2, 'Lift Arm H1319', 'Forge', 'VMC 4th Axis', 'quote', 'girish', 'G1', 1700000),
    (70, 8, 'HMC HYD', 1, 'Cylinder Head OP-20', 'AL Casting', 'HMC 500', 'layout', 'arun', 'G1', 2450000),
    (55, 4, 'Checking Fixture', 1, 'Housing', 'CI', 'CMM', 'process', 'arun', 'G2', 420000),
    (40, 0, 'VMC HYD', 2, 'Daimler 2561 OP-10 & OP-20', 'AL Casting', 'MAZAK VC510', 'process', 'arun', 'G1', 2900000),
    (30, 1, 'VMC', 3, 'KD Swing Arm', 'AL', 'VMC 850', 'open', 'arun', 'G1', 900000),
    (21, 5, 'VTL', 1, 'Wheel 9.00x22.5', 'Steel', 'VTL 1250', 'hold', 'arun', 'G2', 750000),
    (12, 3, 'HMC HYD', 2, 'Valve Body', 'AL', 'HMC 500', 'open', 'arun', 'G1', 1600000),
    (6, 2, 'VMC', 1, 'Planetary Hub', 'CI', 'VMC 1050', 'open', 'arun', 'G2', 520000),
    (3, 7, 'STD ZPS Block', 4, 'ZPS Block', 'Steel', 'VMC', 'open', 'arun', 'COMMON', 380000),
    (185, 8, 'HMC', 1, 'Oil Pan', 'AL', 'HMC 500', 'lost', 'arun', 'G1', 640000),
]

# Fixture parts for BOMs: name, qty, grade, shape, D, L, W, H
FIXTURE_PARTS = [
    ('Base Plate', 1, '20MnCr5', 'FLAT', 0, 400, 300, 40),
    ('Resting Pad', 4, 'EN31', 'FLAT', 0, 80, 80, 25),
    ('Locating Pin', 4, 'EN31', 'ROUND', 20, 95, 0, 0),
    ('Taper Pin', 2, 'EN31', 'ROUND', 16, 70, 0, 0),
    ('Clamp', 4, 'EN8', 'FLAT', 0, 120, 40, 30),
    ('Clamp Pad', 4, 'EN31', 'FLAT', 0, 40, 30, 15),
    ('Rough Guide Base', 2, 'EN8', 'FLAT', 0, 90, 60, 30),
    ('Bush', 4, 'EN31', 'ROUND', 30, 40, 0, 0),
]
FIXTURE_STD = [
    ('HYD Work Support (Kosmek)', 2), ('Swing Clamp Cylinder', 4), ('Sequence Valve', 1),
    ('Dial Gauge', 1), ('Hydraulic Coupler', 2), ('Dowel Pin 8x30', 6), ('Allen Bolt M10x40', 12),
]
COMPLAINTS = [
    (2, 'Oil leakage from manifold block', 'JLR Rear Housing OP-10', 'closed', 'sachin',
     'O-ring groove depth undersize on manifold', 'Groove re-machined, O-rings replaced, leak test done'),
    (5, 'Cylinder crack in top clamp', 'Wheel Disc VTL fixture', 'resolved', 'vishal',
     'Clamp cylinder over-pressure, no pressure relief', 'Cylinder replaced, sequence valve set to 45 bar'),
    (1, 'Hyd pressure drop during machining', 'JD Bearing Cap OP-10', 'trial2', 'sachin', '', ''),
    (6, 'Part slippage on resting pads', 'Pneumatic Tail Support', 'trial1', 'vishal', '', ''),
    (3, 'Hole to position shift 0.05', 'K06 Swing Arm OP-10', 'assigned', 'sachin', '', ''),
    (6, 'Oil leakage in rotary joint', '4th Axis Cradle', 'received', 'vishal', '', ''),
]
FEEDBACK = [  # customer idx, fixture, total score out of 44
    (2, 'RAC VTL & HMC', 43), (1, 'KD Swing Arm', 44), (0, 'Daimler Project & JLR Rear Housing', 32),
    (4, 'Housing', 28), (5, 'VTL DISC', 25), (3, 'K06 Swing Arm OP10', 30), (7, 'Body 7852', 30),
]


class GbbDemoRecord(models.Model):
    _name = 'gbb.demo.record'
    _description = 'GBB Demo Data Tracker'

    batch = fields.Char(required=True)
    model = fields.Char()
    table_name = fields.Char(required=True)
    ids_json = fields.Text(required=True)
    count = fields.Integer()
    kind = fields.Selection([('rows', 'Rows'), ('state', 'Saved State')], default='rows')


class GbbDemoLoader(models.TransientModel):
    _name = 'gbb.demo.loader'
    _description = 'Load / Remove GBB Demo Data'

    is_loaded = fields.Boolean(compute='_compute_status')
    summary = fields.Text(compute='_compute_status')
    log = fields.Text(readonly=True)

    def _compute_status(self):
        recs = self.env['gbb.demo.record'].sudo().search([('kind', '=', 'rows')])
        labels = [('crm.lead', 'Inquiries'), ('sale.order', 'Quotations and orders'),
                  ('project.project', 'Projects (design + complaints)'), ('gbb.checklist', 'Checklists'),
                  ('mrp.bom', 'Bills of materials (fixture + parts)'), ('mrp.production', 'Manufacturing orders'),
                  ('mrp.workorder', 'Work orders'), ('purchase.order', 'Purchase orders'),
                  ('stock.picking', 'Receipts, deliveries, requisitions'), ('account.move', 'Invoices, bills, entries'),
                  ('gbb.design.change', 'Design change records'), ('mrp.workcenter', 'Machines (work centers)'),
                  ('maintenance.equipment', 'Machines and instruments'), ('maintenance.request', 'Maintenance requests'),
                  ('res.partner', 'Customers, vendors, contacts'), ('product.product', 'Products and parts'),
                  ('hr.employee', 'Employees'), ('res.users', 'Demo users'), ('account.analytic.line', 'Timesheets')]
        by_model = {}
        for r in recs:
            by_model[r.model] = by_model.get(r.model, 0) + r.count
        for w in self:
            w.is_loaded = bool(recs)
            if recs:
                lines = ['%s: %s' % (label, by_model[m]) for m, label in labels if by_model.get(m)]
                w.summary = _('Demo data is loaded (%s rows in total).\n\n', sum(recs.mapped('count'))) \
                    + '\n'.join(lines)
            else:
                w.summary = _('No GBB demo data is loaded.')

    # ================================================================ helpers
    def _snapshot_tables(self):
        cr = self.env.cr
        res = {}
        for model_name, model in self.env.registry.items():
            if model._abstract or not model._auto:
                continue
            table = model._table
            if table in SKIP_TABLES or table in res:
                continue
            cr.execute("SELECT to_regclass(%s)", (table,))
            if not cr.fetchone()[0]:
                continue
            cr.execute('SELECT COALESCE(MAX(id), 0) FROM "%s"' % table)
            res[table] = (model_name, cr.fetchone()[0])
        return res

    def _save_state(self, batch):
        Seq = self.env['ir.sequence'].sudo()
        state = {
            'sequences': {s.id: s.number_next_actual for s in Seq.search([])},
            'ranges': {r.id: r.number_next_actual for r in self.env['ir.sequence.date_range'].sudo().search([])},
        }
        company = self.env.company
        state['company'] = {
            'name': company.name, 'street': company.street, 'street2': company.street2, 'city': company.city,
            'zip': company.zip, 'phone': company.phone, 'email': company.email, 'website': company.website,
            'vat': company.vat, 'state_id': company.state_id.id, 'country_id': company.country_id.id,
        }
        mto = self.env.ref('stock.route_warehouse0_mto', raise_if_not_found=False)
        state['mto_active'] = bool(mto and mto.active)
        team = self.env.ref('sales_team.team_sales_department', raise_if_not_found=False)
        state['team_target'] = team.invoiced_target if team else 0
        self.env['gbb.demo.record'].sudo().create({
            'batch': batch, 'table_name': '__state__', 'kind': 'state', 'ids_json': json.dumps(state)})

    def _ref(self, xmlid):
        return self.env.ref(xmlid, raise_if_not_found=False)

    def _step(self, name, func, log):
        try:
            with self.env.cr.savepoint():
                result = func()
            log.append('OK   %s%s' % (name, (': %s' % result) if result else ''))
            return True
        except Exception as e:  # keep loading the rest, report in the log
            _logger.exception('GBB demo step failed: %s', name)
            log.append('FAIL %s: %s' % (name, e))
            return False

    # ================================================================ load
    def action_load(self):
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise UserError(_('Only an administrator can load demo data.'))
        if self.env['gbb.demo.record'].sudo().search_count([]):
            raise UserError(_('GBB demo data is already loaded. Remove it first.'))
        batch = fields.Datetime.now().strftime('%Y%m%d%H%M%S')
        self._save_state(batch)
        log = []
        D = {}
        # Rows created from here on are demo rows. Exception: when the database has no Indian chart of
        # accounts yet, the chart is loaded first and kept (it is configuration, not demo data).
        marks = self._snapshot_tables()
        self._step('Company, accounting and settings', lambda: self.sudo()._load_company(D), log)
        self.env.flush_all()
        if D.get('chart_loaded'):
            marks = self._snapshot_tables()
        ctx = dict(self.env.context, tracking_disable=False, mail_notrack=False, gbb_skip_approval=True,
                   mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True, no_reset_password=True)
        loader = self.with_context(ctx).sudo()
        steps = [
            ('Departments, users and employees', lambda: loader._load_people(D)),
            ('Customers and vendors', lambda: loader._load_partners(D)),
            ('Rate card, RM sizes and products', lambda: loader._load_products(D)),
            ('Machines, work centers and instruments', lambda: loader._load_machines(D)),
            ('Opening stock and reorder rules', lambda: loader._load_stock(D)),
            ('Inquiries and inquiry reviews', lambda: loader._load_inquiries(D)),
            ('Quotations with cost breakup', lambda: loader._load_quotations(D)),
            ('Orders, order reviews and design projects', lambda: loader._load_orders(D)),
            ('Design work: timesheets and checklists', lambda: loader._load_design(D)),
            ('Fixture BOMs, part routes and RM sizing', lambda: loader._load_boms(D)),
            ('Manufacturing orders and purchase', lambda: loader._load_manufacturing(D)),
            ('BOM revision with Design Change Record', lambda: loader._load_design_change(D)),
            ('Dispatch, invoice and payment', lambda: loader._load_dispatch(D)),
            ('Quality: inspection, rejection, tool breakage', lambda: loader._load_quality(D)),
            ('Maintenance: plans, breakdowns, JH checks', lambda: loader._load_maintenance(D)),
            ('Customer complaints and feedback', lambda: loader._load_customer_care(D)),
            ('HR: skills, training, leave, attendance, advances', lambda: loader._load_hr(D)),
            ('Security register and incidents', lambda: loader._load_security(D)),
        ]
        for name, func in steps:
            self._step(name, func, log)
        self.env.flush_all()
        n = self._record_new_rows(batch, marks)
        log.append('Tracked %s demo rows for removal.' % n)
        self.log = '\n'.join(log)
        return self._reopen()

    def _record_new_rows(self, batch, marks):
        cr = self.env.cr
        vals = []
        total = 0
        for table, (model_name, mark) in marks.items():
            cr.execute('SELECT id FROM "%s" WHERE id > %%s ORDER BY id' % table, (mark,))
            ids = [r[0] for r in cr.fetchall()]
            if ids:
                vals.append({'batch': batch, 'model': model_name, 'table_name': table,
                             'ids_json': json.dumps(ids), 'count': len(ids)})
                total += len(ids)
        self.env['gbb.demo.record'].sudo().create(vals)
        return total

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window', 'res_model': 'gbb.demo.loader', 'res_id': self.id,
            'view_mode': 'form', 'target': 'new', 'name': _('GBB Demo Data'),
        }

    # ---------------------------------------------------------------- steps
    def _load_company(self, D):
        env = self.env
        company = env.company
        india = env.ref('base.in')
        mh = env['res.country.state'].search([('country_id', '=', india.id), ('code', '=', 'MH')], limit=1)
        company.write({
            'name': 'G.B.B Industries', 'street': 'Gut No. 128, Behind Rajmata Hotel, Bombay Highway',
            'street2': 'Karodi', 'city': 'Aurangabad', 'zip': '431136', 'state_id': mh.id,
            'country_id': india.id, 'phone': '+91 86577 11555', 'email': 'marketing@gbbindustries.com',
            'website': 'www.gbbindustries.com', 'vat': '27AAGFG3765Q1ZP',
        })
        msgs = []
        if company.chart_template != 'in':
            if not env['account.move'].search_count([('company_id', '=', company.id)]):
                inr = env.ref('base.INR')
                inr.active = True
                company.currency_id = inr
                env['account.chart.template'].try_loading('in', company, install_demo=False)
                D['chart_loaded'] = True
                msgs.append('Indian chart of accounts and GST loaded')
            else:
                msgs.append('company has accounting entries: chart of accounts left as is')
        # settings the demo relies on
        settings = env['res.config.settings'].create({
            'group_mrp_routings': True, 'group_stock_multi_locations': True,
        })
        settings.execute()
        mto = self._ref('stock.route_warehouse0_mto')
        if mto:
            mto.active = True
        team = self._ref('sales_team.team_sales_department')
        if team:
            team.invoiced_target = 1500000  # Rs 1.8 Cr per year / 12
        # numbering continues like the live register: E-225 onwards, project codes 3101 onwards
        today = fields.Date.context_today(self)
        for code, nxt in (('gbb.inquiry', 225), ('gbb.project.code', 3101)):
            seq = env['ir.sequence'].search([('code', '=', code)], limit=1)
            for rng in seq.date_range_ids:
                if rng.date_from <= today <= rng.date_to:
                    rng.number_next_actual = nxt
        return ', '.join(msgs)

    def _load_people(self, D):
        env = self.env
        Dept = env['hr.department']
        D['dept'] = {}
        for name in DEPARTMENTS:
            D['dept'][name] = Dept.search([('name', '=', name)], limit=1) or Dept.create({'name': name})
        g = lambda x: self._ref(x)
        roles = {
            'director': ['base.group_user', 'sales_team.group_sale_manager', 'purchase.group_purchase_manager',
                         'mrp.group_mrp_manager', 'stock.group_stock_manager', 'project.group_project_manager',
                         'hr.group_hr_manager', 'account.group_account_manager', 'gbb_erp.group_gbb_director',
                         'maintenance.group_equipment_manager', 'survey.group_survey_manager',
                         'hr_holidays.group_hr_holidays_manager', 'hr_attendance.group_hr_attendance_manager',
                         'hr_timesheet.group_hr_timesheet_approver'],
            'sales': ['base.group_user', 'sales_team.group_sale_salesman_all_leads', 'project.group_project_user',
                      'hr_timesheet.group_hr_timesheet_user'],
            'design': ['base.group_user', 'project.group_project_manager', 'mrp.group_mrp_manager',
                       'hr_timesheet.group_hr_timesheet_user'],
            'store': ['base.group_user', 'purchase.group_purchase_user', 'stock.group_stock_user',
                      'mrp.group_mrp_user'],
            'ops': ['base.group_user', 'mrp.group_mrp_manager', 'stock.group_stock_user',
                    'maintenance.group_equipment_manager', 'project.group_project_user'],
            'accounts': ['base.group_user', 'account.group_account_manager', 'hr.group_hr_manager',
                         'hr_attendance.group_hr_attendance_manager', 'hr_holidays.group_hr_holidays_manager'],
            'security': ['base.group_user', 'hr_attendance.group_hr_attendance_officer'],
        }
        Users = env['res.users'].with_context(no_reset_password=True)
        D['users'] = {}
        D['emp'] = {}
        for login, name, dept, job, role in USERS:
            groups = [g(x).id for x in roles[role] if g(x)]
            user = Users.create({
                'name': name, 'login': '%s@gbb.demo' % login, 'email': '%s@gbb.demo' % login,
                'password': DEMO_PASSWORD, 'group_ids': [(6, 0, groups)], 'tz': 'Asia/Kolkata',
                'company_id': env.company.id, 'company_ids': [(6, 0, env.company.ids)],
            })
            D['users'][login] = user
            emp = user.employee_id or env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
            vals = {'department_id': D['dept'][dept].id, 'job_title': job,
                    'gbb_staff_type': 'staff', 'gbb_group': 'COMMON'}
            if emp:
                emp.write(vals)
            else:
                emp = env['hr.employee'].create(dict(vals, name=name, user_id=user.id))
            D['emp'][login] = emp
        # Girish is the approving director
        env.ref('gbb_erp.group_gbb_director').write({'user_ids': [(4, D['users']['girish'].id)]})
        D['ops'] = env['hr.employee']
        for i, (name, dept, job) in enumerate(OPERATORS):
            D['ops'] |= env['hr.employee'].create({
                'name': name, 'department_id': D['dept'][dept].id, 'job_title': job,
                'gbb_staff_type': 'worker' if dept not in ('Quality', 'Store') else 'staff',
                'gbb_group': ('G1', 'G2', 'COMMON')[i % 3], 'barcode': 'GBB%03d' % (101 + i),
                'hourly_cost': 450.0,
            })
        for emp in D['emp'].values():
            emp.hourly_cost = 600.0
        return '%s users (password %s), %s operators' % (len(USERS), DEMO_PASSWORD, len(OPERATORS))

    def _load_partners(self, D):
        env = self.env
        Ind = env['res.partner.industry']
        india = env.ref('base.in')
        states = {s.code: s for s in env['res.country.state'].search([('country_id', '=', india.id)])}
        city_state = {'Pune': 'MH', 'Aurangabad': 'MH', 'Nashik': 'MH', 'Waluj': 'MH', 'Hosur': 'TN',
                      'Chennai': 'TN', 'Bengaluru': 'KA'}
        D['cust'] = []
        for name, ref, city, seg, machines in CUSTOMERS:
            ind = Ind.search([('name', '=', seg)], limit=1) or Ind.create({'name': seg})
            D['cust'].append(env['res.partner'].create({
                'name': name, 'is_company': True, 'ref': ref or False, 'city': city or False,
                'state_id': states.get(city_state.get(city)).id if city_state.get(city) else False,
                'country_id': india.id, 'industry_id': ind.id, 'gbb_machine_types': machines,
                'customer_rank': 1, 'property_payment_term_id': env.ref('gbb_erp.payment_term_gbb').id,
            }))
        env['res.partner'].create({'name': 'Abhiraj Patil', 'parent_id': D['cust'][2].id, 'function': 'Purchase'})
        D['vend'] = {}
        for name, city, role in VENDORS:
            D['vend'][role] = env['res.partner'].create({
                'name': name, 'is_company': True, 'city': city, 'state_id': states['MH'].id,
                'country_id': india.id, 'supplier_rank': 1,
            })
        return '%s customers, %s vendors' % (len(CUSTOMERS), len(VENDORS))

    def _tax(self, kind, amount=18):
        Tax = self.env['account.tax']
        tax = Tax.search([('type_tax_use', '=', kind), ('amount', '=', amount), ('company_id', '=', self.env.company.id),
                          ('name', 'ilike', 'GST')], limit=1, order='sequence')
        if not tax:
            tax = Tax.search([('type_tax_use', '=', kind), ('amount', '=', amount),
                              ('company_id', '=', self.env.company.id)], limit=1)
        return tax

    def _load_products(self, D):
        env = self.env
        Product = env['product.product']
        uom_kg = env.ref('uom.product_uom_kgm')
        buy = self._ref('purchase_stock.route_warehouse0_buy')
        mto = self._ref('stock.route_warehouse0_mto')
        manuf = self._ref('mrp.route_warehouse0_manufacture')
        sale_tax, pur_tax = self._tax('sale'), self._tax('purchase')
        D['grade'] = {}
        for name, dens, rate in GRADES:
            prod = Product.create({
                'name': 'RM %s' % name, 'type': 'consu', 'is_storable': True, 'uom_id': uom_kg.id,
                'categ_id': env.ref('gbb_erp.categ_raw_material').id, 'standard_price': rate,
                'purchase_ok': True, 'sale_ok': False, 'route_ids': [(6, 0, buy.ids)],
                'supplier_taxes_id': [(6, 0, pur_tax.ids)], 'l10n_in_hsn_code': '72288090',
                'seller_ids': [(0, 0, {'partner_id': D['vend']['rm'].id, 'price': rate, 'delay': 5})],
            })
            D['grade'][name] = env['gbb.material.grade'].create(
                {'name': name, 'density': dens, 'rate_kg': rate, 'product_id': prod.id})
        for shape, d, l, w in RM_SIZES:
            env['gbb.rm.size'].create({'shape': shape, 'diameter': d, 'length': l, 'width': w})
        D['std'] = {}
        for name, make, price, role in STD_ITEMS:
            D['std'][name] = Product.create({
                'name': name, 'type': 'consu', 'is_storable': True, 'gbb_is_std': True, 'gbb_make': make,
                'categ_id': env.ref('gbb_erp.categ_boughtout').id, 'standard_price': price,
                'purchase_ok': True, 'sale_ok': True, 'route_ids': [(6, 0, (buy | mto).ids)],
                'supplier_taxes_id': [(6, 0, pur_tax.ids)], 'taxes_id': [(6, 0, sale_tax.ids)],
                'l10n_in_hsn_code': '84122100' if 'HYD' in name or 'Cylinder' in name else '73181500',
                'seller_ids': [(0, 0, {'partner_id': D['vend'][role].id, 'price': price, 'delay': 21 if role == 'hyd' else 7})],
            })
        D['service'] = {}
        for name, role, price in (('Hardening (job work)', 'hardening', 45.0), ('Plating (job work)', 'plating', 30.0),
                                  ('Blackening (job work)', 'plating', 18.0)):
            D['service'][name.split(' ')[0]] = Product.create({
                'name': name, 'type': 'service', 'uom_id': uom_kg.id, 'purchase_ok': True, 'sale_ok': False,
                'categ_id': env.ref('gbb_erp.categ_jobwork').id, 'purchase_method': 'purchase',
                'supplier_taxes_id': [(6, 0, pur_tax.ids)], 'l10n_in_hsn_code': '998898',
                'seller_ids': [(0, 0, {'partner_id': D['vend'][role].id, 'price': price})],
            })
        D['consumable'] = Product.create({
            'name': 'Coolant (20 L can)', 'type': 'consu', 'is_storable': True, 'standard_price': 2400,
            'categ_id': env.ref('gbb_erp.categ_consumable').id, 'purchase_ok': True, 'sale_ok': False,
            'route_ids': [(6, 0, buy.ids)],
            'seller_ids': [(0, 0, {'partner_id': D['vend']['fasteners'].id, 'price': 2400})]})
        D['tool'] = Product.create({
            'name': 'End Mill 10 mm Carbide', 'type': 'consu', 'is_storable': True, 'standard_price': 1850,
            'categ_id': env.ref('gbb_erp.categ_tooling').id, 'purchase_ok': True, 'sale_ok': False,
            'route_ids': [(6, 0, buy.ids)],
            'seller_ids': [(0, 0, {'partner_id': D['vend']['gauge'].id, 'price': 1850})]})
        D['routes'] = {'buy': buy, 'mto': mto, 'manuf': manuf}
        D['sale_tax'] = sale_tax
        return '%s grades, %s standard items' % (len(GRADES), len(STD_ITEMS))

    def _load_machines(self, D):
        env = self.env
        D['wc'] = {}
        machine_cat = env.ref('gbb_erp.equipment_categ_machine')
        inst_cat = env.ref('gbb_erp.equipment_categ_instrument')
        for name, mtype, group, cost in MACHINES:
            wc = env['mrp.workcenter'].create({
                'name': name, 'code': name[:12], 'gbb_machine_type': mtype, 'gbb_group': group,
                'costs_hour': cost, 'time_start': 30 if mtype in ('VMC', 'CNC') else 0,
                'oee_target': 85,
            })
            D['wc'][name] = wc
            if mtype not in ('DESIGN',):
                env['maintenance.equipment'].create({
                    'name': name, 'category_id': machine_cat.id, 'gbb_workcenter_id': wc.id,
                    'serial_no': 'GBB-M-%s' % wc.id, 'gbb_is_instrument': False,
                    'technician_user_id': D['users']['planning'].id,
                })
        today = fields.Date.context_today(self)
        makers = {}
        for i, (name, spec, serial, maker, lc, status) in enumerate(INSTRUMENTS):
            makers[maker] = makers.get(maker) or env['res.partner'].search([('name', '=', maker)], limit=1) \
                or env['res.partner'].create({'name': maker, 'is_company': True})
            cal = today - relativedelta(months=(i * 5) % 13)
            env['maintenance.equipment'].create({
                'name': name, 'category_id': inst_cat.id, 'gbb_is_instrument': True, 'gbb_spec': spec,
                'serial_no': serial, 'partner_id': makers[maker].id, 'gbb_least_count': lc,
                'gbb_error_acceptable': 0.005, 'gbb_cal_frequency': '12', 'gbb_cal_date': cal,
                'gbb_actual_error': {'ok': 0.002, 'notok': 0.008, 'new': 0.0}[status],
                'gbb_acceptance': status,
            })
        return '%s work centers, %s instruments' % (len(MACHINES), len(INSTRUMENTS))

    def _load_stock(self, D):
        env = self.env
        loc = env.ref('stock.stock_location_stock')
        Quant = env['stock.quant'].with_context(inventory_mode=True)
        quants = Quant
        for name, grade in D['grade'].items():
            quants |= Quant.create({'product_id': grade.product_id.id, 'location_id': loc.id,
                                    'inventory_quantity': 800 if name != 'AL 6061' else 120})
        stock_std = {'Dowel Pin 8x30': 400, 'Allen Bolt M10x40': 600, 'T-Nut M16': 60, 'Eye Bolt M12': 40,
                     'Dial Gauge': 3, 'Hydraulic Coupler': 10, 'Rest Pad / Locator': 12, 'Pull Stud': 20}
        for name, qty in stock_std.items():
            quants |= Quant.create({'product_id': D['std'][name].id, 'location_id': loc.id, 'inventory_quantity': qty})
        quants |= Quant.create({'product_id': D['consumable'].id, 'location_id': loc.id, 'inventory_quantity': 3})
        quants |= Quant.create({'product_id': D['tool'].id, 'location_id': loc.id, 'inventory_quantity': 8})
        quants.action_apply_inventory()
        wh = env.ref('stock.warehouse0')
        OP = env['stock.warehouse.orderpoint']
        for prod, mn, mx in ((D['consumable'], 5, 10), (D['tool'], 10, 25), (D['std']['Dial Gauge'], 2, 6),
                             (D['std']['Allen Bolt M10x40'], 200, 800), (D['std']['T-Nut M16'], 40, 100)):
            OP.create({'product_id': prod.id, 'warehouse_id': wh.id, 'location_id': loc.id,
                       'product_min_qty': mn, 'product_max_qty': mx, 'trigger': 'manual'})
        return 'opening stock for %s items, 5 reorder rules' % len(quants)

    def _load_inquiries(self, D):
        env = self.env
        today = fields.Date.context_today(self)
        stages = {
            'open': env.ref('crm.stage_lead1'), 'process': env.ref('crm.stage_lead2'),
            'layout': env.ref('gbb_erp.stage_layout_submit'), 'quote': env.ref('crm.stage_lead3'),
            'hold': env.ref('gbb_erp.stage_hold'), 'won': env.ref('crm.stage_lead4'),
        }
        FT = env['gbb.fixture.type']
        D['leads'] = []
        team = self._ref('sales_team.team_sales_department')
        for idx, (ago, ci, ftype, qty, comp, mat, machine, stage, booked, group, value) in enumerate(INQUIRIES):
            date = today - timedelta(days=ago)
            cust = D['cust'][ci]
            ft = FT.search([('name', '=ilike', ftype)], limit=1)
            vals = {
                'name': '%s %s fixture for %s' % (ftype, 'x%s' % qty, comp), 'type': 'opportunity',
                'partner_id': cust.id, 'gbb_inquiry_date': date, 'gbb_fixture_type_id': ft.id,
                'gbb_fixture_qty': qty, 'gbb_component': comp, 'gbb_component_material': mat,
                'gbb_machine_model': machine, 'gbb_group': group, 'user_id': D['users'][booked].id,
                'expected_revenue': value, 'team_id': team.id if team else False,
                'stage_id': stages.get(stage, stages['open']).id,
            }
            if stage not in ('open',):
                vals.update({
                    'ir_tolerances': 'yes' if idx % 4 else 'partial', 'ir_stroke': 'yes', 'ir_component_feasible': 'yes',
                    'ir_feasible': 'YES' if idx % 5 else 'CONDITIONAL',
                    'ir_fixture_type': 'hmc' if 'HMC' in ftype else ('turning' if 'VTL' in ftype else 'vmc_stationary'),
                    'ir_part_material': mat, 'ir_input_condition': 'As Cast' if 'Cast' in mat or mat in ('CI', 'AL') else 'CNC',
                    'ir_setups': 2, 'ir_hyd_elements': 'GBB / Kosmek', 'ir_reviewed_by': D['users']['girish'].id,
                    'ir_review_date': date + timedelta(days=2),
                })
            lead = env['crm.lead'].create(vals)
            lead.message_post(body=_('Inquiry received by email with component drawing (2D + 3D).'))
            if stage == 'lost':
                lead.action_set_lost(lost_reason_id=env.ref('gbb_erp.lost_reason_price').id)
            D['leads'].append(lead)
        return '%s inquiries (%s to %s)' % (len(D['leads']), D['leads'][0].gbb_inquiry_no, D['leads'][-1].gbb_inquiry_no)

    def _fixture_product(self, D, lead, suffix=''):
        env = self.env
        return env['product.product'].create({
            'name': '%s Fixture for %s%s' % (lead.gbb_fixture_type_id.name or '', lead.gbb_component, suffix),
            'type': 'consu', 'is_storable': True, 'gbb_is_fixture': True, 'sale_ok': True, 'purchase_ok': False,
            'categ_id': env.ref('gbb_erp.categ_fixtures').id, 'l10n_in_hsn_code': '84669400',
            'taxes_id': [(6, 0, D['sale_tax'].ids)], 'route_ids': [(6, 0, D['routes']['manuf'].ids)],
            'invoice_policy': 'order',
        })

    def _load_quotations(self, D):
        env = self.env
        SO = env['sale.order']
        D['quotes'] = {}
        term = env.ref('gbb_erp.payment_term_gbb')
        for idx, lead in enumerate(D['leads']):
            stage = INQUIRIES[idx][7]
            if stage not in ('won', 'quote'):
                continue
            ago, qty, value = INQUIRIES[idx][0], INQUIRIES[idx][3], INQUIRIES[idx][10]
            date = fields.Datetime.now() - timedelta(days=ago - 6)
            lines = []
            n_ops = 2 if qty >= 2 and 'Tail' not in lead.gbb_component and 'Cradle' not in lead.gbb_component else 1
            for op in range(n_ops):
                prod = self._fixture_product(D, lead, ' OP-%s0' % (op + 1) if n_ops > 1 else '')
                lines.append((0, 0, {'product_id': prod.id, 'product_uom_qty': qty if n_ops == 1 else max(1, qty // n_ops),
                                     'name': '%s\nHSN 84669400' % prod.name}))
            so = SO.create({
                'partner_id': lead.partner_id.id, 'opportunity_id': lead.id, 'date_order': date,
                'payment_term_id': term.id, 'gbb_machine': lead.gbb_machine_model, 'gbb_delivery_weeks': 5,
                'user_id': lead.user_id.id, 'team_id': lead.team_id.id, 'order_line': lines,
                'validity_date': (date + timedelta(days=30)).date(),
            })
            # cost breakup per fixture, scaled so the quote lands near the inquiry value
            for line in so.order_line:
                line.action_gbb_load_default_breakup()
                target = value / max(1, sum(so.order_line.mapped('product_uom_qty')))
                factor = target / max(1.0, line.gbb_breakup_total)
                for row in line.gbb_breakup_ids:
                    if row.kind == 'std' and row.qty == 0 and 'Work Support' in row.name:
                        row.qty = 2
                    if row.amount_manual:
                        row.amount_manual = round(row.amount_manual * factor, -2)
                line._gbb_apply_breakup()
            if stage == 'won':
                so.write({'gbb_approval_state': 'approved', 'gbb_approved_by': D['users']['girish'].id,
                          'gbb_approved_on': date + timedelta(days=1), 'state': 'sent'})
            elif idx % 2:
                so.with_user(D['users']['arun']).action_gbb_submit()
            else:
                so.write({'gbb_approval_state': 'approved', 'gbb_approved_by': D['users']['girish'].id,
                          'gbb_approved_on': date + timedelta(days=1), 'state': 'sent', 'gbb_negotiation': True})
            D['quotes'][idx] = so
        # one quotation revision (customer asked for a 4th axis option)
        first_quote = D['quotes'].get(5)
        if first_quote:
            rev = env['sale.order'].browse(first_quote.action_gbb_new_revision()['res_id'])
            rev.order_line[:1].gbb_risk = 25000
            rev.order_line._gbb_apply_breakup()
            rev.gbb_approval_state = 'to_approve'
        return '%s quotations' % len(D['quotes'])

    def _load_orders(self, D):
        env = self.env
        D['orders'] = []
        refs = ['1000664452 / 0', 'PO 3300003465', 'PO 3300003512', '1600005881', 'LOI Received']
        for n, (idx, so) in enumerate(sorted(D['quotes'].items())):
            if INQUIRIES[idx][7] != 'won':
                continue
            ago = INQUIRIES[idx][0]
            order_date = fields.Datetime.now() - timedelta(days=ago - 15)
            so.action_confirm()
            so.write({
                'date_order': order_date, 'client_order_ref': refs[n % len(refs)],
                'commitment_date': order_date + timedelta(weeks=so.gbb_delivery_weeks + 3),
                'gbb_allotted_date': (order_date + timedelta(days=2)).date(),
                'or_tol_ok': True, 'or_stroke_ok': True, 'or_machining_ok': True, 'or_envelope_ok': True,
                'or_payment_terms': 'As per Quote', 'or_delivery': '%s weeks' % so.gbb_delivery_weeks,
                'or_man_material': 'yes', 'or_bo_lead_time': 'Kosmek items 3 weeks', 'or_as_expected': 'YES',
                'or_point_ids': [(0, 0, {'name': p, 'done': i < 2}) for i, p in enumerate(
                    ['Customer drawing revision confirmed', 'Hydraulic make agreed (Kosmek)',
                     'Trial component availability at GBB'])],
            })
            so.gbb_project_ids.write({'date_start': order_date.date(), 'date': so.commitment_date.date(),
                                      'user_id': D['users']['girish'].id})
            D['leads'][idx].action_set_won_rainbowman()
            D['orders'].append(so)
        return '%s orders, %s design projects' % (len(D['orders']), sum(len(o.gbb_project_ids) for o in D['orders']))

    def _load_design(self, D):
        env = self.env
        designers = [D['users']['sandip'], D['users']['netaji'], D['users']['rushikesh']]
        projects = env['project.project'].search([('gbb_sale_order_id', 'in', [o.id for o in D['orders']])], order='id')
        D['projects'] = projects
        # progress per project: (stage, tasks done)
        order_plan = ['completed', 'final_model', 'released', 'released', 'modeling', 'inputs']
        order_index = {o.id: i for i, o in enumerate(D['orders'])}
        stage_idx = {k: i for i, (k, _l) in enumerate(DESIGN_STAGES)}
        done_stage = env.ref('gbb_erp.task_stage_design_done')
        prog_stage = env.ref('gbb_erp.task_stage_design_progress')
        today = fields.Date.context_today(self)
        n_ts = 0
        for i, proj in enumerate(projects):
            oi = order_index.get(proj.gbb_sale_order_id.id, len(order_plan) - 1)
            stage = order_plan[min(oi, len(order_plan) - 1)]
            designer = designers[i % 3]
            proj.write({'gbb_designer_id': designer.id, 'allocated_hours': 120})
            ndone = min(19, stage_idx.get(stage, 0) + (1 if stage in ('released', 'completed') else 0))
            tasks = proj.task_ids.sorted('sequence')
            start = proj.gbb_sale_order_id.date_order.date() if proj.gbb_sale_order_id.date_order else today
            for t in tasks:
                t.date_deadline = datetime.combine(start + timedelta(days=int(t.sequence * 1.5)), time(17, 30))
                t.allocated_hours = 6 if t.sequence <= 19 else 8
            tasks.filtered(lambda t: t.sequence <= ndone).write({'stage_id': done_stage.id, 'state': '1_done'})
            nxt = tasks.filtered(lambda t: t.sequence == ndone + 1)
            nxt.write({'stage_id': prog_stage.id})
            if stage in ('completed',):
                tasks.write({'stage_id': done_stage.id, 'state': '1_done'})
            # daily work sheet = timesheets on the design activities
            emp = D['emp'][designer.login.split('@')[0]]
            for t in tasks.filtered(lambda t: t.sequence <= max(ndone, 1) and t.sequence <= 19):
                for k in range(2):
                    day = start + timedelta(days=int(t.sequence * 1.5) - k)
                    if day > today:
                        continue
                    env['account.analytic.line'].create({
                        'name': t.name[4:], 'project_id': proj.id, 'task_id': t.id, 'employee_id': emp.id,
                        'date': day, 'unit_amount': random.choice([3.0, 4.0, 4.5, 7.5]),
                    })
                    n_ts += 1
            proj.gbb_design_stage = stage
        # checklists
        Chk = env['gbb.checklist']
        fx = env.ref('gbb_erp.tmpl_fixture_design')
        for proj in projects[:3]:
            chk = Chk.create({'template_id': fx.id, 'project_id': proj.id, 'subject': proj.name,
                              'prepared_by_id': proj.gbb_designer_id.id, 'gbb_group': proj.gbb_group,
                              'checked_by_ids': [(6, 0, D['users']['girish'].ids)],
                              'approved_by_id': D['users']['girish'].id,
                              'design_start': proj.date_start, 'design_hours': 96})
            chk.action_all_yes()
            for l in chk.line_ids.filtered(lambda l: l.answer_type in ('text', 'value') and not l.is_section):
                l.answer_text = {'Number of setups': '2', 'Fixture weight': '185 kg', 'X-Stroke': '800',
                                 'Y-Stroke': '500', 'Z-Stroke': '510'}.get(l.name, 'OK as per design')
            for l in chk.line_ids.filtered(lambda l: 'indexer' in l.name.lower() or '4th axis' in l.name.lower()):
                l.answer_yn = 'na'
            chk.action_done()
        cradle_proj = projects.filtered(lambda p: 'Cradle' in (p.name or ''))[:1]
        if cradle_proj:
            chk = Chk.create({'template_id': env.ref('gbb_erp.tmpl_cradle_design').id, 'project_id': cradle_proj.id,
                              'subject': cradle_proj.name, 'prepared_by_id': cradle_proj.gbb_designer_id.id})
            for l in chk.line_ids.filtered(lambda l: not l.is_section):
                if l.answer_type == 'yesno':
                    l.answer_yn = 'yes'
                else:
                    l.answer_text = {'1) Centre height': '250', '9) Cradle weight': '320 kg'}.get(l.name, 'Checked')
            chk.action_done()
        if len(projects) > 1:
            rev = Chk.create({'template_id': env.ref('gbb_erp.tmpl_internal_review').id, 'project_id': projects[1].id,
                              'subject': projects[1].name, 'checked_by_ids': [(6, 0, (D['users']['girish'] | D['users']['planning']).ids)]})
            for i, l in enumerate(rev.line_ids):
                l.answer_ok = 'revise' if i == 2 else 'ok'
                if i == 2:
                    l.remark = 'Z clearance tight on MAZAK HCN 5000, raise base by 10 mm'
        return '%s projects, %s timesheet entries, 5 checklists' % (len(projects), n_ts)

    def _build_bom(self, D, proj, sale_line):
        env = self.env
        fixture = sale_line.product_id
        lines = []
        D.setdefault('parts', {})
        for name, qty, grade, shape, dd, ll, ww, hh in FIXTURE_PARTS:
            part = env['product.product'].create({
                'name': '%s · %s' % (name, proj.gbb_project_code), 'type': 'consu', 'is_storable': True,
                'categ_id': env.ref('gbb_erp.categ_fixture_parts').id, 'sale_ok': False, 'purchase_ok': False,
                'gbb_grade_id': D['grade'][grade].id,
                'route_ids': [(6, 0, (D['routes']['manuf'] | D['routes']['mto']).ids)],
            })
            lines.append((0, 0, {'product_id': part.id, 'product_qty': qty, 'gbb_grade_id': D['grade'][grade].id,
                                 'gbb_shape': shape, 'gbb_fin_d': dd, 'gbb_fin_l': ll, 'gbb_fin_w': ww,
                                 'gbb_fin_h': hh, 'gbb_spare': 1 if name in ('Locating Pin', 'Clamp Pad') else 0,
                                 'gbb_critical': name in ('Locating Pin',)}))
        for name, qty in FIXTURE_STD:
            lines.append((0, 0, {'product_id': D['std'][name].id, 'product_qty': qty}))
        asm = D['wc']['Assembly Bench 1' if proj.gbb_group != 'G2' else 'Assembly Bench 2']
        bom = env['mrp.bom'].create({
            'product_tmpl_id': fixture.product_tmpl_id.id, 'product_qty': 1, 'project_id': proj.id,
            'gbb_rev': '01', 'bom_line_ids': lines,
            'operation_ids': [(0, 0, {'name': 'Assembly, Piping & Trial', 'workcenter_id': asm.id,
                                      'time_mode': 'manual', 'time_cycle_manual': 16 * 60}),
                              (0, 0, {'name': 'Final Inspection (CMM)', 'workcenter_id': asm.id,
                                      'time_mode': 'manual', 'time_cycle_manual': 4 * 60})],
        })
        bom.action_gbb_generate_part_boms()
        return bom

    def _load_boms(self, D):
        D['boms'] = {}
        for proj in D['projects']:
            if proj.gbb_design_stage not in ('released', 'completed'):
                continue
            if proj.gbb_design_stage == 'released' and proj == D['projects'].filtered(
                    lambda p: p.gbb_design_stage == 'released')[-1:]:
                continue  # one released project is left with "BOM pending" to show the alert
            bom = self._build_bom(D, proj, proj.gbb_sale_line_id)
            bom.with_context(gbb_force=True).action_gbb_send_to_purchase()
            D['boms'][proj.id] = bom
        return '%s fixture BOMs with part BOMs and routes' % len(D['boms'])

    def _produce(self, mo):
        mo.action_assign()
        mo.qty_producing = mo.product_qty
        for move in mo.move_raw_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        mo.with_context(skip_backorder=True, skip_consumption=True).button_mark_done()

    def _load_manufacturing(self, D):
        env = self.env
        MO = env['mrp.production']
        D['mos'] = {}
        done_projs = set()
        for n, (pid, bom) in enumerate(D['boms'].items()):
            proj = env['project.project'].browse(pid)
            product = bom.product_tmpl_id.product_variant_id
            mo = MO.create({'product_id': product.id, 'product_qty': proj.gbb_fixture_qty or 1, 'bom_id': bom.id,
                            'project_id': proj.id, 'origin': proj.gbb_sale_order_id.name,
                            'date_deadline': proj.date, 'user_id': D['users']['planning'].id})
            mo.action_confirm()
            D['mos'][pid] = mo
            children = mo._get_children()
            if proj.gbb_design_stage == 'completed':
                done_projs.add(proj.id)
        # purchase: the MTO procurements created RFQs for bought-out items; type and confirm them
        POs = env['purchase.order'].search([('state', '=', 'draft')])
        for po in POs:
            types = set(po.order_line.mapped('product_id.categ_id').ids)
            po.gbb_po_type = 'RM' if env.ref('gbb_erp.categ_raw_material').id in types else 'BOUGHTOUT'
            origin_mo = MO.search([('name', 'in', (po.origin or '').replace(' ', '').split(','))], limit=1)
            po.project_id = origin_mo.project_id.id or False
        # receive bought-out for the completed project and one more, leave the rest open
        n_conf = 0
        for po in POs:
            po.button_confirm()
            n_conf += 1
        # a raw material PO raised manually by stores
        first = D['projects'][:1]
        rm_po = env['purchase.order'].create({
            'partner_id': D['vend']['rm'].id, 'gbb_po_type': 'RM', 'project_id': first.id,
            'order_line': [(0, 0, {'product_id': D['grade']['20MnCr5'].product_id.id, 'product_qty': 250,
                                   'price_unit': 95.0}),
                           (0, 0, {'product_id': D['grade']['EN31'].product_id.id, 'product_qty': 120,
                                   'price_unit': 110.0})],
        })
        rm_po.button_confirm()
        for picking in rm_po.picking_ids:
            for m in picking.move_ids:
                m.quantity = m.product_uom_qty
                m.picked = True
            picking.button_validate()
        rm_po.action_create_invoice()
        bill = rm_po.invoice_ids[:1]
        if bill:
            bill.invoice_date = fields.Date.context_today(self)
            bill.ref = 'DS/2026/0418'
            bill.action_post()
        # job work: hardening sent, overdue
        jw = env['purchase.order'].create({
            'partner_id': D['vend']['hardening'].id, 'gbb_po_type': 'JOBWORK', 'gbb_process': 'hardening',
            'project_id': (D['projects'][1:2] or first).id, 'gbb_jw_status': 'process',
            'date_planned': fields.Datetime.now() - timedelta(days=2),
            'order_line': [(0, 0, {'product_id': D['service']['Hardening'].id, 'product_qty': 38.5, 'price_unit': 45.0,
                                   'name': 'Hardening of Locating Pins, Taper Pins, Bushes (HRC 58-60)'})],
        })
        jw.button_confirm()
        jw2 = env['purchase.order'].create({
            'partner_id': D['vend']['plating'].id, 'gbb_po_type': 'JOBWORK', 'gbb_process': 'plating',
            'project_id': first.id, 'gbb_jw_status': 'received',
            'order_line': [(0, 0, {'product_id': D['service']['Plating'].id, 'product_qty': 22, 'price_unit': 30.0,
                                   'name': 'Hard chrome plating of clamp pads'})],
        })
        jw2.button_confirm()
        jw2.order_line.qty_received = 22
        # complete production for the finished project; start work on the next one
        n_done = 0
        for pid, mo in D['mos'].items():
            proj = env['project.project'].browse(pid)
            children = mo._get_children()
            if pid in done_projs:
                for po in env['purchase.order'].search([('project_id', '=', pid), ('state', '=', 'purchase')]):
                    for picking in po.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
                        for m in picking.move_ids:
                            m.quantity = m.product_uom_qty
                            m.picked = True
                        picking.with_context(skip_backorder=True).button_validate()
                for child in children:
                    self._produce(child)
                    n_done += 1
                self._produce(mo)
                n_done += 1
            elif proj.gbb_design_stage == 'released':
                # parts partly machined: first child done, work started on the next
                if children:
                    try:
                        with env.cr.savepoint():
                            self._produce(children[0])
                            n_done += 1
                    except Exception as e:
                        _logger.info('GBB demo: part MO not produced (%s)', e)
                    for child in children[1:3]:
                        child.action_assign()
                        wo = child.workorder_ids[:1]
                        if wo:
                            wo.button_start()
        return '%s fixture MOs, %s POs confirmed, %s MOs completed' % (len(D['mos']), n_conf, n_done)

    def _load_design_change(self, D):
        env = self.env
        # take a released project whose POs are already raised
        target = None
        for pid, bom in D['boms'].items():
            proj = env['project.project'].browse(pid)
            if proj.gbb_design_stage == 'released':
                target = bom
                break
        if not target:
            return 'no released BOM to revise'
        wiz = env['gbb.bom.revision.wizard'].create({
            'bom_id': target.id, 'reason': 'customer',
            'change_details': 'Customer changed clamping point after DAP review: 2 extra swing clamps, '
                              'locating pin dia changed 20 to 25, rough guide base removed.'})
        new_bom = env['mrp.bom'].browse(wiz.action_create_revision()['res_id'])
        swing = new_bom.bom_line_ids.filtered(lambda l: l.product_id == D['std']['Swing Clamp Cylinder'])
        swing.product_qty += 2
        pin = new_bom.bom_line_ids.filtered(lambda l: l.product_id.name.startswith('Locating Pin'))
        pin.write({'gbb_fin_d': 25})
        new_bom.bom_line_ids.filtered(lambda l: l.product_id.name.startswith('Rough Guide Base')).unlink()
        new_bom.bom_line_ids = [(0, 0, {'product_id': D['std']['Flow Control Valve'].id, 'product_qty': 1})]
        new_bom.action_gbb_release_revision()
        dcr = env['gbb.design.change'].search([('bom_new_id', '=', new_bom.id)], limit=1)
        dcr.approved_by_id = D['users']['girish']
        env['gbb.lesson.learnt'].create([
            {'project_id': target.project_id.id, 'category': 'design', 'user_id': D['users']['sandip'].id,
             'name': 'Confirm clamping scheme with customer before DAP freeze; late change cost 2 swing clamps and a re-order.'},
            {'project_id': target.project_id.id, 'category': 'mfg', 'user_id': D['users']['planning'].id,
             'name': 'EN31 pins: order hardening slot with RM PO to avoid 7-day wait.'},
            {'project_id': D['projects'][:1].id, 'category': 'trial', 'user_id': D['users']['sachin'].id,
             'name': 'Leak test the manifold at 1.5x pressure before dispatch (JLR complaint).'},
        ])
        return '%s: Rev %s -> %s, %s impacted lines' % (dcr.name, target.gbb_rev, new_bom.gbb_rev, len(dcr.line_ids))

    def _load_dispatch(self, D):
        env = self.env
        so = None
        for proj in D['projects']:
            if proj.gbb_design_stage == 'completed':
                so = proj.gbb_sale_order_id
                break
        msgs = []
        if so:
            for picking in so.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
                picking.action_assign()
                for m in picking.move_ids:
                    m.quantity = m.product_uom_qty
                    m.picked = True
                picking.write({'gbb_transporter_id': D['vend']['transport'].id, 'gbb_vehicle_no': 'MH20 EL 4521',
                               'gbb_lr_no': 'OTC/2026/1187', 'gbb_eway_bill': '2712 4589 6631',
                               'gbb_customer_po': so.client_order_ref})
                chk = env['gbb.checklist'].create({'template_id': env.ref('gbb_erp.tmpl_packaging').id,
                                                   'picking_id': picking.id, 'project_id': so.gbb_project_ids[:1].id,
                                                   'subject': so.order_line[:1].name})
                chk.line_ids.write({'checked': True})
                chk.action_done()
                picking.with_context(skip_backorder=True).button_validate()
                msgs.append(picking.name)
            invoice = so._create_invoices()
            invoice.action_post()
            reg = env['account.payment.register'].with_context(
                active_model='account.move', active_ids=invoice.ids).create({})
            reg.action_create_payments()
            msgs.append(invoice.name)
            so.gbb_project_ids.write({'gbb_design_stage': 'completed'})
        # 50% advance invoice on the most recent order
        last = D['orders'][-1] if D['orders'] else None
        if last and last != so:
            wiz = env['sale.advance.payment.inv'].with_context(
                active_model='sale.order', active_ids=last.ids).create(
                {'advance_payment_method': 'percentage', 'amount': 50})
            wiz.create_invoices()
            adv = last.invoice_ids.filtered(lambda m: m.state == 'draft')
            adv.action_post()
            msgs.append('advance %s' % adv.name)
        # a material requisition from the shop floor and a returnable challan
        mr_type = env.ref('gbb_erp.picking_type_mr')
        mr = env['stock.picking'].create({
            'picking_type_id': mr_type.id, 'location_id': mr_type.default_location_src_id.id,
            'location_dest_id': mr_type.default_location_dest_id.id, 'gbb_requested_by_id': D['ops'][0].id,
            'gbb_department_id': D['dept']['Production'].id, 'project_id': D['projects'][1:2].id,
            'move_ids': [(0, 0, {'product_id': D['consumable'].id, 'product_uom_qty': 1,
                                 'product_uom': D['consumable'].uom_id.id, 'location_id': mr_type.default_location_src_id.id,
                                 'location_dest_id': mr_type.default_location_dest_id.id}),
                         (0, 0, {'product_id': D['tool'].id, 'product_uom_qty': 2,
                                 'product_uom': D['tool'].uom_id.id, 'location_id': mr_type.default_location_src_id.id,
                                 'location_dest_id': mr_type.default_location_dest_id.id})],
        })
        mr.action_confirm()
        mr.action_assign()
        rc_type = env.ref('gbb_erp.picking_type_returnable')
        rc = env['stock.picking'].create({
            'picking_type_id': rc_type.id, 'partner_id': D['cust'][1].id, 'gbb_returnable': True,
            'gbb_expected_return': fields.Date.context_today(self) + timedelta(days=10),
            'location_id': rc_type.default_location_src_id.id, 'location_dest_id': rc_type.default_location_dest_id.id,
            'origin': 'Fixture sent back for trial correction',
            'move_ids': [(0, 0, {'product_id': D['std']['Dial Gauge'].id, 'product_uom_qty': 1,
                                 'product_uom': D['std']['Dial Gauge'].uom_id.id,
                                 'location_id': rc_type.default_location_src_id.id,
                                 'location_dest_id': rc_type.default_location_dest_id.id})],
        })
        rc.action_confirm()
        msgs += [mr.name, rc.name]
        return ', '.join(msgs)

    def _load_quality(self, D):
        env = self.env
        Chk = env['gbb.checklist']
        msgs = 0
        for pid, mo in D['mos'].items():
            proj = env['project.project'].browse(pid)
            if mo.state == 'done':
                chk = Chk.create({'template_id': env.ref('gbb_erp.tmpl_insp_fixture').id, 'project_id': pid,
                                  'production_id': mo.id, 'subject': mo.product_id.name,
                                  'prepared_by_id': D['users']['quality'].id})
                actual = {'Guide Bush CD': 565.012, 'Guide Bush Inline': 0.011, 'Tooling Bush to OP-10 Setup_X': 211.968,
                          'Tooling Bush to OP-10 Setup_Y': 17.53, 'Location Pin CD_OP-10_R': 95.752,
                          'Resting Height 55 mm': 55.008, 'Resting Height 75 mm': 74.991}
                for l in chk.line_ids:
                    if l.name in actual:
                        l.actual = actual[l.name]
                    elif l.answer_type == 'value':
                        l.answer_text = '420 x 320 OK'
                chk.action_done()
                msgs += 1
        cb = Chk.create({'template_id': env.ref('gbb_erp.tmpl_insp_casting').id, 'project_id': D['projects'][1:2].id,
                         'subject': 'Casting base for HMC tombstone', 'prepared_by_id': D['users']['quality'].id})
        for l in cb.line_ids:
            if l.answer_type == 'yesno':
                l.answer_yn = 'yes'
            else:
                l.answer_text = {'Hardness': '190 BHN'}.get(l.name, '+3 mm allowance OK')
        cb.result = 'pass'
        cb.action_done()
        # job rejections on scrap
        Tag = env['stock.scrap.reason.tag']
        tags = {n: (Tag.search([('name', '=', n)], limit=1) or Tag.create({'name': n}))
                for n in ('Dimension out of tolerance', 'Setting error', 'Tool breakage')}
        parts = env['product.product'].search([('categ_id', '=', env.ref('gbb_erp.categ_fixture_parts').id)], limit=6)
        stock_loc = env.ref('stock.stock_location_stock')
        n_scrap = 0
        for i, part in enumerate(parts[:2]):
            qty = part.qty_available
            if qty <= 0:
                quant = env['stock.quant'].with_context(inventory_mode=True).create(
                    {'product_id': part.id, 'location_id': stock_loc.id, 'inventory_quantity': 1})
                quant.action_apply_inventory()
            scrap = env['stock.scrap'].create({
                'product_id': part.id, 'scrap_qty': 1, 'location_id': stock_loc.id,
                'scrap_reason_tag_ids': [(6, 0, tags['Dimension out of tolerance' if i == 0 else 'Setting error'].ids)],
                'gbb_project_id': D['projects'][:1].id, 'gbb_workcenter_id': D['wc']['SURYA 1' if i == 0 else 'DOOSAN'].id,
                'gbb_operator_id': D['ops'][i].id, 'gbb_reworkable': i == 1,
                'gbb_root_cause': 'Bore 20H7 oversize by 0.03 after hardening' if i == 0 else 'Wrong offset after tool change',
                'gbb_corrective_action': 'Grinding allowance increased to 0.15' if i == 0 else 'Offset check added to setup sheet',
                'gbb_action_status': 'closed' if i == 0 else 'open', 'gbb_responsible_id': D['ops'][4].id,
                'origin': D['projects'][:1].gbb_project_code,
            })
            scrap.action_validate()
            n_scrap += 1
        env['gbb.tool.breakage'].create([
            {'name': 'End Mill 10 mm Carbide', 'workcenter_id': D['wc']['SURYA 2'].id, 'operator_id': D['ops'][1].id,
             'programmer_id': D['emp']['sandip'].id, 'tool_qty': 1, 'amount': 1850, 'reason': 'Feed too high in pocket corner',
             'action': 'Corner feed reduced 40%', 'learning': 'Use trochoidal path for EN31 pockets'},
            {'name': 'Drill 8.5 mm HSS-Co', 'workcenter_id': D['wc']['DOOSAN'].id, 'operator_id': D['ops'][2].id,
             'tool_qty': 2, 'amount': 900, 'reason': 'Chip packing, no peck cycle', 'action': 'Peck cycle added'},
            {'name': 'CNMG Insert', 'workcenter_id': D['wc']['CNC JOBBER JUNIOR'].id, 'operator_id': D['ops'][3].id,
             'tool_qty': 4, 'amount': 1600, 'reason': 'Interrupted cut on casting', 'action': 'Tougher grade insert'},
        ])
        return '%s final inspections, 1 casting inspection, %s rejections, 3 tool breakages' % (msgs, n_scrap)

    def _load_maintenance(self, D):
        env = self.env
        Req = env['maintenance.request']
        machines = env['maintenance.equipment'].search([('gbb_workcenter_id', 'in', [w.id for w in D['wc'].values()])])
        today = fields.Date.context_today(self)
        team = env['maintenance.team'].search([], limit=1)
        n = 0
        for i, eq in enumerate(machines[:8]):
            Req.create({'name': 'Preventive maintenance: %s' % eq.name, 'equipment_id': eq.id,
                        'maintenance_type': 'preventive', 'schedule_date': datetime.combine(today + timedelta(days=3 + i * 4), time(9, 0)),
                        'recurring_maintenance': True, 'repeat_interval': 1, 'repeat_unit': 'month', 'repeat_type': 'forever',
                        'maintenance_team_id': team.id, 'user_id': D['users']['planning'].id, 'duration': 3})
            n += 1
        done_stage = env.ref('maintenance.stage_3', raise_if_not_found=False)
        for eq, prob, hrs in ((machines[0], 'Spindle bearing noise, bearing replaced', 6),
                              (machines[3], 'Hydraulic pressure drop, seal kit replaced', 4),
                              (machines[12] if len(machines) > 12 else machines[1], 'Coolant pump motor burnt', 3)):
            r = Req.create({'name': prob, 'equipment_id': eq.id, 'maintenance_type': 'corrective',
                            'request_date': today - timedelta(days=12), 'duration': hrs,
                            'maintenance_team_id': team.id, 'user_id': D['users']['planning'].id,
                            'schedule_date': datetime.combine(today - timedelta(days=12), time(10, 0))})
            if done_stage:
                r.stage_id = done_stage
            n += 1
        # downtime on the work center feeds OEE
        loss = env['mrp.workcenter.productivity.loss'].search([('loss_type', '=', 'availability')], limit=1)
        if loss:
            env['mrp.workcenter.productivity'].create({
                'workcenter_id': D['wc']['SURYA 1'].id, 'loss_id': loss.id, 'description': 'Spindle bearing replacement',
                'date_start': datetime.combine(today - timedelta(days=12), time(4, 30)),
                'date_end': datetime.combine(today - timedelta(days=12), time(10, 30)),
            })
        # JH daily checks for 3 machines, last 5 working days
        tmpl = env.ref('gbb_erp.tmpl_jh_daily')
        n_jh = 0
        for eq in machines[:3]:
            for k in range(5):
                day = today - timedelta(days=k)
                chk = env['gbb.checklist'].create({'template_id': tmpl.id, 'equipment_id': eq.id, 'date': day,
                                                   'subject': eq.name, 'prepared_by_id': D['users']['planning'].id})
                for j, l in enumerate(chk.line_ids):
                    l.answer_ok = 'notok' if (k == 2 and j == 3 and eq == machines[0]) else 'ok'
                    if l.answer_ok == 'notok':
                        l.remark = 'Pressure 26 bar, informed maintenance'
                chk.action_done()
                n_jh += 1
        return '%s maintenance requests, %s JH checks' % (n, n_jh)

    def _load_customer_care(self, D):
        env = self.env
        proj = env.ref('gbb_erp.project_customer_complaints')
        stage = {k: env.ref('gbb_erp.task_stage_cc_%s' % k) for k in
                 ('received', 'assigned', 'trial1', 'trial2', 'resolved', 'closed')}
        today = fields.Date.context_today(self)
        for i, (ci, prob, fixture, st, user, rca, action) in enumerate(COMPLAINTS):
            env['project.task'].create({
                'name': prob, 'project_id': proj.id, 'partner_id': D['cust'][ci].id, 'gbb_fixture_desc': fixture,
                'gbb_complaint_date': today - timedelta(days=40 - i * 6), 'stage_id': stage[st].id,
                'user_ids': [(6, 0, D['users'][user].ids)],
                'date_deadline': datetime.combine(today + timedelta(days=-5 + i * 3), time(17, 0)),
                'gbb_rca': rca or False, 'gbb_action_taken': action or False,
                'gbb_closure_date': today - timedelta(days=3) if st in ('closed', 'resolved') else False,
                'state': '1_done' if st == 'closed' else '01_in_progress',
            })
        survey = env.ref('gbb_erp.survey_feedback')
        questions = survey.question_ids.filtered(lambda q: q.question_type == 'simple_choice').sorted('sequence')
        for ci, fixture, total in FEEDBACK:
            # spread the total over 11 parameters (1-4 each)
            base, extra = divmod(total, len(questions))
            scores = [min(4, base + (1 if k < extra else 0)) for k in range(len(questions))]
            ui = env['survey.user_input'].create({'survey_id': survey.id, 'partner_id': D['cust'][ci].id,
                                                  'state': 'done', 'nickname': fixture})
            for q, sc in zip(questions, scores):
                ans = q.suggested_answer_ids.filtered(lambda a: a.answer_score == sc)[:1]
                env['survey.user_input.line'].create({'user_input_id': ui.id, 'question_id': q.id,
                                                      'answer_type': 'suggestion', 'suggested_answer_id': ans.id})
        return '%s complaints, %s feedback responses' % (len(COMPLAINTS), len(FEEDBACK))

    def _load_hr(self, D):
        env = self.env
        today = fields.Date.context_today(self)
        levels = {}
        for st in env['hr.skill.type'].search([('name', 'in', ('Machining', 'Fixture Assembly', 'Design'))]):
            levels[st.name] = st
        def add_skill(emp, skill_name, level_idx):
            skill = env['hr.skill'].search([('name', '=', skill_name)], limit=1)
            if not skill:
                return
            lv = skill.skill_type_id.skill_level_ids.sorted('level_progress')
            env['hr.employee.skill'].create({'employee_id': emp.id, 'skill_id': skill.id,
                                             'skill_level_id': lv[min(level_idx, len(lv) - 1)].id,
                                             'skill_type_id': skill.skill_type_id.id})
        skill_map = ['VMC Operation', 'VMC Operation', 'CNC Turning', 'CNC Turning', 'Cylindrical Grinding',
                     'HMC Operation', 'Fixture Assembly', 'Fixture Assembly', 'Hydraulic Piping', 'Inspection (CMM / gauges)']
        for i, emp in enumerate(D['ops'][:10]):
            add_skill(emp, skill_map[i], i % 3)
            if i < 6:
                add_skill(emp, 'CNC Programming', 0)
        for login in ('sandip', 'netaji', 'rushikesh'):
            add_skill(D['emp'][login], '3D Modeling', 2)
            add_skill(D['emp'][login], 'Deflection Analysis', 1)
        tr_type = env.ref('gbb_erp.resume_type_training')
        for emp in D['ops'][:6]:
            env['hr.resume.line'].create({'employee_id': emp.id, 'line_type_id': tr_type.id,
                                          'name': '5S and JH awareness', 'date_start': today - timedelta(days=45),
                                          'date_end': today - timedelta(days=45),
                                          'description': 'Trainer: Production Planner. Score 8/10'})
        for emp in D['ops'][6:9]:
            env['hr.resume.line'].create({'employee_id': emp.id, 'line_type_id': tr_type.id,
                                          'name': 'Hydraulic circuit and leak testing', 'date_start': today - timedelta(days=20),
                                          'description': 'Trainer: Kosmek application engineer. Score 7/10'})
        Leave = env['hr.leave'].with_context(leave_skip_state_check=True, mail_activity_quick_update=True)
        n_leave = 0
        for emp, ltype, start, days in ((D['ops'][0], 'sick', -20, 2), (D['ops'][3], 'casual', -6, 1),
                                        (D['ops'][7], 'earned', 8, 3), (D['emp']['vishal'], 'outstation', -9, 2)):
            d0 = today + timedelta(days=start)
            try:
                with env.cr.savepoint():
                    lv = Leave.create({'employee_id': emp.id, 'holiday_status_id': env.ref('gbb_erp.leave_type_%s' % ltype).id,
                                       'request_date_from': d0, 'request_date_to': d0 + timedelta(days=days - 1),
                                       'name': {'sick': 'Viral fever, certificate attached', 'casual': 'Family function',
                                                'earned': 'Native place visit', 'outstation': 'Fixture trial at TVS Hosur'}[ltype]})
                    if ltype != 'earned':
                        lv.action_approve()
                    n_leave += 1
            except Exception as e:
                _logger.info('GBB demo: leave skipped (%s)', e)
        n_att = 0
        for k in range(1, 6):
            day = today - timedelta(days=k)
            if day.weekday() == 6:
                continue
            for emp in D['ops'][:8]:
                start = datetime.combine(day, time(2, 30)) + timedelta(minutes=random.randint(0, 20))
                env['hr.attendance'].create({'employee_id': emp.id, 'check_in': start,
                                             'check_out': start + timedelta(hours=8, minutes=random.randint(30, 90))})
                n_att += 1
        Adv = env['gbb.employee.advance']
        month = today.strftime('%Y-%m')
        Adv.create([
            {'employee_id': D['ops'][1].id, 'move_type': 'advance', 'amount': 10000, 'date': today - timedelta(days=50),
             'note': 'Medical advance'},
            {'employee_id': D['ops'][1].id, 'move_type': 'deduction', 'amount': 2500,
             'salary_month': (today - relativedelta(months=1)).strftime('%Y-%m')},
            {'employee_id': D['ops'][1].id, 'move_type': 'deduction', 'amount': 2500, 'salary_month': month},
            {'employee_id': D['ops'][6].id, 'move_type': 'advance', 'amount': 5000, 'date': today - timedelta(days=10),
             'note': 'Festival advance'},
        ])
        for emp in D['ops'][:6]:
            emp.sudo().write({'gbb_salary_type': 'hours', 'gbb_pay_category': 'worker', 'gbb_pf': True, 'gbb_esic': True})
        # exit clearance for one helper who resigned
        leaver = D['ops'][11]
        clr = env['gbb.checklist'].create({'template_id': env.ref('gbb_erp.tmpl_clearance').id, 'employee_id': leaver.id,
                                           'subject': leaver.name})
        clr.line_ids[:4].write({'checked': True})
        return '%s leaves, %s attendance records, 4 advance entries, 1 exit clearance' % (n_leave, n_att)

    def _load_security(self, D):
        env = self.env
        today = fields.Date.context_today(self)
        GP = env['gbb.gate.pass']
        GP.create([
            {'employee_id': D['ops'][2].id, 'date': today - timedelta(days=1), 'entry_type': 'missing',
             'time_in': 8.0, 'time_out': 17.0, 'reason': 'Punch machine not reading card',
             'logged_by_id': D['users']['security'].id},
            {'employee_id': D['ops'][5].id, 'date': today - timedelta(days=2), 'entry_type': 'gatepass',
             'time_in': 14.5, 'time_out': 13.0, 'reason': 'Bank work, permission by planner',
             'logged_by_id': D['users']['security'].id},
            {'employee_id': D['ops'][0].id, 'date': today - timedelta(days=3), 'entry_type': 'dinner',
             'reason': 'Second shift dinner', 'logged_by_id': D['users']['security'].id},
            {'employee_id': D['emp']['vishal'].id, 'date': today - timedelta(days=7), 'entry_type': 'missing',
             'time_in': 9.0, 'time_out': 18.0, 'on_duty_late': True, 'reason': 'Returned from TVS Hosur trial',
             'logged_by_id': D['users']['security'].id},
        ])
        GP.search([('entry_type', '=', 'missing'), ('attendance_id', '=', False)], limit=1).action_post_attendance()
        env['gbb.incident'].create({
            'incident_datetime': datetime.combine(today - timedelta(days=16), time(9, 15)),
            'employee_id': D['ops'][7].id, 'location': 'Assembly bay 2', 'severity': 'minor',
            'name': 'Finger cut while deburring clamp pad edge without gloves.',
            'prevention': 'First aid given. Cut-resistant gloves made mandatory at deburring table; toolbox talk held.',
        })
        return '4 security entries, 1 incident'

    # ================================================================ unload
    def action_unload(self):
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise UserError(_('Only an administrator can remove demo data.'))
        Rec = self.env['gbb.demo.record'].sudo()
        recs = Rec.search([('kind', '=', 'rows')])
        state_rec = Rec.search([('kind', '=', 'state')], limit=1)
        if not recs and not state_rec:
            raise UserError(_('No GBB demo data is loaded.'))
        cr = self.env.cr
        ids_by_table = {r.table_name: json.loads(r.ids_json) for r in recs}
        model_by_table = {r.table_name: r.model for r in recs}
        log = []
        self._soften(ids_by_table, model_by_table, log)
        self.env.flush_all()
        # delete rows in dependency order: retry until no table makes progress
        pending = {t: list(ids) for t, ids in ids_by_table.items() if ids}
        cr.execute("SET CONSTRAINTS ALL IMMEDIATE")
        for _round in range(40):
            progress = False
            for table in list(pending):
                ids = pending[table]
                try:
                    with cr.savepoint(flush=False):
                        cr.execute('DELETE FROM "%s" WHERE id = ANY(%%s)' % table, (ids,))
                    del pending[table]
                    progress = True
                except Exception:
                    continue
            if not pending or not progress:
                break
        if pending:
            # last resort: null out references to the blocked rows from rows that survive
            for table, ids in list(pending.items()):
                cr.execute("""
                    SELECT cl.relname, att.attname FROM pg_constraint con
                    JOIN pg_class cl ON cl.oid = con.conrelid
                    JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
                    WHERE con.contype = 'f' AND con.confrelid = %s::regclass""", (table,))
                for ref_table, col in cr.fetchall():
                    try:
                        with cr.savepoint(flush=False):
                            cr.execute('UPDATE "%s" SET "%s" = NULL WHERE "%s" = ANY(%%s)' % (ref_table, col, col), (ids,))
                    except Exception:
                        pass
            for table, ids in list(pending.items()):
                try:
                    with cr.savepoint(flush=False):
                        cr.execute('DELETE FROM "%s" WHERE id = ANY(%%s)' % table, (ids,))
                    del pending[table]
                except Exception as e:
                    log.append('Could not remove %s rows from %s: %s' % (len(ids), table, e))
        # chatter, followers and activities attached to removed records
        for table, ids in ids_by_table.items():
            model = model_by_table.get(table)
            if not model or not ids:
                continue
            for t, col in (('mail_message', 'model'), ('mail_followers', 'res_model'), ('mail_activity', 'res_model')):
                cr.execute('DELETE FROM "%s" WHERE "%s" = %%s AND res_id = ANY(%%s)' % (t, col), (model, ids))
            cr.execute('DELETE FROM ir_attachment WHERE res_model = %s AND res_id = ANY(%s)', (model, ids))
        if state_rec:
            self._restore_state(json.loads(state_rec.ids_json), log)
        Rec.search([]).unlink()
        self.env.invalidate_all()
        self.env.registry.clear_cache()
        removed = sum(len(v) for v in ids_by_table.values())
        log.insert(0, 'Removed %s demo rows from %s tables.%s' % (
            removed, len(ids_by_table), (' %s tables could not be cleaned.' % len(pending)) if pending else ''))
        self.log = '\n'.join(log)
        return self._reopen()

    def _soften(self, ids_by_table, model_by_table, log):
        """Cancel / reset business documents so nothing (e.g. a posted entry) blocks the delete."""
        env = self.env
        for table, ids in ids_by_table.items():
            model = model_by_table.get(table)
            if model not in env or not ids:
                continue
            recs = env[model].browse(ids).exists()
            try:
                with env.cr.savepoint():
                    if model == 'account.move':
                        recs.filtered(lambda m: m.state == 'posted').with_context(force_delete=True).button_draft()
            except Exception as e:
                log.append('Note: could not reset %s (%s)' % (model, e))
        # archive demo users first so their sessions end
        if 'res_users' in ids_by_table:
            users = env['res.users'].browse(ids_by_table['res_users']).exists()
            users.write({'active': False})

    def _restore_state(self, state, log):
        env = self.env
        cr = env.cr
        Seq = env['ir.sequence'].sudo()
        for sid, nxt in state.get('sequences', {}).items():
            seq = Seq.browse(int(sid)).exists()
            if seq and seq.number_next_actual != nxt:
                seq.number_next_actual = nxt
        for rid, nxt in state.get('ranges', {}).items():
            rng = env['ir.sequence.date_range'].sudo().browse(int(rid)).exists()
            if rng and rng.number_next_actual != nxt:
                rng.number_next_actual = nxt
        comp = state.get('company') or {}
        if comp:
            env.company.write({k: v for k, v in comp.items() if k in env.company._fields})
        mto = self._ref('stock.route_warehouse0_mto')
        if mto and not state.get('mto_active'):
            mto.active = False
        team = self._ref('sales_team.team_sales_department')
        if team:
            team.invoiced_target = state.get('team_target') or 0
        log.append('Company details, numbering and settings restored. '
                   'Work orders and storage locations stay enabled in Settings.')
