# -*- coding: utf-8 -*-
from odoo import fields, models


class HrPayslipLine(models.Model):
    _name = 'hr.payslip.line'
    _description = 'Payslip Line'
    _order = 'slip_id, sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(
        required=True, index=True, default=5,
        help='Use to arrange calculation sequence')
    code = fields.Char(
        required=True,
        help="Careful, the code is used in many references, changing it could lead to unwanted changes.")
    slip_id = fields.Many2one('hr.payslip', string='Pay Slip', required=True, index=True, ondelete='cascade')
    salary_rule_id = fields.Many2one('hr.salary.rule', string='Rule', required=True, ondelete='restrict')
    version_id = fields.Many2one('hr.version', string='Contract', required=True, index=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, index=True)
    rate = fields.Float(string='Rate (%)', digits='Payroll Rate', default=100.0)
    amount = fields.Monetary()
    quantity = fields.Float(digits='Payroll', default=1.0)
    total = fields.Monetary(string='Total')

    amount_select = fields.Selection(related='salary_rule_id.amount_select', readonly=True)
    appears_on_payslip = fields.Boolean(related='salary_rule_id.appears_on_payslip', readonly=True)
    category_id = fields.Many2one(related='salary_rule_id.category_id', readonly=True, store=True)
    partner_id = fields.Many2one(related='salary_rule_id.partner_id', readonly=True, store=True)

    date_from = fields.Date(string='From', related="slip_id.date_from", store=True)
    date_to = fields.Date(string='To', related="slip_id.date_to", store=True)
    state = fields.Selection(related='slip_id.state', store=True, string='Status')
    struct_id = fields.Many2one(related='slip_id.struct_id', store=True)
    department_id = fields.Many2one(related='slip_id.department_id', store=True)
    company_id = fields.Many2one(related='slip_id.company_id', store=True)
    currency_id = fields.Many2one('res.currency', related='slip_id.currency_id')
