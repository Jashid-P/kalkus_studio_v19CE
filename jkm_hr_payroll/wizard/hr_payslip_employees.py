# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class HrPayslipEmployees(models.TransientModel):
    _name = 'hr.payslip.employees'
    _description = 'Generate payslips for all selected employees'

    def _get_payslip_run(self):
        if self.env.context.get('active_model') == 'hr.payslip.run':
            return self.env['hr.payslip.run'].browse(self.env.context.get('active_id'))
        return self.env['hr.payslip.run']

    def _get_available_versions_domain(self):
        run = self._get_payslip_run()
        return [
            ('contract_date_start', '!=', False),
            ('contract_date_start', '<=', run.date_end or fields.Date.today()),
            '|', ('contract_date_end', '=', False), ('contract_date_end', '>=', run.date_start or fields.Date.today()),
            ('company_id', '=', (run.company_id or self.env.company).id),
            ('employee_id.active', '=', True),
        ]

    payslip_run_id = fields.Many2one('hr.payslip.run', default=_get_payslip_run, readonly=True)
    employee_ids = fields.Many2many(
        'hr.employee', 'hr_employee_group_rel', 'payslip_id', 'employee_id', 'Employees',
        required=True,
        compute='_compute_employee_ids', store=True, readonly=False)
    structure_id = fields.Many2one(
        'hr.payroll.structure', string='Salary Structure',
        default=lambda self: self._get_payslip_run().structure_id)
    structure_type_id = fields.Many2one('hr.payroll.structure.type', string='Salary Structure Type')
    department_id = fields.Many2one('hr.department')

    @api.depends('department_id', 'structure_type_id')
    def _compute_employee_ids(self):
        for wizard in self:
            domain = wizard._get_available_versions_domain()
            if wizard.department_id:
                domain.append(('department_id', 'child_of', wizard.department_id.id))
            if wizard.structure_type_id:
                domain.append(('structure_type_id', '=', wizard.structure_type_id.id))
            wizard.employee_ids = self.env['hr.version'].search(domain).employee_id

    def compute_sheet(self):
        self.ensure_one()
        run = self.payslip_run_id or self._get_payslip_run()
        if not run:
            raise UserError(self.env._("Open this wizard from a payslip batch."))
        employees = self.employee_ids.filtered(lambda e: e not in run.slip_ids.employee_id)
        if not employees:
            raise UserError(self.env._("You must select employee(s) without a payslip in this batch."))

        versions = employees._get_versions_with_contract_overlap_with_period(run.date_start, run.date_end)
        versions.sudo().generate_work_entries(run.date_start, run.date_end)

        vals_list = []
        for employee in employees:
            employee_versions = versions.filtered(lambda v: v.employee_id == employee)
            if not employee_versions:
                continue
            version = employee._get_version(run.date_end)
            if version not in employee_versions:
                version = max(employee_versions, key=lambda v: v.date_version)
            struct = self.structure_id or version.structure_type_id.default_struct_id
            if not struct:
                continue
            vals_list.append({
                'employee_id': employee.id,
                'version_id': version.id,
                'struct_id': struct.id,
                'payslip_run_id': run.id,
                'date_from': run.date_start,
                'date_to': run.date_end,
                'company_id': run.company_id.id,
            })
        if not vals_list:
            raise UserError(self.env._(
                "No payslip could be generated: check that the selected employees have a running "
                "contract and a salary structure type with a default pay structure."))
        payslips = self.env['hr.payslip'].create(vals_list)
        payslips.compute_sheet()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip.run',
            'views': [[False, 'form']],
            'res_id': run.id,
        }
