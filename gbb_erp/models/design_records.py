from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .common import GBB_GROUPS


class GbbDesignChange(models.Model):
    """Design Change Record (GBB/DSG/DCR), now tied to the BOM revision it creates."""
    _name = 'gbb.design.change'
    _description = 'Design Change Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char('DCR No', default=lambda s: _('New'), copy=False, readonly=True)
    project_id = fields.Many2one('project.project', 'Project Code', tracking=True)
    partner_id = fields.Many2one(related='project_id.partner_id', string='Customer', store=True)
    date = fields.Date(default=fields.Date.context_today)
    gbb_group = fields.Selection(GBB_GROUPS, 'Production Group')
    reason = fields.Selection([
        ('customer', 'Customer request'), ('internal', 'Internal improvement'),
        ('mfg', 'Manufacturing feedback'), ('trial', 'Trial / proving result')], default='customer')
    change_details = fields.Text('Change Details', required=True)
    approved_by_id = fields.Many2one('res.users', 'Approved By', tracking=True)
    state = fields.Selection([('draft', 'Draft'), ('approved', 'Approved'), ('applied', 'BOM Revised')],
                             default='draft', tracking=True)
    bom_old_id = fields.Many2one('mrp.bom', 'BOM (old rev)', readonly=True)
    bom_new_id = fields.Many2one('mrp.bom', 'BOM (new rev)', readonly=True)
    line_ids = fields.One2many('gbb.design.change.line', 'change_id', 'BOM Impact')
    impacted_po_count = fields.Integer(compute='_compute_impact')
    impacted_mo_count = fields.Integer(compute='_compute_impact')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('gbb.design.change') or _('New')
        return super().create(vals_list)

    def _compute_impact(self):
        for rec in self:
            rec.impacted_po_count = len(rec.line_ids.sudo().mapped('po_line_ids.order_id'))
            rec.impacted_mo_count = self.env['mrp.production'].search_count(
                [('bom_id', '=', rec.bom_old_id.id), ('state', 'not in', ('done', 'cancel'))]) if rec.bom_old_id else 0

    def action_approve(self):
        self.write({'state': 'approved', 'approved_by_id': self.env.user.id})

    def action_view_pos(self):
        return {
            'type': 'ir.actions.act_window', 'name': _('Impacted Purchase Orders'), 'res_model': 'purchase.order',
            'view_mode': 'list,form', 'domain': [('id', 'in', self.line_ids.mapped('po_line_ids.order_id').ids)],
        }

    def action_view_mos(self):
        return {
            'type': 'ir.actions.act_window', 'name': _('Impacted Manufacturing Orders'),
            'res_model': 'mrp.production', 'view_mode': 'list,form',
            'domain': [('bom_id', '=', self.bom_old_id.id), ('state', 'not in', ('done', 'cancel'))],
        }


