# -*- coding: utf-8 -*-
from odoo import fields, models


class HrSalaryRule(models.Model):
    _name = 'hr.salary.rule'
    _inherit = ['hr.salary.rule', 'analytic.mixin']

    account_debit = fields.Many2one(
        'account.account', 'Debit Account', company_dependent=True, ondelete='restrict',
        help="Account debited with the positive amounts of this rule (credited with the negative ones).")
    account_credit = fields.Many2one(
        'account.account', 'Credit Account', company_dependent=True, ondelete='restrict',
        help="Account credited with the positive amounts of this rule (debited with the negative ones).")
    not_computed_in_net = fields.Boolean(
        string="Excluded from Net", default=False,
        help="If checked, the amount of this rule is removed from the Net Salary journal item. "
             "Its own debit/credit accounts are used to book it independently.")
    debit_tag_ids = fields.Many2many(
        'account.account.tag', 'jkm_hr_salary_rule_debit_tag_rel', string="Debit Tax Grids",
        help="Tax grids set on the debit journal item of this rule.")
    credit_tag_ids = fields.Many2many(
        'account.account.tag', 'jkm_hr_salary_rule_credit_tag_rel', string="Credit Tax Grids",
        help="Tax grids set on the credit journal item of this rule.")
    split_move_lines = fields.Boolean(
        string="Split on names",
        help="Create one journal item per payslip line name (e.g. one per deduction or attachment).")
    employee_move_line = fields.Boolean(
        string="Set employee on account line",
        help="Set the employee as partner on the journal items of this rule (e.g. the net salary, "
             "so that it can be paid to the employee).")
    analytic_distribution = fields.Json(groups="hr.group_hr_user")
