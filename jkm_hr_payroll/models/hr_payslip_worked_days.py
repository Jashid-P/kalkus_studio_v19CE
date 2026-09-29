# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrPayslipWorkedDays(models.Model):
    _name = 'hr.payslip.worked_days'
    _description = 'Payslip Worked Days'
    _order = 'payslip_id, sequence, id'

    name = fields.Char(compute='_compute_name', store=True, string='Description', readonly=False)
    payslip_id = fields.Many2one('hr.payslip', string='Pay Slip', required=True, ondelete='cascade', index=True)
    date_from = fields.Date(string='From', related="payslip_id.date_from", store=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', related='payslip_id.employee_id', store=True)
    sequence = fields.Integer(required=True, index=True, default=10)
    code = fields.Char(string='Code', related='work_entry_type_id.code')
    work_entry_type_id = fields.Many2one(
        'hr.work.entry.type', string='Type', required=True,
        help="The code that can be used in the salary rules")
    number_of_days = fields.Float(string='Number of Days')
    number_of_hours = fields.Float(string='Number of Hours')
    is_paid = fields.Boolean(compute='_compute_is_paid', store=True)
    amount = fields.Monetary(string='Amount', compute='_compute_amount', store=True, readonly=False, copy=True)
    version_id = fields.Many2one(related='payslip_id.version_id', string='Contract')
    currency_id = fields.Many2one('res.currency', related='payslip_id.currency_id')

    @api.depends('work_entry_type_id')
    def _compute_name(self):
        for worked_days in self:
            worked_days.name = worked_days.work_entry_type_id.name

    @api.depends('work_entry_type_id', 'payslip_id.struct_id')
    def _compute_is_paid(self):
        out_of_contract = self.env.ref('hr_work_entry.hr_work_entry_type_out_of_contract', raise_if_not_found=False)
        for worked_days in self:
            unpaid = worked_days.payslip_id.struct_id.unpaid_work_entry_type_ids | out_of_contract
            worked_days.is_paid = worked_days.work_entry_type_id not in unpaid

    @api.depends('is_paid', 'number_of_hours', 'number_of_days', 'payslip_id', 'payslip_id.version_id.wage',
                 'payslip_id.version_id.hourly_wage', 'payslip_id.version_id.wage_type',
                 'payslip_id.struct_id.proration_method',
                 'payslip_id.worked_days_line_ids.number_of_hours',
                 'payslip_id.worked_days_line_ids.number_of_days',
                 'payslip_id.worked_days_line_ids.is_paid')
    def _compute_amount(self):
        for slip, lines in self.grouped('payslip_id').items():
            if slip.state != 'draft':
                continue  # keep the amounts of confirmed payslips frozen
            amounts = slip.worked_days_line_ids._get_amounts()
            for worked_days in lines:
                worked_days.amount = amounts.get(worked_days, 0.0)

    def _get_amounts(self):
        """Amount of each worked days line of a single payslip."""
        slip = self.payslip_id[:1]
        version = slip.version_id
        if not version:
            return {}
        if version.wage_type == 'hourly':
            return {
                line: version.hourly_wage * line.number_of_hours * line.work_entry_type_id.amount_rate
                for line in self if line.is_paid
            }
        regular = self.filtered(lambda line: not line.work_entry_type_id.is_extra_hours)
        extra = self - regular
        wage = version.wage
        amounts = {}
        if slip._is_fixed_30_proration():
            # Each unpaid day deducts wage / 30 per month of the period (wage / 30 monthly,
            # wage / 90 quarterly...), whatever the real length of the months.
            day_rate = wage / slip._get_proration_basis_days()
            hours_per_day = version.resource_calendar_id.hours_per_day or 8.0
            unpaid_days = sum(regular.filtered(lambda line: not line.is_paid).mapped('number_of_days'))
            paid_total = max(wage - unpaid_days * day_rate, 0.0)
            paid = regular.filtered('is_paid')
            paid_hours = sum(paid.mapped('number_of_hours'))
            for line in paid:
                share = paid_total * line.number_of_hours / paid_hours if paid_hours else 0.0
                # a reduced rate (e.g. 60% sick leave) loses the rest of its day value
                share -= (1 - line.work_entry_type_id.amount_rate) * line.number_of_days * day_rate
                amounts[line] = max(share, 0.0)
            for line in extra.filtered('is_paid'):
                amounts[line] = day_rate / hours_per_day * line.number_of_hours * line.work_entry_type_id.amount_rate
            return amounts
        # Working schedule: the wage covers every regular hour of the period
        # (paid or not, in or out of contract); extra hours come on top.
        period_hours = sum(regular.mapped('number_of_hours'))
        if not period_hours:
            return {}
        for line in self.filtered('is_paid'):
            amounts[line] = wage * line.number_of_hours / period_hours * line.work_entry_type_id.amount_rate
        return amounts
