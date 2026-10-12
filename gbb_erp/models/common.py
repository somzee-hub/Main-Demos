from odoo import api, fields, models

GBB_GROUPS = [
    ('G1', 'Group 1'),
    ('G2', 'Group 2'),
    ('COMMON', 'Common'),
]


def fy_start_year(date):
    """GBB financial year runs April to March."""
    if not date:
        date = fields.Date.today()
    return date.year if date.month >= 4 else date.year - 1


def fy_long(date):
    """2026-2027 style label (project codes, inquiry display)."""
    y = fy_start_year(date)
    return '%s-%s' % (y, y + 1)


def fy_short(date):
    """2026-27 style label (quotation numbers, registers)."""
    y = fy_start_year(date)
    return '%s-%s' % (y, str(y + 1)[-2:])


class GbbFixtureType(models.Model):
    _name = 'gbb.fixture.type'
    _description = 'Fixture Type'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('UNIQUE(name)', 'Fixture type already exists.')


class GbbMaterialGrade(models.Model):
    """Material Rate Card + Density Table of the old Purchase module."""
    _name = 'gbb.material.grade'
    _description = 'Material Grade (Rate Card)'
    _order = 'name'

    name = fields.Char('Grade', required=True)
    density = fields.Float('Density (g/cc)', digits=(6, 3), default=7.85)
    rate_kg = fields.Float('Rate (Rs/kg)')
    product_id = fields.Many2one(
        'product.product', 'Raw Material Product',
        help='Stock item purchased in kg for this grade')
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('UNIQUE(name)', 'Grade already exists.')


class GbbRmSize(models.Model):
    """Standard raw material stock sizes used to pick the RM size of a BOM line."""
    _name = 'gbb.rm.size'
    _description = 'Standard RM Size'
    _order = 'shape, diameter, length, width'

    shape = fields.Selection([('ROUND', 'Round'), ('FLAT', 'Flat')], required=True, default='FLAT')
    grade_id = fields.Many2one('gbb.material.grade', 'Grade (optional)')
    diameter = fields.Float('Dia (mm)')
    length = fields.Float('Length (mm)')
    width = fields.Float('Width (mm)')

    @api.depends('shape', 'diameter', 'length', 'width')
    def _compute_display_name(self):
        for rec in self:
            if rec.shape == 'ROUND':
                rec.display_name = 'Round Dia %g x %g' % (rec.diameter, rec.length)
            else:
                rec.display_name = 'Flat %g x %g' % (rec.length, rec.width)
