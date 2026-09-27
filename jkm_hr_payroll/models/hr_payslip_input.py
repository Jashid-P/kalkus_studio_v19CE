# -*- coding: utf-8 -*-
from odoo import fields, models


class HrPayslipInput(models.Model):
    _name = 'hr.payslip.input'
    _description = 'Payslip Input'
    _order = 'payslip_id, sequence, id'

    name = fields.Char(string="Description")
    payslip_id = fields.Many2one('hr.payslip', string='Pay Slip', required=True, ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', related='payslip_id.employee_id')
    date_from = fields.Date(related='payslip_id.date_from')
    sequence = fields.Integer(required=True, index=True, default=10)
    input_type_id = fields.Many2one(
        'hr.payslip.input.type', string='Type', required=True,
        domain="['|', ('id', 'in', _allowed_input_type_ids), ('struct_ids', '=', False)]")
    _allowed_input_type_ids = fields.Many2many(
        'hr.payslip.input.type', related='payslip_id.struct_id.input_line_type_ids')
    code = fields.Char(related='input_type_id.code', help="The code that can be used in the salary rules")
    amount = fields.Float(
        string="Count", digits='Payroll',
        help="It is used in computation. E.g. a rule for salesmen having 1% commission of basic salary per product "
             "can defined in expression like: result = inputs['SALEURO'].amount * version.wage * 0.01.")
    version_id = fields.Many2one(related='payslip_id.version_id', string='Contract')
    attachment_id = fields.Many2one(
        'hr.salary.attachment', string='Salary Attachment', index='btree_not_null', ondelete='set null',
        readonly=True, help="Salary attachment this input was generated from.")
