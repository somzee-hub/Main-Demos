import math

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .common import GBB_GROUPS


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    gbb_is_fixture = fields.Boolean('Fixture (made to order)',
                                    help='Booking an order for this product opens a design project with a project code')
    gbb_make = fields.Char('Make', help='Kosmek / GBB / Mitutoyo / Vega ...')
    gbb_is_std = fields.Boolean('Standard / Bought-out Part',
                                help='No machining route, goes to the standard parts list and Store')
    gbb_grade_id = fields.Many2one('gbb.material.grade', 'Material Grade')


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    gbb_rev = fields.Char('Rev No', default='01', tracking=True, copy=False)
    gbb_previous_bom_id = fields.Many2one('mrp.bom', 'Previous Revision', readonly=True, copy=False)
    gbb_rev_released = fields.Boolean('Revision Released', copy=False, readonly=True)
    gbb_fixture_qty = fields.Integer(related='project_id.gbb_fixture_qty', string='Fixture Qty')
    gbb_group = fields.Selection(related='project_id.gbb_group')
    gbb_designer_id = fields.Many2one(related='project_id.gbb_designer_id')
    gbb_sent_to_purchase = fields.Datetime('Sent to Purchase', readonly=True, copy=False)
    gbb_rm_pending = fields.Integer('RM Pending Lines', compute='_compute_gbb_rm_pending')
    gbb_change_ids = fields.One2many('gbb.design.change', 'bom_new_id', 'Design Changes')

    @api.model_create_multi
    def create(self, vals_list):
        boms = super().create(vals_list)
        for bom in boms.filtered('project_id'):
            # BOM uploaded: close the "Upload BOM" reminder raised at release
            acts = bom.project_id.activity_ids.filtered(lambda a: (a.summary or '').startswith('Upload BOM'))
            acts.action_feedback(feedback=_('BOM Rev %s uploaded', bom.gbb_rev))
        return boms

    def _compute_gbb_rm_pending(self):
        for bom in self:
            bom.gbb_rm_pending = len(bom.bom_line_ids.filtered(
                lambda l: not l.product_id.gbb_is_std and l.gbb_grade_id and not l.gbb_rm_available))

    def action_gbb_send_to_purchase(self):
        """BOM Inbox of the old Purchase module: hand the BOM to purchase."""
        for bom in self:
            if bom.project_id and bom.project_id.gbb_design_stage not in ('released', 'completed') \
                    and not self.env.context.get('gbb_force'):
                raise UserError(_('Design of %s is not yet Released to Mfg.', bom.project_id.gbb_project_code))
            bom.gbb_sent_to_purchase = fields.Datetime.now()
            purchasers = self.env.ref('purchase.group_purchase_user').user_ids.filtered(lambda u: not u.share)
            buyer = purchasers.filtered(lambda u: not u.has_group('base.group_system'))[:1] or purchasers[:1] or self.env.user
            bom.message_post(body=_('BOM Rev %s sent to Purchase.', bom.gbb_rev))
            if bom.project_id:
                bom.project_id.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=buyer.id,
                    summary=_('BOM Rev %s received in BOM Inbox: raise POs', bom.gbb_rev))

    def action_gbb_new_revision(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('New BOM Revision'),
            'res_model': 'gbb.bom.revision.wizard', 'view_mode': 'form', 'target': 'new',
            'context': {'default_bom_id': self.id},
        }

    def _gbb_line_map(self):
        res = {}
        for line in self.bom_line_ids:
            res[line.product_id.id] = res.get(line.product_id.id, 0.0) + line.product_qty
        return res


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    gbb_spare = fields.Integer('Spare')
    gbb_grade_id = fields.Many2one('gbb.material.grade', 'Material / Grade')
    gbb_is_std = fields.Boolean(related='product_id.gbb_is_std', string='Std')
    gbb_critical = fields.Boolean('Critical Spare')
    gbb_shape = fields.Selection([('FLAT', 'FLAT'), ('ROUND', 'ROUND')], 'Shape')
    gbb_fin_d = fields.Float('Fin Dia')
    gbb_fin_l = fields.Float('Fin L')
    gbb_fin_w = fields.Float('Fin W')
    gbb_fin_h = fields.Float('Fin H')
    gbb_rm_d = fields.Float('RM Dia', compute='_compute_gbb_rm', store=True)
    gbb_rm_l = fields.Float('RM L', compute='_compute_gbb_rm', store=True)
    gbb_rm_w = fields.Float('RM W', compute='_compute_gbb_rm', store=True)
    gbb_rm_h = fields.Float('RM H', compute='_compute_gbb_rm', store=True)
    gbb_rm_size = fields.Char('RM Size', compute='_compute_gbb_rm', store=True)
    gbb_rm_weight = fields.Float('RM Wt/pc (kg)', compute='_compute_gbb_rm', store=True, digits=(10, 2))
    gbb_rm_available = fields.Boolean('RM Avail', compute='_compute_gbb_rm_available')

    @api.depends('gbb_shape', 'gbb_fin_d', 'gbb_fin_l', 'gbb_fin_w', 'gbb_fin_h', 'gbb_grade_id.density')
    def _compute_gbb_rm(self):
        """Same rule as the old computeRMSize / nearestStdPiece:
        FLAT: L, W = tightest standard piece >= finish + 3 mm, H = finish + 5 mm
        ROUND: tightest standard bar with Dia >= finish + 3 mm and L >= finish + 5 mm
        Tightest = least D x D x L (round) or L x W (flat). No fit: raw allowance."""
        sizes = self.env['gbb.rm.size'].search([])
        for line in self:
            d = l = w = h = 0.0
            if line.gbb_shape == 'ROUND':
                need_d = math.ceil(line.gbb_fin_d + 3) if line.gbb_fin_d else 0
                need_l = math.ceil(line.gbb_fin_l + 5) if line.gbb_fin_l else 0
                fits = sizes.filtered(lambda s: s.shape == 'ROUND' and (not need_d or s.diameter >= need_d)
                                      and (not need_l or s.length >= need_l))
                best = fits.sorted(lambda s: s.diameter * s.diameter * (s.length or 1))[:1]
                d = best.diameter or (line.gbb_fin_d + 3 if line.gbb_fin_d else 0)
                l = best.length or (line.gbb_fin_l + 5 if line.gbb_fin_l else 0)
            elif line.gbb_shape == 'FLAT':
                need_l = math.ceil(line.gbb_fin_l + 3) if line.gbb_fin_l else 0
                need_w = math.ceil(line.gbb_fin_w + 3) if line.gbb_fin_w else 0
                fits = sizes.filtered(lambda s: s.shape == 'FLAT' and (not need_l or s.length >= need_l)
                                      and (not need_w or s.width >= need_w))
                best = fits.sorted(lambda s: (s.length or 1) * (s.width or 1))[:1]
                l = best.length or (line.gbb_fin_l + 3 if line.gbb_fin_l else 0)
                w = best.width or (line.gbb_fin_w + 3 if line.gbb_fin_w else 0)
                h = line.gbb_fin_h + 5 if line.gbb_fin_h else 0
            line.gbb_rm_d, line.gbb_rm_l, line.gbb_rm_w, line.gbb_rm_h = d, l, w, h
            density = line.gbb_grade_id.density or 7.85
            if d:
                line.gbb_rm_size = 'Dia %g x %g' % (d, l)
                vol = math.pi / 4 * d * d * l
            elif l:
                line.gbb_rm_size = '%g x %g x %g' % (l, w, h)
                vol = l * w * h
            else:
                line.gbb_rm_size = False
                vol = 0.0
            line.gbb_rm_weight = vol * density / 1e6

    def _compute_gbb_rm_available(self):
        for line in self:
            prod = line.gbb_grade_id.product_id
            need = line.gbb_rm_weight * (line.product_qty + line.gbb_spare)
            line.gbb_rm_available = bool(prod) and prod.qty_available >= need > 0


