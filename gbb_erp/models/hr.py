from odoo import api, fields, models

from .common import GBB_GROUPS


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    gbb_group = fields.Selection(GBB_GROUPS, 'Production Group', default='COMMON')
    gbb_staff_type = fields.Selection([('staff', 'Staff'), ('worker', 'Worker'), ('unskilled', 'Unskilled')],
                                      'Staff Type', default='worker')
    gbb_pan = fields.Char('PAN Number', groups='hr.group_hr_user')
    gbb_prev_epf = fields.Char('Previous EPF No.', groups='hr.group_hr_user')
    gbb_prev_esic = fields.Char('Previous ESIC No.', groups='hr.group_hr_user')
    # Pay setup of the old Salary screen (confidential: HR Manager only)
    gbb_salary_type = fields.Selection([
        ('hours', 'Hours-based (OT + bonus)'),
        ('fixed', 'Fixed, month-days (bonus, no OT)'),
        ('ctc', 'CTC, month-days (no bonus, no OT, PF 24% on basic)')], 'Salary Type',
        groups='hr.group_hr_manager')
    gbb_pay_category = fields.Selection([('worker', 'Worker (8 hr shift)'), ('staff', 'Staff (9 hr shift)'),
                                         ('outdoor', 'Out-Door (12 hr)')], 'Pay Category',
                                        groups='hr.group_hr_manager')
    gbb_pf = fields.Boolean('PF enrolled (12%)', groups='hr.group_hr_manager')
    gbb_esic = fields.Boolean('ESIC enrolled (0.75%)', groups='hr.group_hr_manager')
    gbb_advance_ids = fields.One2many('gbb.employee.advance', 'employee_id', groups='hr.group_hr_manager')
    gbb_advance_balance = fields.Float('Advance Outstanding', compute='_compute_gbb_advance_balance',
                                       groups='hr.group_hr_manager')

    @api.depends('gbb_advance_ids.amount', 'gbb_advance_ids.move_type')
    def _compute_gbb_advance_balance(self):
        for e in self:
            adv = e.gbb_advance_ids
            e.gbb_advance_balance = sum(adv.filtered(lambda a: a.move_type == 'advance').mapped('amount')) - \
                sum(adv.filtered(lambda a: a.move_type == 'deduction').mapped('amount'))


class GbbEmployeeAdvance(models.Model):
    _name = 'gbb.employee.advance'
    _description = 'Employee Advance / Recovery'
    _order = 'date desc, id desc'

    employee_id = fields.Many2one('hr.employee', required=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    move_type = fields.Selection([('advance', 'Advance given'), ('deduction', 'Deduction (salary recovery)')],
                                 required=True, default='advance')
    amount = fields.Float(required=True)
    salary_month = fields.Char('Post to Salary Month', help='YYYY-MM')
    note = fields.Char()
