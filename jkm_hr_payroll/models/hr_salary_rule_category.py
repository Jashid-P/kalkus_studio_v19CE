# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrSalaryRuleCategory(models.Model):
    _name = 'hr.salary.rule.category'
    _description = 'Salary Rule Category'
    _order = 'code, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    parent_id = fields.Many2one(
        'hr.salary.rule.category', string='Parent', index=True,
        help="Amounts of this category are also added to the parent category.")
    children_ids = fields.One2many('hr.salary.rule.category', 'parent_id', string='Children')
    note = fields.Html(string='Description')
    country_id = fields.Many2one(
        'res.country', string='Country',
        default=lambda self: self.env.company.country_id)

    @api.constrains('parent_id')
    def _check_parent_id(self):
        if self._has_cycle():
            raise ValidationError(self.env._("You cannot create a recursive hierarchy of salary rule categories."))

    @api.depends('code')
    def _compute_display_name(self):
        for category in self:
            category.display_name = f"{category.name} ({category.code})" if category.code else category.name

    def _sum_salary_rule_category(self, localdict, amount):
        """Add ``amount`` to this category and all its parents in ``localdict['categories']``."""
        self.ensure_one()
        category = self
        while category:
            localdict['categories'][category.code] += amount
            category = category.parent_id
        return localdict