class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    gbb_machine_type = fields.Selection([
        ('VMC', 'VMC'), ('HMC', 'HMC'), ('VTL', 'VTL'), ('CNC', 'CNC'), ('GRIND', 'Grinding'),
        ('ASM', 'Assembly'), ('DESIGN', 'Design'), ('OTHER', 'Other')], 'Machine Type')
    gbb_group = fields.Selection(GBB_GROUPS, 'Production Group', default='COMMON')
    gbb_shift = fields.Selection([('1', 'Single'), ('1.5', 'Partial 2nd'), ('2', 'Double'),
                                  ('3', 'Round the clock')], 'Shift', default='1')


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    gbb_project_code = fields.Char(related='project_id.gbb_project_code', string='Project Code', store=True)


class StockScrap(models.Model):
    """Job Rejection register (GBB/QA/02) on top of Odoo scrap."""
    _inherit = 'stock.scrap'

    gbb_project_id = fields.Many2one('project.project', 'Project Code')
    gbb_workcenter_id = fields.Many2one('mrp.workcenter', 'Machine')
    gbb_operator_id = fields.Many2one('hr.employee', 'Operator')
    gbb_shift = fields.Char('Shift', default='A')
    gbb_reworkable = fields.Boolean('Reworkable')
    gbb_root_cause = fields.Text('Reason / Root Cause')
    gbb_corrective_action = fields.Text('Corrective Action')
    gbb_action_status = fields.Selection([('open', 'Open'), ('closed', 'Closed')], 'Action Status', default='open')
    gbb_responsible_id = fields.Many2one('hr.employee', 'Responsible Person')
    gbb_amount = fields.Float('Amount of Rejection', compute='_compute_gbb_amount', store=True)

    @api.depends('scrap_qty', 'product_id.standard_price')
    def _compute_gbb_amount(self):
        for s in self:
            s.gbb_amount = s.scrap_qty * s.product_id.standard_price


