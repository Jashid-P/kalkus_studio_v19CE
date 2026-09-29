# -*- coding: utf-8 -*-
from odoo import api, fields, models

PAYROLL_GROUPS = "hr.group_hr_manager,jkm_hr_payroll.group_hr_payroll_user"


class HrVersion(models.Model):
    _inherit = 'hr.version'

    # Payroll officers need the contract data to compute payslips.
    contract_date_start = fields.Date(groups=PAYROLL_GROUPS)
    contract_date_end = fields.Date(groups=PAYROLL_GROUPS)
    trial_date_end = fields.Date(groups=PAYROLL_GROUPS)
    date_start = fields.Date(groups=PAYROLL_GROUPS)
    date_end = fields.Date(groups=PAYROLL_GROUPS)
    is_current = fields.Boolean(groups=PAYROLL_GROUPS)
    is_past = fields.Boolean(groups=PAYROLL_GROUPS)
    is_future = fields.Boolean(groups=PAYROLL_GROUPS)
    is_in_contract = fields.Boolean(groups=PAYROLL_GROUPS)
    wage = fields.Monetary(
        groups=PAYROLL_GROUPS,
        help="Gross wage for one pay period of the Pay Schedule: per day for Daily, per week for "
             "Weekly, per month for Monthly, per year for Annually...")
    contract_wage = fields.Monetary(groups=PAYROLL_GROUPS)
    structure_type_id = fields.Many2one(groups=PAYROLL_GROUPS)
    work_entry_source = fields.Selection(groups=PAYROLL_GROUPS)
    work_entry_source_calendar_invalid = fields.Boolean(groups=PAYROLL_GROUPS)

    schedule_pay = fields.Selection(
        selection=lambda self: self.env['hr.payroll.structure.type']._get_selection_schedule_pay(),
        compute='_compute_schedule_pay', store=True, readonly=False, tracking=True,
        string='Pay Schedule', groups=PAYROLL_GROUPS,
        help="Defines the frequency of the wage payment.")
    wage_type = fields.Selection(
        [('monthly', 'Fixed Wage'), ('hourly', 'Hourly Wage')],
        compute='_compute_wage_type', store=True, readonly=False, tracking=True,
        string='Wage Type', groups=PAYROLL_GROUPS)
    hourly_wage = fields.Monetary(
        'Hourly Wage', tracking=True, groups=PAYROLL_GROUPS,
        help="Employee's hourly gross wage.")
    structure_id = fields.Many2one(
        'hr.payroll.structure', related='structure_type_id.default_struct_id',
        string='Pay Structure', groups=PAYROLL_GROUPS)
    payslips_count = fields.Integer("# Payslips", compute='_compute_payslips_count', groups=PAYROLL_GROUPS)

    @api.depends('structure_type_id')
    def _compute_schedule_pay(self):
        for version in self:
            version.schedule_pay = version.structure_type_id.default_schedule_pay or version.schedule_pay or 'monthly'

    @api.depends('structure_type_id')
    def _compute_wage_type(self):
        for version in self:
            version.wage_type = version.structure_type_id.wage_type or version.wage_type or 'monthly'

    def _compute_payslips_count(self):
        counts = dict(self.env['hr.payslip'].sudo()._read_group(
            [('version_id', 'in', self.ids)], ['version_id'], ['__count']))
        for version in self:
            version.payslips_count = counts.get(version, 0)

    def _get_contract_wage(self):
        self.ensure_one()
        return self.hourly_wage if self.wage_type == 'hourly' else self.wage

    @api.model
    def _get_whitelist_fields_from_template(self):
        return super()._get_whitelist_fields_from_template() + ['schedule_pay', 'wage_type', 'hourly_wage']

    def action_open_payslips(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('jkm_hr_payroll.action_view_hr_payslip_month_form')
        action['domain'] = [('version_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.employee_id.id}
        return action
