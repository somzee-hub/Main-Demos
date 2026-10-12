from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .common import GBB_GROUPS


class ResPartner(models.Model):
    _inherit = 'res.partner'

    gbb_machine_types = fields.Char('Machine Type(s)', help='Comma separated, e.g. VMC, HMC, VTL')
    gbb_complaint_count = fields.Integer(compute='_compute_gbb_counts')
    gbb_project_count = fields.Integer(compute='_compute_gbb_counts')

    def _compute_gbb_counts(self):
        Task = self.env['project.task']
        Project = self.env['project.project']
        for p in self:
            commercial = p.commercial_partner_id
            p.gbb_complaint_count = Task.search_count([('partner_id', 'child_of', commercial.id),
                                                       ('project_id.gbb_is_complaint_project', '=', True)])
            p.gbb_project_count = Project.search_count([('partner_id', 'child_of', commercial.id),
                                                        ('gbb_is_design', '=', True)])

    def action_gbb_complaints(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Complaints'), 'res_model': 'project.task',
            'view_mode': 'list,form', 'domain': [('partner_id', 'child_of', self.commercial_partner_id.id),
                                                 ('project_id.gbb_is_complaint_project', '=', True)],
        }

    def action_gbb_projects(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Design Projects'), 'res_model': 'project.project',
            'view_mode': 'list,form', 'domain': [('partner_id', 'child_of', self.commercial_partner_id.id),
                                                 ('gbb_is_design', '=', True)],
        }


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    gbb_po_type = fields.Selection([('RM', 'Raw Material'), ('JOBWORK', 'Job Work / Labour'),
                                    ('BOUGHTOUT', 'Bought-out')], 'PO Type', default='BOUGHTOUT', tracking=True)
    gbb_process = fields.Selection([('hardening', 'Hardening'), ('plating', 'Plating'), ('blackening', 'Blackening'),
                                    ('edm', 'EDM'), ('other', 'Other')], 'Job Work Process')
    gbb_jw_status = fields.Selection([('sent', 'Sent'), ('process', 'In Process'), ('received', 'Received'),
                                      ('hold', 'On Hold')], 'Job Work Status', default='sent', tracking=True)
    gbb_jw_overdue = fields.Boolean('Overdue', compute='_compute_gbb_jw_overdue')

    def _compute_gbb_jw_overdue(self):
        now = fields.Datetime.now()
        for po in self:
            po.gbb_jw_overdue = po.gbb_po_type == 'JOBWORK' and po.gbb_jw_status != 'received' \
                and po.date_planned and po.date_planned < now


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    gbb_vehicle_no = fields.Char('Vehicle No')
    gbb_transporter_id = fields.Many2one('res.partner', 'Transporter')
    gbb_lr_no = fields.Char('LR No')
    gbb_eway_bill = fields.Char('E-way Bill No')
    gbb_customer_po = fields.Char('Customer PO Ref')
    gbb_returnable = fields.Boolean('Returnable Challan')
    gbb_expected_return = fields.Date('Expected Return')
    gbb_requested_by_id = fields.Many2one('hr.employee', 'Requested By')
    gbb_department_id = fields.Many2one('hr.department', 'Department')
    gbb_checklist_ids = fields.One2many('gbb.checklist', 'picking_id', 'Packaging Check List')


class MaintenanceEquipment(models.Model):
    _inherit = 'maintenance.equipment'

    gbb_workcenter_id = fields.Many2one('mrp.workcenter', 'Work Center (Machine)')
    gbb_is_instrument = fields.Boolean('Measuring Instrument')
    gbb_spec = fields.Char('Specification', help='e.g. 0-25 mm')
    gbb_least_count = fields.Char('Least Count')
    gbb_error_acceptable = fields.Float('Error Acceptable', digits=(6, 4))
    gbb_actual_error = fields.Float('Actual Error', digits=(6, 4))
    gbb_acceptance = fields.Selection([('ok', 'Ok'), ('new', 'New Instrument'), ('notok', 'Not Ok')],
                                      'Acceptance Status', compute='_compute_gbb_acceptance', store=True, readonly=False)
    gbb_cal_frequency = fields.Selection([('12', 'Yearly'), ('6', 'Half-Yearly'), ('3', 'Quarterly'),
                                          ('1', 'Monthly')], 'Calibration Frequency', default='12')
    gbb_cal_date = fields.Date('Calibration Date')
    gbb_cal_due = fields.Date('Calibration Due', compute='_compute_gbb_cal_due', store=True, readonly=False)
    gbb_cal_status = fields.Selection([('ok', 'OK'), ('due', 'Due'), ('out', 'Out of Service')],
                                      'Calibration Status', compute='_compute_gbb_cal_status')
    gbb_jh_ids = fields.One2many('gbb.checklist', 'equipment_id', 'JH Daily Checks')

    @api.depends('gbb_actual_error', 'gbb_error_acceptable')
    def _compute_gbb_acceptance(self):
        for e in self:
            if not e.gbb_is_instrument:
                e.gbb_acceptance = False
            elif not e.gbb_actual_error:
                e.gbb_acceptance = e.gbb_acceptance or 'new'
            else:
                e.gbb_acceptance = 'ok' if e.gbb_actual_error <= e.gbb_error_acceptable else 'notok'

    @api.depends('gbb_cal_date', 'gbb_cal_frequency')
    def _compute_gbb_cal_due(self):
        from dateutil.relativedelta import relativedelta
        for e in self:
            if e.gbb_cal_date and e.gbb_cal_frequency:
                e.gbb_cal_due = e.gbb_cal_date + relativedelta(months=int(e.gbb_cal_frequency))

    def _compute_gbb_cal_status(self):
        today = fields.Date.context_today(self)
        for e in self:
            if not e.gbb_is_instrument:
                e.gbb_cal_status = False
            elif not e.active or e.scrap_date:
                e.gbb_cal_status = 'out'
            elif e.gbb_cal_due and e.gbb_cal_due <= today:
                e.gbb_cal_status = 'due'
            else:
                e.gbb_cal_status = 'ok'