class GbbDesignChangeLine(models.Model):
    _name = 'gbb.design.change.line'
    _description = 'Design Change BOM Impact'

    change_id = fields.Many2one('gbb.design.change', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', 'Part / Item', required=True)
    change_type = fields.Selection([('added', 'Added'), ('removed', 'Removed'), ('qty', 'Qty changed'),
                                    ('spec', 'Size / grade changed')])
    detail = fields.Char('What changed')
    old_qty = fields.Float('Old Qty')
    new_qty = fields.Float('New Qty')
    delta = fields.Float('Qty Change', compute='_compute_delta', store=True)
    po_line_ids = fields.Many2many('purchase.order.line', string='Open PO Lines', compute='_compute_po',
                                   help='Purchase lines already raised for this item on this project')
    po_qty = fields.Float('Already on PO', compute='_compute_po')
    mo_qty = fields.Float('In Production', compute='_compute_po')
    action_hint = fields.Char('Purchase Action', compute='_compute_po')

    @api.depends('old_qty', 'new_qty')
    def _compute_delta(self):
        for l in self:
            l.delta = l.new_qty - l.old_qty

    def _compute_po(self):
        for l in self:
            project = l.change_id.project_id
            pols = self.env['purchase.order.line'].sudo().search([
                ('product_id', '=', l.product_id.id), ('state', 'in', ('draft', 'sent', 'to approve', 'purchase')),
                ('order_id.project_id', '=', project.id)]) if project else self.env['purchase.order.line']
            l.po_line_ids = pols
            l.po_qty = sum(pols.mapped('product_qty'))
            mos = self.env['mrp.production'].sudo().search([
                ('product_id', '=', l.product_id.id), ('state', 'not in', ('done', 'cancel'))])
            l.mo_qty = sum(mos.mapped('product_qty'))
            if l.change_type == 'removed' and l.mo_qty:
                l.action_hint = _('Stop part MO, scrap or keep as spare')
            elif l.change_type == 'removed' and l.po_qty:
                l.action_hint = _('Cancel / reduce PO')
            elif l.change_type == 'removed':
                l.action_hint = _('Remove from drawings and BOM print')
            elif l.change_type == 'spec' and l.mo_qty:
                l.action_hint = _('Re-issue drawing; check RM size of part MO')
            elif l.change_type == 'spec':
                l.action_hint = _('Re-issue drawing and RM size')
            elif l.delta > 0:
                l.action_hint = _('Raise extra PO') if l.po_qty else _('Include in next PO')
            elif l.delta < 0 and l.po_qty:
                l.action_hint = _('Reduce PO qty')
            else:
                l.action_hint = False


class GbbBomRevisionWizard(models.TransientModel):
    _name = 'gbb.bom.revision.wizard'
    _description = 'Create BOM Revision from Design Change'

    bom_id = fields.Many2one('mrp.bom', required=True)
    change_details = fields.Text('What changed in the design?', required=True)
    reason = fields.Selection([
        ('customer', 'Customer request'), ('internal', 'Internal improvement'),
        ('mfg', 'Manufacturing feedback'), ('trial', 'Trial / proving result')], default='customer')

    def action_create_revision(self):
        self.ensure_one()
        old = self.bom_id
        try:
            new_rev = '%02d' % (int(old.gbb_rev or '0') + 1)
        except ValueError:
            new_rev = (old.gbb_rev or '') + '+1'
        new = old.copy({'gbb_rev': new_rev, 'gbb_previous_bom_id': old.id, 'project_id': old.project_id.id})
        dcr = self.env['gbb.design.change'].create({
            'project_id': old.project_id.id,
            'gbb_group': old.project_id.gbb_group,
            'change_details': self.change_details,
            'reason': self.reason,
            'bom_old_id': old.id,
            'bom_new_id': new.id,
        })
        old.message_post(body=_('Superseded by Rev %(rev)s via %(dcr)s', rev=new_rev, dcr=dcr.name))
        return {
            'type': 'ir.actions.act_window', 'res_model': 'mrp.bom', 'res_id': new.id,
            'view_mode': 'form', 'target': 'current',
            'context': {'gbb_dcr_id': dcr.id},
        }


class MrpBomRevisionHook(models.Model):
    _inherit = 'mrp.bom'

    def action_gbb_release_revision(self):
        """Edit the new revision, then release: archives the old rev and fills the DCR impact table."""
        for bom in self:
            old = bom.gbb_previous_bom_id
            if not old:
                raise UserError(_('This BOM is not a revision.'))
            dcr = self.env['gbb.design.change'].search([('bom_new_id', '=', bom.id)], limit=1)
            old_map, new_map = old._gbb_line_map(), bom._gbb_line_map()
            old_spec, new_spec = old._gbb_spec_map(), bom._gbb_spec_map()
            lines = []
            for pid in set(old_map) | set(new_map):
                o, n = old_map.get(pid, 0.0), new_map.get(pid, 0.0)
                diff = [txt for txt in self._gbb_spec_diff(old_spec.get(pid), new_spec.get(pid))] if o and n else []
                if o == n and not diff:
                    continue
                ctype = 'added' if not o else ('removed' if not n else ('qty' if o != n else 'spec'))
                lines.append((0, 0, {'product_id': pid, 'old_qty': o, 'new_qty': n, 'change_type': ctype,
                                     'detail': '; '.join(diff) or False}))
            if dcr:
                dcr.line_ids.unlink()
                dcr.write({'line_ids': lines, 'state': 'applied'})
            old.active = False
            bom.gbb_rev_released = True
            bom.message_post(body=_('Rev %s released. %s line(s) changed.', bom.gbb_rev, len(lines)))
        return True


class MrpBomSpec(models.Model):
    _inherit = 'mrp.bom'

    def _gbb_spec_map(self):
        res = {}
        for l in self.bom_line_ids:
            res[l.product_id.id] = {'Grade': l.gbb_grade_id.name or '', 'Shape': l.gbb_shape or '',
                                    'Dia': l.gbb_fin_d, 'L': l.gbb_fin_l, 'W': l.gbb_fin_w, 'H': l.gbb_fin_h}
        return res

    @api.model
    def _gbb_spec_diff(self, a, b):
        out = []
        for key in ('Grade', 'Shape', 'Dia', 'L', 'W', 'H'):
            va, vb = (a or {}).get(key), (b or {}).get(key)
            if va != vb:
                fmt = (lambda v: '%g' % v) if isinstance(va or vb, float) else (lambda v: v or '-')
                out.append('%s %s to %s' % (key, fmt(va or 0) if isinstance(va or vb, float) else fmt(va),
                                             fmt(vb or 0) if isinstance(va or vb, float) else fmt(vb)))
        return out


class GbbLessonLearnt(models.Model):
    _name = 'gbb.lesson.learnt'
    _description = 'Lesson Learnt (GBB/DSG/LL)'
    _order = 'date desc, id desc'

    project_id = fields.Many2one('project.project', 'Project Code')
    partner_id = fields.Many2one(related='project_id.partner_id', string='Customer', store=True)
    name = fields.Text('Lesson / Learning', required=True)
    user_id = fields.Many2one('res.users', 'By', default=lambda s: s.env.user)
    date = fields.Date(default=fields.Date.context_today)
    gbb_group = fields.Selection(GBB_GROUPS, 'Production Group')
    category = fields.Selection([('design', 'Design'), ('mfg', 'Manufacturing'), ('assembly', 'Assembly'),
                                 ('trial', 'Trial / Proving'), ('customer', 'Customer')], default='design')
