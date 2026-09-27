# -*- coding: utf-8 -*-
import ast

from odoo import api, fields, models
from odoo.exceptions import UserError


class HrRuleParameterValue(models.Model):
    _name = 'hr.rule.parameter.value'
    _description = 'Salary Rule Parameter Value'
    _order = 'date_from desc, id desc'

    rule_parameter_id = fields.Many2one(
        'hr.rule.parameter', required=True, index=True, ondelete='cascade',
        default=lambda self: self.env.context.get('active_id'))
    rule_parameter_name = fields.Char(related="rule_parameter_id.name", readonly=True)
    code = fields.Char(related="rule_parameter_id.code", index=True, store=True, readonly=True)
    date_from = fields.Date(string="From", index=True, required=True)
    parameter_value = fields.Text(
        help="Python literal: a number, a string, a list, a dict... "
             "E.g. 0.1, [(0, 10000, 0.0), (10000, 50000, 0.2)], {'rate': 0.15}")
    country_id = fields.Many2one(related="rule_parameter_id.country_id")

    _unique_code_date = models.Constraint(
        'unique (rule_parameter_id, date_from)',
        'Two rule parameters with the same code cannot start the same day',
    )

    @api.constrains('parameter_value')
    def _check_parameter_value(self):
        for value in self:
            try:
                ast.literal_eval(value.parameter_value or 'None')
            except (ValueError, SyntaxError) as e:
                raise UserError(self.env._(
                    "Wrong rule parameter value for %(name)s starting on %(date)s.\n%(error)s",
                    name=value.rule_parameter_name, date=value.date_from, error=e)) from e


class HrRuleParameter(models.Model):
    _name = 'hr.rule.parameter'
    _description = 'Salary Rule Parameter'
    _order = 'name, id'

    name = fields.Char(required=True)
    code = fields.Char(required=True, help="This code is used in salary rules to refer to this parameter.")
    description = fields.Html()
    country_id = fields.Many2one('res.country', string='Country', default=lambda self: self.env.company.country_id)
    parameter_version_ids = fields.One2many('hr.rule.parameter.value', 'rule_parameter_id', string='Versions')
    current_value = fields.Text(compute='_compute_current_value', string='Current Value')
    valid_since = fields.Date(compute='_compute_current_value')

    _unique_code = models.Constraint('unique (code)', 'Two rule parameters cannot have the same code.')

    @api.depends('parameter_version_ids.date_from', 'parameter_version_ids.parameter_value')
    def _compute_current_value(self):
        today = fields.Date.today()
        for parameter in self:
            value = parameter.parameter_version_ids.filtered(lambda v: v.date_from <= today)[:1]
            parameter.current_value = value.parameter_value
            parameter.valid_since = value.date_from

    @api.model
    def _get_parameter_from_code(self, code, date=None, raise_if_not_found=True):
        date = date or fields.Date.today()
        value = self.env['hr.rule.parameter.value'].sudo().search(
            [('code', '=', code), ('date_from', '<=', date)], order='date_from desc', limit=1)
        if not value:
            if raise_if_not_found:
                raise UserError(self.env._("No rule parameter with code '%(code)s' was found for %(date)s",
                                           code=code, date=date))
            return None
        return ast.literal_eval(value.parameter_value or 'None')