class GbbToolBreakage(models.Model):
    _name = 'gbb.tool.breakage'
    _description = 'Tool Breakage (GBB/PROD/TB)'
    _order = 'date desc, id desc'

    date = fields.Date(default=fields.Date.context_today, required=True)
    name = fields.Char('Tool Description', required=True)
    workcenter_id = fields.Many2one('mrp.workcenter', 'Machine')
    operator_id = fields.Many2one('hr.employee', 'Operator')
    programmer_id = fields.Many2one('hr.employee', 'Programmer')
    responsible_id = fields.Many2one('hr.employee', 'Responsible')
    tool_qty = fields.Integer('Tool Qty', default=1)
    amount = fields.Float('Tool Amount')
    shift = fields.Char(default='A')
    reason = fields.Text('Reason for Breakage')
    action = fields.Text('Action')
    learning = fields.Text('Learning')


class GbbIncident(models.Model):
    _name = 'gbb.incident'
    _description = 'Accident / Incident Report (GBB/HR/08)'
    _inherit = ['mail.thread']
    _order = 'incident_datetime desc'

    incident_datetime = fields.Datetime('Incident Date & Time', required=True, default=fields.Datetime.now)
    reporting_date = fields.Date(default=fields.Date.context_today)
    employee_id = fields.Many2one('hr.employee', 'Affected Employee')
    department_id = fields.Many2one('hr.department', compute='_compute_department', store=True, readonly=False)
    location = fields.Char()
    severity = fields.Selection([('minor', 'Minor'), ('serious', 'Serious'), ('very', 'Very Serious')],
                                default='minor', tracking=True)
    name = fields.Text('What Happened', required=True)
    prevention = fields.Text('Prevention / Action Taken')

    @api.depends('employee_id')
    def _compute_department(self):
        for r in self:
            if r.employee_id:
                r.department_id = r.employee_id.department_id


class GbbGatePass(models.Model):
    """Security In / Out register: missing punches, breaks and gate passes."""
    _name = 'gbb.gate.pass'
    _description = 'Security In / Out Entry'
    _order = 'date desc, id desc'

    employee_id = fields.Many2one('hr.employee', required=True)
    gbb_group = fields.Selection(related='employee_id.gbb_group', store=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    entry_type = fields.Selection([
        ('missing', 'Missing punch - In/Out day entry'),
        ('dinner', 'Dinner break (left before 10 PM) - 30 min deduct'),
        ('short', 'Short break (management permission) - actual time deduct'),
        ('gatepass', 'Out with permission (gate pass) - time outside deducted')],
        required=True, default='missing')
    time_in = fields.Float('In Time', help='24h, e.g. 9.0 = 09:00')
    time_out = fields.Float('Out Time')
    on_duty_late = fields.Boolean('On-duty / Outstation late return')
    reason = fields.Char('Reason / Note')
    logged_by_id = fields.Many2one('res.users', 'Logged By', default=lambda s: s.env.user)
    deduct_minutes = fields.Integer('Deduct (min)', compute='_compute_deduct', store=True)
    attendance_id = fields.Many2one('hr.attendance', readonly=True)

    @api.depends('entry_type', 'time_in', 'time_out')
    def _compute_deduct(self):
        for r in self:
            if r.entry_type == 'dinner':
                r.deduct_minutes = 30
            elif r.entry_type in ('short', 'gatepass') and r.time_in and r.time_out:
                r.deduct_minutes = int(round(abs(r.time_in - r.time_out) * 60))
            else:
                r.deduct_minutes = 0

    def action_post_attendance(self):
        """Missing punch: create the attendance the machine missed."""
        from datetime import datetime, time, timedelta
        for r in self.filtered(lambda x: x.entry_type == 'missing' and not x.attendance_id):
            if not (r.time_in and r.time_out):
                raise UserError(_('Enter both In and Out time to post attendance.'))
            tz_offset = timedelta(hours=5, minutes=30)  # IST
            start = datetime.combine(r.date, time()) + timedelta(hours=r.time_in) - tz_offset
            end = datetime.combine(r.date, time()) + timedelta(hours=r.time_out) - tz_offset
            r.attendance_id = self.env['hr.attendance'].create(
                {'employee_id': r.employee_id.id, 'check_in': start, 'check_out': end})
