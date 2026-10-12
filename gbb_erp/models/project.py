from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .common import GBB_GROUPS, fy_long

DESIGN_STAGES = [
    ('inputs', 'Design Inputs & Verification'),
    ('discussion', 'Discussion with customer'),
    ('modeling', 'Modeling'),
    ('cust_approval', 'Customer Approval'),
    ('model_update', 'Modeling updation (as customer)'),
    ('cust_approval2', 'Customer Approval if reqd.'),
    ('final_model', 'Final modeling'),
    ('drafting', 'Drafting'),
    ('checklist', 'Check List'),
    ('asm_bom', 'Assembly Drg./BOM'),
    ('subasm_bom', 'Sub Assembly Drg./BOM'),
    ('fasteners', 'Fasteners List'),
    ('part_drg', 'Part Details Drg.'),
    ('base_plate', 'Base Plate Drg.'),
    ('coordinates', 'Co-ordinates'),
    ('name_plate', 'Name Plate Drg.'),
    ('output', 'Design output (document list)'),
    ('dd_review', 'Design & Development Review'),
    ('verification', 'Design Verification'),
    ('released', 'Released to Mfg'),
    ('completed', 'Completed'),
    ('hold', 'On Hold'),
]

# 24 planning activities of the design planner: 19 design stages + 5 downstream
EXTRA_ACTIVITIES = ['R.M. Purchasing', 'Machining', 'Assembly & Trial', 'Dispatch',
                    'Design & Development validation']


