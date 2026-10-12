from odoo import api, fields, models

from .common import GBB_GROUPS, fy_long, fy_short


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # ---- Inquiry Booking (GBB/MKT/EB.01) ----
    gbb_inquiry_no = fields.Char('Inquiry No', copy=False, readonly=True, index=True,
                                 help='E-n, restarts every financial year (April to March)')
    gbb_fy = fields.Char('FY', copy=False, readonly=True)
    gbb_inquiry_ref = fields.Char('Inquiry Ref', compute='_compute_gbb_inquiry_ref', store=True,
                                  help='Shown as 2026-2027/E-231 like the old register')
    gbb_inquiry_date = fields.Date('Inquiry Date', default=fields.Date.context_today)
    gbb_fixture_type_id = fields.Many2one('gbb.fixture.type', 'Fixture Type')
    gbb_fixture_qty = fields.Integer('Fixture Qty', default=1)
    gbb_component = fields.Char('Component Name')
    gbb_component_material = fields.Char('Component Material')
    gbb_machine_model = fields.Char('Machine Model', help='e.g. MAZAK VC510')
    gbb_group = fields.Selection(GBB_GROUPS, 'Production Group', default='G1', tracking=True)

    # ---- Inquiry Review (GBB/MKT/ER-02) ----
    ir_tolerances = fields.Selection([('yes', 'Yes'), ('no', 'No'), ('partial', 'Partial')], 'Tolerances OK')
    ir_stroke = fields.Selection([('yes', 'Yes'), ('no', 'No')], 'Machine Stroke OK')
    ir_component_feasible = fields.Selection([('yes', 'Yes'), ('no', 'No')], 'Component Feasible')
    ir_feasible = fields.Selection([('YES', 'YES'), ('NO', 'NO'), ('CONDITIONAL', 'CONDITIONAL')],
                                   'Feasible Overall', tracking=True)
    ir_fixture_type = fields.Selection([
        ('vmc_stationary', 'VMC Stationary'), ('vmc_rotary', 'VMC Rotary'),
        ('hmc', 'HMC'), ('turning', 'Turning'), ('other', 'Other')], 'Review Fixture Type')
    ir_part_material = fields.Char('Part Material', help='Cast Iron / Steel / AL')
    ir_input_condition = fields.Char('Part Input Condition', help='As Cast / CNC / Semi finish')
    ir_setups = fields.Integer('No. of Setups', default=1)
    ir_hyd_elements = fields.Char('Hydraulic Elements', help='GBB / Kosmek / NA')
    ir_reviewed_by = fields.Many2one('res.users', 'Reviewed By')
    ir_review_date = fields.Date('Review Date')
    ir_done = fields.Boolean('Review Done', compute='_compute_ir_done', store=True)

    gbb_project_ids = fields.One2many('project.project', 'gbb_lead_id', 'Design Projects')
    gbb_project_count = fields.Integer(compute='_compute_gbb_project_count')

    @api.depends('gbb_inquiry_no', 'gbb_fy')
    def _compute_gbb_inquiry_ref(self):
        for lead in self:
            lead.gbb_inquiry_ref = '%s/%s' % (lead.gbb_fy, lead.gbb_inquiry_no) if lead.gbb_inquiry_no else False

    @api.depends('ir_feasible')
    def _compute_ir_done(self):
        for lead in self:
            lead.ir_done = bool(lead.ir_feasible)

    def _compute_gbb_project_count(self):
        for lead in self:
            lead.gbb_project_count = len(lead.gbb_project_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('gbb_inquiry_no'):
                date = fields.Date.to_date(vals.get('gbb_inquiry_date')) or fields.Date.context_today(self)
                seq = self.env['ir.sequence'].next_by_code('gbb.inquiry', sequence_date=date)
                if seq:
                    vals['gbb_inquiry_no'] = seq
                    vals['gbb_fy'] = fy_long(date)
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if 'gbb_group' in vals:
            # Group belongs to the inquiry and cascades to quotes, orders and projects
            for lead in self:
                lead.order_ids.write({'gbb_group': lead.gbb_group})
                lead.gbb_project_ids.write({'gbb_group': lead.gbb_group})
        return res

    @api.depends('gbb_inquiry_ref', 'name')
    def _compute_display_name(self):
        super()._compute_display_name()
        for lead in self:
            if lead.gbb_inquiry_no:
                lead.display_name = '%s · %s' % (lead.gbb_inquiry_no, lead.display_name)

    def action_gbb_projects(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('project.open_view_project_all')
        action['domain'] = [('gbb_lead_id', '=', self.id)]
        action['context'] = {'default_gbb_lead_id': self.id, 'default_partner_id': self.partner_id.id}
        return action

    def gbb_fy_short(self):
        self.ensure_one()
        return fy_short(self.gbb_inquiry_date)
