from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .common import GBB_GROUPS, fy_long, fy_short

DEFAULT_SCOPE = """<ol>
<li>Precision clamps</li>
<li>Support elements</li>
<li>Structure &amp; mechanical assemblies</li>
<li>HYD pressure supply</li>
<li>Electrical integration</li>
<li>Inspection</li>
<li>Packing &amp; fixture documentation (1 set)</li>
</ol>"""

DEFAULT_TERMS = """<table>
<tr><td><b>Delivery</b></td><td>5 Weeks After Receipt of Techno-commercial PO</td></tr>
<tr><td><b>Freight</b></td><td>In Customer Scope</td></tr>
<tr><td><b>Payment</b></td><td>50% Advance, 40% + Taxes Against PI, 10% After Trial</td></tr>
<tr><td><b>Warranty</b></td><td>12 Months From Date of Dispatch</td></tr>
<tr><td><b>Taxes</b></td><td>GST 18% As Applicable</td></tr>
<tr><td><b>Order to be Placed on</b></td><td>G.B.B Industries, Gut No.128, Karodi, Aurangabad-431136</td></tr>
</table>"""

# Default cost breakup of the old quotation screen (per 1 fixture)
DEFAULT_BREAKUP = [
    # name, kind, qty, rate, amount
    ('Design Cost', 'cost', 0, 0, 30000),
    ('Material Cost', 'material', 0, 0, 34500),
    ('Machining Cost', 'machining', 0, 0, 0),
    ('HYD CYL (GBB Make)', 'std', 0, 9500, 0),
    ('HYD Work Support (Kosmek)', 'std', 0, 25500, 0),
    ('Sequence Valve', 'std', 1, 10500, 0),
    ('Dial Gauge', 'std', 1, 3000, 0),
    ('Tombstone Casting', 'std', 1, 0, 0),
    ('Flow Control Valve', 'std', 0, 5500, 0),
    ('Stress Relieving & Hardening', 'cost', 0, 0, 8000),
    ('Internal Piping', 'cost', 0, 0, 55000),
    ('Fasteners & Consumables', 'cost', 0, 0, 8000),
    ('Assembly & Inspection', 'cost', 0, 0, 25000),
    ('Fixture Proving Charges', 'cost', 0, 0, 25000),
    ('Packaging & Transport', 'cost', 0, 0, 12500),
]


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    gbb_group = fields.Selection(GBB_GROUPS, 'Production Group', default='G1', tracking=True)
    gbb_inquiry_no = fields.Char(related='opportunity_id.gbb_inquiry_no', string='Inquiry No', store=True)
    gbb_rev = fields.Char('Rev No', default='00', copy=False)
    gbb_parent_quote_id = fields.Many2one('sale.order', 'Revision Of', copy=False, readonly=True)
    gbb_machine = fields.Char('Machine', help='MAZAK, HMC ...')
    gbb_delivery_weeks = fields.Integer('Delivery (weeks)', default=5)
    gbb_machining_factor = fields.Float('Machining = Material x', default=6.0)
    gbb_scope = fields.Html('Scope of Supply', default=DEFAULT_SCOPE)
    gbb_terms = fields.Html('Commercial Terms', default=DEFAULT_TERMS)

    # Director approval of quotations
    gbb_approval_state = fields.Selection([
        ('draft', 'Not Submitted'),
        ('to_approve', 'Waiting Director Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')], 'Approval', default='draft', copy=False, tracking=True)
    gbb_approved_by = fields.Many2one('res.users', 'Approved By', copy=False, readonly=True)
    gbb_approved_on = fields.Datetime('Approved On', copy=False, readonly=True)
    gbb_negotiation = fields.Boolean('Under Negotiation', tracking=True)

    # Order Booking (GBB/MKT/OB-04)
    gbb_allotted_date = fields.Date('Allotted Date')
    gbb_market = fields.Selection([('DOMESTIC', 'Domestic'), ('OVERSEAS', 'Overseas')], 'Domestic / Overseas',
                                  default='DOMESTIC')
    gbb_on_hold = fields.Boolean('On Hold', tracking=True)
    gbb_order_status = fields.Selection([
        ('quote', 'Quotation'),
        ('design', 'Under Design'),
        ('mfg', 'Under Manufacturing'),
        ('dispatched', 'Dispatched'),
        ('hold', 'On Hold')], 'Order Status', compute='_compute_gbb_order_status')
    gbb_days_left = fields.Integer('Days to Dispatch', compute='_compute_gbb_order_status',
                                   help='Negative = overdue')

    # Order Review (GBB/MKT/OB-5)
    or_tol_ok = fields.Boolean('Customer tolerances achievable')
    or_stroke_ok = fields.Boolean('Fixture within machine stroke')
    or_machining_ok = fields.Boolean('Component machining feasible')
    or_envelope_ok = fields.Boolean('Fixture within work envelope')
    or_payment_terms = fields.Char('Payment Terms (review)', default='As per Quote')
    or_delivery = fields.Char('Fixture Delivery', default='5 weeks')
    or_man_material = fields.Selection([('yes', 'Yes'), ('no', 'No'), ('partial', 'Partial')],
                                       'Man & Material Available')
    or_cutting_trial = fields.Char('Cutting Trial Scope', default='NA')
    or_bo_lead_time = fields.Char('Bought-Out Lead Time')
    or_outsourcing = fields.Char('Outsourcing Req.', default='NA')
    or_as_expected = fields.Selection([('YES', 'YES'), ('NO', 'NO'), ('PARTIALLY', 'PARTIALLY')],
                                      'As Per Expectation')
    or_point_ids = fields.One2many('gbb.order.review.point', 'order_id', 'Review Points')
    or_points_done = fields.Char('Points Done', compute='_compute_or_points_done')

    gbb_project_ids = fields.One2many('project.project', 'gbb_sale_order_id', 'Design Projects')

    @api.depends('or_point_ids.done')
    def _compute_or_points_done(self):
        for so in self:
            so.or_points_done = '%s/%s' % (len(so.or_point_ids.filtered('done')), len(so.or_point_ids))

    @api.depends('state', 'gbb_on_hold', 'delivery_status', 'commitment_date')
    def _compute_gbb_order_status(self):
        today = fields.Date.context_today(self)
        for so in self:
            if so.state != 'sale':
                so.gbb_order_status = 'quote'
            elif so.gbb_on_hold:
                so.gbb_order_status = 'hold'
            elif so.delivery_status == 'full':
                so.gbb_order_status = 'dispatched'
            elif (so.sudo().mrp_production_ids | self.env['mrp.production'].sudo().search(
                    [('project_id', 'in', so.sudo().gbb_project_ids.ids)])).filtered(
                    lambda m: m.state in ('confirmed', 'progress', 'to_close', 'done')):
                so.gbb_order_status = 'mfg'
            else:
                so.gbb_order_status = 'design'
            date = so.commitment_date and so.commitment_date.date()
            so.gbb_days_left = (date - today).days if date and so.gbb_order_status != 'dispatched' else 0

    # ------------------------------------------------------------------ numbering
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('opportunity_id') and vals.get('name', _('New')) == _('New'):
                lead = self.env['crm.lead'].browse(vals['opportunity_id'])
                if lead.gbb_inquiry_no:
                    base = 'GBB/SQ/%s/%s' % (fy_short(lead.gbb_inquiry_date), lead.gbb_inquiry_no)
                    name, n = base, 1
                    while self.search_count([('name', '=', name)]):
                        n += 1
                        name = '%s-%s' % (base, n)
                    vals['name'] = name
                    vals.setdefault('gbb_group', lead.gbb_group)
        return super().create(vals_list)

    # ------------------------------------------------------------------ revisions
    def action_gbb_new_revision(self):
        self.ensure_one()
        root = self.gbb_parent_quote_id or self
        revs = self.search([('gbb_parent_quote_id', '=', root.id)])
        rev_no = len(revs) + 1
        new = self.copy({
            'name': '%s-R%02d' % (root.name, rev_no),
            'gbb_rev': '%02d' % rev_no,
            'gbb_parent_quote_id': root.id,
            'opportunity_id': self.opportunity_id.id,
        })
        for old_line, new_line in zip(self.order_line, new.order_line):
            for b in old_line.gbb_breakup_ids:
                b.copy({'line_id': new_line.id})
        self.message_post(body=_('Superseded by revision %s', new.name))
        return {
            'type': 'ir.actions.act_window', 'res_model': 'sale.order',
            'res_id': new.id, 'view_mode': 'form', 'target': 'current',
        }

    # ------------------------------------------------------------------ approval
    def action_gbb_submit(self):
        self.write({'gbb_approval_state': 'to_approve'})
        directors = self.env.ref('gbb_erp.group_gbb_director').user_ids
        for so in self:
            for user in directors:
                so.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                     summary=_('Approve quotation %s', so.name))

    def _gbb_check_director(self):
        if not self.env.user.has_group('gbb_erp.group_gbb_director'):
            raise UserError(_('Only a Director can approve or reject quotations.'))

    def action_gbb_approve(self):
        self._gbb_check_director()
        self.write({'gbb_approval_state': 'approved', 'gbb_approved_by': self.env.user.id,
                    'gbb_approved_on': fields.Datetime.now()})
        self.activity_feedback(['mail.mail_activity_data_todo'], feedback=_('Approved'))
        if len(self) == 1 and not self.env.context.get('gbb_no_send'):
            return self.action_quotation_send()
        return True

    def action_gbb_reject(self):
        self._gbb_check_director()
        self.write({'gbb_approval_state': 'rejected'})
        self.activity_feedback(['mail.mail_activity_data_todo'], feedback=_('Rejected'))

    def action_quotation_send(self):
        for so in self:
            if so.state in ('draft', 'sent') and so.gbb_approval_state != 'approved' \
                    and not self.env.context.get('gbb_skip_approval'):
                raise UserError(_('Quotation %s needs Director approval before it is sent.', so.name))
        return super().action_quotation_send()

    def action_quotation_sent(self):
        for so in self:
            if so.gbb_approval_state != 'approved' and not self.env.context.get('gbb_skip_approval'):
                raise UserError(_('Quotation %s needs Director approval before it is sent.', so.name))
        return super().action_quotation_sent()

    def action_confirm(self):
        for so in self:
            if so.gbb_approval_state != 'approved' and not self.env.context.get('gbb_skip_approval'):
                raise UserError(_('Quotation %s needs Director approval before the order is booked.', so.name))
        res = super().action_confirm()
        self._gbb_create_design_projects()
        return res

    # ------------------------------------------------------------------ project codes
    def _gbb_create_design_projects(self):
        """One design project per fixture line, project code <FY>-<n> from 3101."""
        Project = self.env['project.project'].sudo()  # sales books the order, project code is system-issued
        for so in self:
            for line in so.order_line.filtered(lambda l: l.product_id.gbb_is_fixture and not l.gbb_project_id):
                project = Project.create(Project._gbb_project_vals_from_line(line))
                line.gbb_project_id = project

    def action_gbb_apply_breakups(self):
        for line in self.order_line.filtered('gbb_breakup_ids'):
            line._gbb_apply_breakup()

    def action_gbb_view_projects(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('project.open_view_project_all')
        action['domain'] = [('gbb_sale_order_id', '=', self.id)]
        return action


class GbbOrderReviewPoint(models.Model):
    _name = 'gbb.order.review.point'
    _description = 'Order Review Point'
    _order = 'sequence, id'

    order_id = fields.Many2one('sale.order', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char('Review Point', required=True)
    done = fields.Boolean('Done')


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    gbb_breakup_ids = fields.One2many('gbb.cost.breakup.line', 'line_id', 'Cost Breakup', copy=False)
    gbb_risk = fields.Float('Risk Factor')
    gbb_profit_pct = fields.Float('Profit (%)', default=20.0)
    gbb_subtotal1 = fields.Float('Sub Total-1', compute='_compute_gbb_breakup', store=True)
    gbb_profit = fields.Float('Profit', compute='_compute_gbb_breakup', store=True)
    gbb_breakup_total = fields.Float('Breakup Total (per fixture)', compute='_compute_gbb_breakup', store=True)
    gbb_project_id = fields.Many2one('project.project', 'Project Code', copy=False)

    @api.depends('gbb_breakup_ids.amount', 'gbb_risk', 'gbb_profit_pct')
    def _compute_gbb_breakup(self):
        for line in self:
            sub = sum(line.gbb_breakup_ids.mapped('amount'))
            line.gbb_subtotal1 = sub
            line.gbb_profit = sub * line.gbb_profit_pct / 100.0
            # risk counted once (the old screen added it twice, see coverage map)
            line.gbb_breakup_total = sub + line.gbb_profit + line.gbb_risk

    def write(self, vals):
        res = super().write(vals)
        if {'price_unit', 'product_uom_qty', 'discount', 'product_id'} & set(vals) \
                and not self.env.context.get('gbb_skip_approval'):
            orders = self.order_id.filtered(lambda o: o.state in ('draft', 'sent') and o.gbb_approval_state == 'approved')
            if orders:
                orders.write({'gbb_approval_state': 'draft'})
                for o in orders:
                    o.message_post(body=_('Prices changed after approval: quotation needs Director approval again.'))
        return res

    def _gbb_apply_breakup(self):
        for line in self:
            if line.gbb_breakup_ids:
                line.price_unit = line.gbb_breakup_total

    def action_gbb_load_default_breakup(self):
        Std = self.env['product.product']
        for line in self:
            line.gbb_breakup_ids.unlink()
            vals = []
            for seq, (name, kind, qty, rate, amount) in enumerate(DEFAULT_BREAKUP):
                prod = Std.search([('name', '=', name)], limit=1) if kind == 'std' else Std
                vals.append({'line_id': line.id, 'sequence': seq, 'name': name, 'kind': kind,
                             'product_id': prod.id or False, 'qty': qty, 'rate': rate,
                             'amount_manual': amount})
            self.env['gbb.cost.breakup.line'].create(vals)
            line._gbb_apply_breakup()

    def action_gbb_open_breakup(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cost Breakup (Confidential)'),
            'res_model': 'sale.order.line',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('gbb_erp.view_sale_line_breakup_form').id,
            'target': 'new',
        }


class GbbCostBreakupLine(models.Model):
    _name = 'gbb.cost.breakup.line'
    _description = 'Quotation Cost Breakup Row'
    _order = 'sequence, id'

    line_id = fields.Many2one('sale.order.line', required=True, ondelete='cascade')
    order_id = fields.Many2one(related='line_id.order_id', store=True)
    sequence = fields.Integer(default=10)
    name = fields.Char('Cost Head', required=True)
    kind = fields.Selection([
        ('cost', 'Cost'), ('material', 'Material'), ('machining', 'Machining (x material)'),
        ('std', 'Standard / Bought-out Item')], default='cost', required=True)
    product_id = fields.Many2one('product.product', 'Standard Item')
    qty = fields.Float('Qty')
    rate = fields.Float('Rate')
    amount_manual = fields.Float('Amount (direct)')
    amount = fields.Float('Amount', compute='_compute_amount', store=True)

    @api.depends('kind', 'qty', 'rate', 'amount_manual',
                 'line_id.order_id.gbb_machining_factor', 'line_id.gbb_breakup_ids.amount_manual',
                 'line_id.gbb_breakup_ids.kind')
    def _compute_amount(self):
        for row in self:
            if row.kind == 'machining':
                material = sum(row.line_id.gbb_breakup_ids.filtered(lambda r: r.kind == 'material').mapped('amount_manual'))
                row.amount = material * (row.line_id.order_id.gbb_machining_factor or 0.0)
            elif row.qty or row.rate:
                row.amount = row.qty * row.rate
            else:
                row.amount = row.amount_manual

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.name
            self.rate = self.product_id.standard_price
            self.kind = 'std'
            if not self.qty:
                self.qty = 1

    @api.model_create_multi
    def create(self, vals_list):
        rows = super().create(vals_list)
        rows.line_id._gbb_apply_breakup()
        return rows

    def write(self, vals):
        res = super().write(vals)
        self.line_id._gbb_apply_breakup()
        return res

    def unlink(self):
        lines = self.line_id
        res = super().unlink()
        lines.exists()._gbb_apply_breakup()
        return res