class ProjectProject(models.Model):
    _inherit = 'project.project'

    gbb_project_code = fields.Char('Project Code', copy=False, index=True)
    gbb_lead_id = fields.Many2one('crm.lead', 'Inquiry', copy=False)
    gbb_inquiry_no = fields.Char(related='gbb_lead_id.gbb_inquiry_no', string='Inquiry No', store=True)
    gbb_sale_order_id = fields.Many2one('sale.order', 'Booked Order', copy=False)
    gbb_sale_line_id = fields.Many2one('sale.order.line', 'Order Line', copy=False)
    gbb_group = fields.Selection(GBB_GROUPS, 'Production Group', default='G1')
    gbb_fixture_qty = fields.Integer('Fixture Qty', default=1)
    gbb_fixture_type_id = fields.Many2one('gbb.fixture.type', 'Fixture Type')
    gbb_is_design = fields.Boolean('Design Project')
    gbb_designer_id = fields.Many2one('res.users', 'Designer', tracking=True)
    gbb_design_stage = fields.Selection(DESIGN_STAGES, 'Design Stage', default='inputs', tracking=True)
    gbb_released_date = fields.Date('Released to Mfg On', readonly=True, copy=False)
    gbb_bom_ids = fields.One2many('mrp.bom', 'project_id', 'BOMs')
    gbb_bom_status = fields.Selection([
        ('na', '-'), ('bom_pending', 'BOM pending'), ('po_pending', 'BOM done, PO pending'),
        ('done', 'BOM done, PO done')], compute='_compute_gbb_bom_status', string='BOM / PO')
    gbb_checklist_ids = fields.One2many('gbb.checklist', 'project_id', 'Checklists')
    gbb_change_ids = fields.One2many('gbb.design.change', 'project_id', 'Design Changes')
    gbb_lesson_ids = fields.One2many('gbb.lesson.learnt', 'project_id', 'Lessons Learnt')
    gbb_checklist_count = fields.Integer(compute='_compute_gbb_counts')
    gbb_change_count = fields.Integer(compute='_compute_gbb_counts')

    _gbb_code_uniq = models.Constraint('UNIQUE(gbb_project_code)', 'Project code must be unique.')

    def _compute_gbb_counts(self):
        for p in self:
            p.gbb_checklist_count = len(p.gbb_checklist_ids)
            p.gbb_change_count = len(p.gbb_change_ids)

    @api.depends('gbb_design_stage', 'gbb_bom_ids')
    def _compute_gbb_bom_status(self):
        for p in self:
            if p.gbb_design_stage not in ('released', 'completed'):
                p.gbb_bom_status = 'na'
            elif not p.gbb_bom_ids:
                p.gbb_bom_status = 'bom_pending'
            elif not p.sudo().purchase_orders_count:
                p.gbb_bom_status = 'po_pending'
            else:
                p.gbb_bom_status = 'done'

    @api.model
    def _gbb_next_code(self, date=None):
        date = date or fields.Date.context_today(self)
        n = self.env['ir.sequence'].next_by_code('gbb.project.code', sequence_date=date)
        return '%s-%s' % (fy_long(date), n)

    @api.model
    def _gbb_project_vals_from_line(self, line):
        so = line.order_id
        code = self._gbb_next_code(so.date_order.date() if so.date_order else None)
        lead = so.opportunity_id
        return {
            'name': '%s · %s' % (code, line.name.split('\n')[0][:80]),
            'gbb_project_code': code,
            'partner_id': so.partner_id.id,
            'gbb_lead_id': lead.id or False,
            'gbb_sale_order_id': so.id,
            'gbb_sale_line_id': line.id,
            'gbb_group': so.gbb_group,
            'gbb_fixture_qty': int(line.product_uom_qty),
            'gbb_fixture_type_id': lead.gbb_fixture_type_id.id or False,
            'gbb_is_design': True,
            'allow_timesheets': True,
            'date_start': fields.Date.context_today(self),
            'date': so.commitment_date.date() if so.commitment_date else False,
        }

    @api.model_create_multi
    def create(self, vals_list):
        projects = super().create(vals_list)
        for p in projects.filtered('gbb_is_design'):
            p._gbb_init_design_tasks()
        return projects

    def _gbb_init_design_tasks(self):
        stages = self.env['project.task.type'].search([('gbb_design_task_stage', '=', True)])
        self.type_ids = [(6, 0, stages.ids)]
        names = [label for key, label in DESIGN_STAGES if key not in ('released', 'completed', 'hold')]
        names += EXTRA_ACTIVITIES
        vals = []
        start = self.date_start or fields.Date.context_today(self)
        for seq, name in enumerate(names, 1):
            vals.append({
                'name': '%02d. %s' % (seq, name), 'project_id': self.id, 'sequence': seq,
                'allocated_hours': 6.0 if seq <= 19 else 8.0,
                'date_deadline': fields.Datetime.to_datetime(start) + timedelta(days=int(seq * 1.5), hours=12),
                'user_ids': [(6, 0, self.gbb_designer_id.ids)] if seq <= 19 and self.gbb_designer_id else False,
                'stage_id': stages[:1].id,
            })
        self.env['project.task'].create(vals)

    def write(self, vals):
        if vals.get('gbb_design_stage') == 'released':
            vals.setdefault('gbb_released_date', fields.Date.context_today(self))
        res = super().write(vals)
        if vals.get('gbb_design_stage') == 'released':
            for p in self.filtered(lambda p: not p.gbb_bom_ids):
                p.activity_schedule('mail.mail_activity_data_todo',
                                    user_id=(p.gbb_designer_id or self.env.user).id,
                                    summary=_('Upload BOM for %s', p.gbb_project_code or p.name))
        if 'gbb_designer_id' in vals:
            for p in self:
                p.task_ids.filtered(lambda t: t.sequence <= 19).write({'user_ids': [(6, 0, p.gbb_designer_id.ids)]})
        return res

    def action_gbb_create_mo(self):
        """Planning: open the manufacturing order for this fixture from the released BOM."""
        self.ensure_one()
        bom = self.gbb_bom_ids.filtered('active')[:1]
        if not bom:
            raise UserError(_('Upload the BOM first (project %s).', self.gbb_project_code))
        product = bom.product_id or bom.product_tmpl_id.product_variant_id
        mo = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': self.gbb_fixture_qty or 1, 'bom_id': bom.id,
            'project_id': self.id, 'origin': self.gbb_sale_order_id.name or self.gbb_project_code,
            'date_deadline': self.date,
        })
        return {'type': 'ir.actions.act_window', 'res_model': 'mrp.production', 'res_id': mo.id,
                'view_mode': 'form', 'target': 'current'}

    def action_gbb_checklists(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Checklists'), 'res_model': 'gbb.checklist',
            'view_mode': 'list,form', 'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_gbb_changes(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Design Changes'), 'res_model': 'gbb.design.change',
            'view_mode': 'list,form', 'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }


class ProjectTaskType(models.Model):
    _inherit = 'project.task.type'

    gbb_design_task_stage = fields.Boolean('GBB Design Activity Stage')


class ProjectTask(models.Model):
    _inherit = 'project.task'

    # Customer Complaints (GBB/MKT/CF-70) live in the "Customer Complaints" project
    gbb_is_complaint = fields.Boolean(related='project_id.gbb_is_complaint_project')
    gbb_fixture_desc = fields.Char('Fixture Description', help='Part name & OP number')
    gbb_complaint_date = fields.Date('Complaint Date')
    gbb_customer_email = fields.Char('Customer Email')
    gbb_rca = fields.Text('Root Cause Analysis')
    gbb_action_taken = fields.Text('Action Taken')
    gbb_closure_date = fields.Date('Closure Date')
    gbb_group = fields.Selection(GBB_GROUPS, 'Production Group')


class ProjectProjectComplaint(models.Model):
    _inherit = 'project.project'

    gbb_is_complaint_project = fields.Boolean('Customer Complaints Project')
