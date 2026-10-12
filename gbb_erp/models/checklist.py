from odoo import api, fields, models, _

from .common import GBB_GROUPS

KINDS = [
    ('fixture_design', 'Fixture Design Check List'),
    ('cradle_design', 'Cradle Design Check List'),
    ('internal_review', 'Internal Design Review'),
    ('packaging', 'Packaging / Dispatch Check List'),
    ('final_inspection', 'Final Inspection'),
    ('jh_daily', 'JH Daily Check'),
    ('clearance', 'Employee Clearance'),
    ('vendor_assessment', 'Vendor Assessment'),
]

ANSWER_TYPES = [
    ('yesno', 'Yes / No / NA'),
    ('text', 'Written answer'),
    ('value', 'Value'),
    ('measure', 'Measurement (nominal and tolerance)'),
    ('okrev', 'OK / Not OK / Revise'),
    ('tick', 'Tick with qty'),
    ('score', 'Score 1-10'),
]


class GbbChecklistTemplate(models.Model):
    _name = 'gbb.checklist.template'
    _description = 'Checklist Template (ISO format)'
    _order = 'kind, sequence, name'

    name = fields.Char(required=True)
    code = fields.Char('Doc No', help='e.g. GBB/DSG/FDCL-02 Rev 00')
    kind = fields.Selection(KINDS, required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many('gbb.checklist.template.line', 'template_id', 'Points', copy=True)
    point_count = fields.Integer(compute='_compute_point_count')

    def _compute_point_count(self):
        for t in self:
            t.point_count = len(t.line_ids.filtered(lambda l: not l.is_section))


class GbbChecklistTemplateLine(models.Model):
    _name = 'gbb.checklist.template.line'
    _description = 'Checklist Template Point'
    _order = 'sequence, id'

    template_id = fields.Many2one('gbb.checklist.template', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    is_section = fields.Boolean('Section Header')
    name = fields.Char('Point', required=True)
    answer_type = fields.Selection(ANSWER_TYPES, default='yesno', required=True)
    nominal = fields.Float('Nominal', digits=(10, 3))
    tol_plus = fields.Float('Tol +', digits=(10, 3))
    tol_minus = fields.Float('Tol -', digits=(10, 3))
    instrument = fields.Char('Instrument')
    spec = fields.Char('Specification')
    default_qty = fields.Float('Qty')


class GbbChecklist(models.Model):
    _name = 'gbb.checklist'
    _description = 'Checklist'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char('No', default=lambda s: _('New'), copy=False, readonly=True)
    template_id = fields.Many2one('gbb.checklist.template', 'Format', required=True)
    kind = fields.Selection(related='template_id.kind', store=True)
    doc_code = fields.Char(related='template_id.code')
    date = fields.Date(default=fields.Date.context_today)
    project_id = fields.Many2one('project.project', 'Project Code')
    partner_id = fields.Many2one('res.partner', 'Customer / Vendor', compute='_compute_partner', store=True,
                                 readonly=False)
    picking_id = fields.Many2one('stock.picking', 'Delivery / Challan')
    production_id = fields.Many2one('mrp.production', 'Manufacturing Order')
    equipment_id = fields.Many2one('maintenance.equipment', 'Machine / Equipment')
    employee_id = fields.Many2one('hr.employee', 'Employee')
    subject = fields.Char('Fixture / Cradle / Part Name')
    prepared_by_id = fields.Many2one('res.users', 'Prepared By', default=lambda s: s.env.user)
    checked_by_ids = fields.Many2many('res.users', string='Checked By')
    approved_by_id = fields.Many2one('res.users', 'Approved By')
    gbb_group = fields.Selection(GBB_GROUPS, 'Production Group')
    design_start = fields.Date('Design Start')
    design_end = fields.Date('Design Complete')
    design_hours = fields.Float('Design Hours')
    result = fields.Selection([('pass', 'Pass'), ('fail', 'Fail'), ('conditional', 'Conditional')], tracking=True)
    state = fields.Selection([('draft', 'In Progress'), ('done', 'Completed')], default='draft', tracking=True)
    line_ids = fields.One2many('gbb.checklist.line', 'checklist_id', 'Points', copy=True)
    count_yes = fields.Integer('Yes', compute='_compute_counts', store=True)
    count_no = fields.Integer('No Count', compute='_compute_counts', store=True)
    count_na = fields.Integer('NA', compute='_compute_counts', store=True)
    count_total = fields.Integer('Total Points', compute='_compute_counts', store=True)
    count_answered = fields.Integer('Answered', compute='_compute_counts', store=True)
    progress = fields.Float('Progress %', compute='_compute_counts', store=True)
    remarks = fields.Text()

    @api.depends('project_id')
    def _compute_partner(self):
        for c in self:
            if c.project_id and not c.partner_id:
                c.partner_id = c.project_id.partner_id

    @api.depends('line_ids.answer_yn', 'line_ids.is_answered', 'line_ids.is_section')
    def _compute_counts(self):
        for c in self:
            pts = c.line_ids.filtered(lambda l: not l.is_section)
            c.count_yes = len(pts.filtered(lambda l: l.answer_yn == 'yes'))
            c.count_no = len(pts.filtered(lambda l: l.answer_yn == 'no'))
            c.count_na = len(pts.filtered(lambda l: l.answer_yn == 'na'))
            c.count_total = len(pts)
            c.count_answered = len(pts.filtered('is_answered'))
            c.progress = 100.0 * c.count_answered / c.count_total if c.count_total else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('gbb.checklist') or _('New')
        recs = super().create(vals_list)
        for rec in recs.filtered(lambda r: not r.line_ids):
            rec._load_template_lines()
        return recs

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id and not self.line_ids:
            self.line_ids = [(0, 0, vals) for vals in self._template_line_vals()]

    def _template_line_vals(self):
        return [{
            'sequence': tl.sequence, 'is_section': tl.is_section, 'name': tl.name,
            'answer_type': tl.answer_type, 'nominal': tl.nominal, 'tol_plus': tl.tol_plus,
            'tol_minus': tl.tol_minus, 'instrument': tl.instrument, 'spec': tl.spec, 'qty': tl.default_qty,
        } for tl in self.template_id.line_ids]

    def _load_template_lines(self):
        for rec in self:
            rec.line_ids = [(0, 0, vals) for vals in rec._template_line_vals()]

    def action_all_yes(self):
        self.line_ids.filtered(lambda l: l.answer_type == 'yesno' and not l.is_section).write({'answer_yn': 'yes'})

    def action_all_na(self):
        self.line_ids.filtered(lambda l: l.answer_type == 'yesno' and not l.is_section).write({'answer_yn': 'na'})

    def action_done(self):
        for c in self:
            vals = {'state': 'done'}
            if c.kind == 'final_inspection' and not c.result:
                meas = c.line_ids.filtered(lambda l: l.answer_type == 'measure' and l.actual)
                vals['result'] = 'fail' if meas.filtered(lambda l: l.measure_result == 'fail') else 'pass'
            c.write(vals)

    def action_reset(self):
        self.write({'state': 'draft'})


class GbbChecklistLine(models.Model):
    _name = 'gbb.checklist.line'
    _description = 'Checklist Point'
    _order = 'sequence, id'

    checklist_id = fields.Many2one('gbb.checklist', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    is_section = fields.Boolean()
    name = fields.Char('Point', required=True)
    answer_type = fields.Selection(ANSWER_TYPES, default='yesno', required=True)
    answer_yn = fields.Selection([('yes', 'Yes'), ('no', 'No'), ('na', 'NA')], 'Yes/No/NA')
    answer_ok = fields.Selection([('ok', 'OK'), ('notok', 'Not OK'), ('revise', 'Revise')], 'Status')
    answer_text = fields.Char('Answer / Value')
    checked = fields.Boolean('Done')
    qty = fields.Float('Qty')
    score = fields.Integer('Score /10')
    nominal = fields.Float(digits=(10, 3))
    tol_plus = fields.Float('Tol +', digits=(10, 3))
    tol_minus = fields.Float('Tol -', digits=(10, 3))
    instrument = fields.Char()
    spec = fields.Char('Specification')
    actual = fields.Float('Actual', digits=(10, 3))
    measure_result = fields.Selection([('pass', 'OK'), ('fail', 'Not OK')], compute='_compute_measure_result',
                                      store=True)
    remark = fields.Char()
    is_answered = fields.Boolean(compute='_compute_is_answered', store=True)

    @api.depends('answer_type', 'nominal', 'tol_plus', 'tol_minus', 'actual')
    def _compute_measure_result(self):
        for l in self:
            if l.answer_type != 'measure' or not l.actual:
                l.measure_result = False
                continue
            lo = l.nominal - (l.tol_minus or l.tol_plus)
            hi = l.nominal + l.tol_plus
            if not l.nominal:
                # geometric tolerances (runout, parallelism): actual must be within tol
                l.measure_result = 'pass' if abs(l.actual) <= (l.tol_plus or 0.0) else 'fail'
            else:
                l.measure_result = 'pass' if lo - 1e-9 <= l.actual <= hi + 1e-9 else 'fail'

    @api.depends('answer_type', 'answer_yn', 'answer_ok', 'answer_text', 'checked', 'actual', 'score', 'is_section')
    def _compute_is_answered(self):
        for l in self:
            if l.is_section:
                l.is_answered = False
            elif l.answer_type == 'yesno':
                l.is_answered = bool(l.answer_yn)
            elif l.answer_type == 'okrev':
                l.is_answered = bool(l.answer_ok)
            elif l.answer_type in ('text', 'value'):
                l.is_answered = bool(l.answer_text)
            elif l.answer_type == 'measure':
                l.is_answered = bool(l.actual) or bool(l.answer_text)
            elif l.answer_type == 'score':
                l.is_answered = bool(l.score)
            else:
                l.is_answered = l.checked
