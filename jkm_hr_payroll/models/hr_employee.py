# -*- coding: utf-8 -*-
from odoo import fields, models

PAYROLL_GROUPS = "hr.group_hr_manager,jkm_hr_payroll.group_hr_payroll_user"


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    slip_ids = fields.One2many('hr.payslip', 'employee_id', string='Payslips', readonly=True, groups=PAYROLL_GROUPS)
    payslip_count = fields.Integer(compute='_compute_payslip_count', string='Payslip Count', groups=PAYROLL_GROUPS)
    salary_attachment_count = fields.Integer(compute='_compute_salary_attachment_count', groups=PAYROLL_GROUPS)
    schedule_pay = fields.Selection(related='version_id.schedule_pay', readonly=False, inherited=True, groups=PAYROLL_GROUPS)
    wage_type = fields.Selection(related='version_id.wage_type', readonly=False, inherited=True, groups=PAYROLL_GROUPS)
    hourly_wage = fields.Monetary(related='version_id.hourly_wage', readonly=False, inherited=True, groups=PAYROLL_GROUPS)

    def _compute_payslip_count(self):
        counts = dict(self.env['hr.payslip']._read_group(
            [('employee_id', 'in', self.ids)], ['employee_id'], ['__count']))
        for employee in self:
            employee.payslip_count = counts.get(employee, 0)

    def _compute_salary_attachment_count(self):
        counts = dict(self.env['hr.salary.attachment']._read_group(
            [('employee_id', 'in', self.ids), ('state', '=', 'open')], ['employee_id'], ['__count']))
        for employee in self:
            employee.salary_attachment_count = counts.get(employee, 0)

    def action_open_payslips(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('jkm_hr_payroll.action_view_hr_payslip_month_form')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action

    def action_open_salary_attachments(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('jkm_hr_payroll.action_hr_salary_attachment')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action
