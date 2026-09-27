# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.fields import Command


class HrPayrollStructure(models.Model):
    _name = 'hr.payroll.structure'
    _description = 'Salary Structure'
    _order = 'type_id, name, id'

    @api.model
    def _get_default_report_id(self):
        return self.env.ref('jkm_hr_payroll.action_report_payslip', raise_if_not_found=False)

    @api.model
    def _get_default_rule_ids(self):
        """New structures start with the three rules every payslip needs."""
        categories = {
            code: self.env.ref(f'jkm_hr_payroll.{code}', raise_if_not_found=False)
            for code in ('BASIC', 'GROSS', 'NET')
        }
        if not all(categories.values()):
            return []
        return [
            Command.create({
                'name': self.env._('Basic Salary'),
                'sequence': 1,
                'code': 'BASIC',
                'category_id': categories['BASIC'].id,
                'condition_select': 'none',
                'amount_select': 'code',
                'amount_python_compute': 'result = payslip.paid_amount',
            }),
            Command.create({
                'name': self.env._('Gross'),
                'sequence': 100,
                'code': 'GROSS',
                'category_id': categories['GROSS'].id,
                'condition_select': 'none',
                'amount_select': 'code',
                'amount_python_compute': "result = categories['BASIC'] + categories['ALW']",
            }),
            Command.create({
                'name': self.env._('Net Salary'),
                'sequence': 200,
                'code': 'NET',
                'category_id': categories['NET'].id,
                'condition_select': 'none',
                'amount_select': 'code',
                'amount_python_compute': "result = categories['BASIC'] + categories['ALW'] + categories['DED']",
            }),
        ]

    @api.model
    def _get_default_work_entry_type_ids(self):
        unpaid = self.env.ref('hr_work_entry.work_entry_type_unpaid_leave', raise_if_not_found=False)
        return unpaid.ids if unpaid else []

    name = fields.Char(required=True, translate=True)
    code = fields.Char()
    active = fields.Boolean(default=True)
    type_id = fields.Many2one(
        'hr.payroll.structure.type', string="Structure Type", required=True, index=True,
        default=lambda self: self.env['hr.payroll.structure.type'].search([], limit=1))
    country_id = fields.Many2one(
        'res.country', string='Country',
        default=lambda self: self.env.company.country_id)
    country_code = fields.Char(related='country_id.code')
    note = fields.Html(string='Description')
    rule_ids = fields.One2many(
        'hr.salary.rule', 'struct_id', string='Salary Rules',
        copy=True, default=_get_default_rule_ids)
    rule_count = fields.Integer(compute='_compute_rule_count')
    report_id = fields.Many2one(
        'ir.actions.report', string="Report",
        domain="[('model', '=', 'hr.payslip'), ('report_type', '=', 'qweb-pdf')]",
        default=_get_default_report_id)
    payslip_name = fields.Char(
        string="Payslip Name", translate=True,
        help="Name to be set on a payslip. Example: 'End of the year bonus'. "
             "If not set, the default value is 'Salary Slip'.")
    hide_basic_on_pdf = fields.Boolean(
        help="Enable this option if you don't want to display the Basic Salary on the printed pdf.")
    unpaid_work_entry_type_ids = fields.Many2many(
        'hr.work.entry.type', 'hr_payroll_structure_hr_work_entry_type_rel',
        string="Unpaid Work Entry Types", default=_get_default_work_entry_type_ids)
    proration_method = fields.Selection([
        ('fixed_30', 'Fixed 30 days per month'),
        ('working_days', 'Working schedule of the period'),
    ], string="Salary Proration", default='fixed_30', required=True,
        help="How a fixed monthly wage is reduced for unpaid days (unpaid time off, days out of contract):\n"
             "* Fixed 30 days per month: each unpaid day deducts wage / 30; days out of contract "
             "are counted in calendar days.\n"
             "* Working schedule of the period: the wage is spread over the working hours of the "
             "period, so a day is worth wage / working days of the month.\n"
             "Only applies to monthly pay schedules with a fixed wage.")
    use_worked_day_lines = fields.Boolean(
        default=True, help="If unchecked, worked days are neither computed nor displayed on payslips.")
    schedule_pay = fields.Selection(related='type_id.default_schedule_pay')
    input_line_type_ids = fields.Many2many(
        'hr.payslip.input.type', string='Other Input Line',
        help="Other inputs that can be encoded on the payslips of this structure.")

    @api.depends('rule_ids')
    def _compute_rule_count(self):
        for structure in self:
            structure.rule_count = len(structure.rule_ids)

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        if default and 'name' in default:
            return vals_list
        return [
            dict(vals, name=self.env._("%s (copy)", structure.name))
            for structure, vals in zip(self, vals_list)
        ]

    def action_open_rules(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('jkm_hr_payroll.action_hr_salary_rule')
        action['domain'] = [('struct_id', '=', self.id)]
        action['context'] = {'default_struct_id': self.id, 'search_default_group_by_category': 0}
        return action
