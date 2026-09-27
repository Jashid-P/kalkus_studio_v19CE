# -*- coding: utf-8 -*-
from odoo import fields, models


class HrPayslipInputType(models.Model):
    _name = 'hr.payslip.input.type'
    _description = 'Payslip Input Type'
    _order = 'name, id'

    name = fields.Char(string='Description', required=True, translate=True)
    code = fields.Char(required=True, help="The code that can be used in the salary rules")
    struct_ids = fields.Many2many(
        'hr.payroll.structure', string='Availability in Structure',
        help='This input will be only available in those structure. If empty, it will be available in all payslip.')
    country_id = fields.Many2one(
        'res.country', string='Country',
        default=lambda self: self.env.company.country_id)
    country_code = fields.Char(related='country_id.code')
    active = fields.Boolean(default=True)
    available_in_attachments = fields.Boolean(
        string="Available in attachments",
        help="If set, this input type can be used on salary attachments.")
    is_quantity = fields.Boolean(
        default=False, string="Is quantity?",
        help="If set, hide currency and consider the manual input as a quantity for every rule computation using this input.")