# Part categories and default process route of the old Production Planning screen
PART_CATEGORIES = [
    ('Base Plate', ['base plate', 'baseplate', 'base structure', 'casting base', 'plate']),
    ('Resting Pad', ['resting pad', 'rest pad', 'resting', 'support pad']),
    ('Clamp Pad', ['clamp pad', 'clamping pad']),
    ('Clamp', ['clamp', 'clamping']),
    ('Locating Pin', ['locating pin', 'locator', 'dowel']),
    ('Spring Loaded Housing', ['spring loaded', 'spring housing', 'spring loaded housing']),
    ('Taper Pin', ['taper pin', 'tapper pin', 'taper']),
    ('Rough Guide Base', ['rough guide base', 'guide base', 'rough base']),
    ('Rough Guide Top', ['rough guide top', 'guide top', 'rough top']),
    ('Bush', ['bush', 'bushing']),
    ('Guiding Pin', ['guiding pin', 'guide pin', 'guiding']),
    ('Casting Structure', ['casting structure', 'casting', 'structure', 'weldment']),
]
# (operation, hours per piece, machine type); lead-time steps (RM, Hardening, Plating) are purchase / job work
DEFAULT_ROUTE = [
    ('3D Program', 8, 'DESIGN'),
    ('CNC Soft', 6, 'CNC'),
    ('VMC Soft', 6, 'VMC'),
    ('CNC Hard', 4, 'CNC'),
    ('VMC Hard', 4, 'VMC'),
    ('Cyl Grinding', 3, 'GRIND'),
    ('Surface Grinding', 3, 'GRIND'),
    ('H7 / Bore', 2, 'GRIND'),
]
ROUND_SKIP = {'VMC Soft', 'VMC Hard', 'Surface Grinding'}
FLAT_SKIP = {'CNC Soft', 'CNC Hard', 'Cyl Grinding'}


def gbb_part_category(name):
    low = (name or '').lower()
    for cat, keys in PART_CATEGORIES:
        if any(k in low for k in keys):
            return cat
    return False


class MrpBomGenerate(models.Model):
    _inherit = 'mrp.bom'

    def action_gbb_generate_part_boms(self):
        """Designer fills the flat GBB BOM; Odoo builds each part's RM consumption and machining route."""
        Bom = self.env['mrp.bom']
        Wc = self.env['mrp.workcenter']
        created = Bom
        for bom in self:
            for line in bom.bom_line_ids.filtered(lambda l: not l.product_id.gbb_is_std and l.gbb_grade_id):
                tmpl = line.product_id.product_tmpl_id
                if tmpl.bom_ids:
                    continue
                routes = self.env.ref('mrp.route_warehouse0_manufacture', raise_if_not_found=False)
                mto = self.env.ref('stock.route_warehouse0_mto', raise_if_not_found=False)
                if mto and mto.active:
                    routes |= mto
                if routes:
                    tmpl.route_ids = [(4, r.id) for r in routes]
                if not tmpl.is_storable:
                    tmpl.is_storable = True
                ops = []
                for seq, (op, hrs, mtype) in enumerate(DEFAULT_ROUTE, 1):
                    if line.gbb_shape == 'ROUND' and op in ROUND_SKIP:
                        continue
                    if line.gbb_shape == 'FLAT' and op in FLAT_SKIP:
                        continue
                    wc = Wc.search([('gbb_machine_type', '=', mtype), ('gbb_group', 'in', (bom.gbb_group or 'COMMON', 'COMMON'))], limit=1) \
                        or Wc.search([('gbb_machine_type', '=', mtype)], limit=1)
                    if not wc:
                        continue
                    ops.append((0, 0, {'name': op, 'workcenter_id': wc.id, 'sequence': seq,
                                       'time_mode': 'manual', 'time_cycle_manual': hrs * 60.0}))
                vals = {'product_tmpl_id': tmpl.id, 'product_qty': 1.0, 'type': 'normal',
                        'project_id': bom.project_id.id, 'operation_ids': ops,
                        'code': gbb_part_category(tmpl.name) or False}
                rm = line.gbb_grade_id.product_id
                if rm and line.gbb_rm_weight:
                    vals['bom_line_ids'] = [(0, 0, {'product_id': rm.id, 'product_qty': round(line.gbb_rm_weight, 2)})]
                created |= Bom.create(vals)
        return created
