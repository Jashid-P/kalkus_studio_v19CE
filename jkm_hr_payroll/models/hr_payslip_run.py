# -*- coding: utf-8 -*-
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class HrPayslipRun(models.Model):
    _name = 'hr.payslip.run'
    _description = 'Payslip Batches'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_end desc, id desc'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    slip_ids = fields.One2many('hr.payslip', 'payslip_run_id', string='Payslips')
    state = fields.Selection([
        ('01_ready', 'Ready'),
        ('02_close', 'Done'),
        ('03_paid', 'Paid'),
        ('04_cancel', 'Cancelled'),
    ], string='Status', index=True, readonly=True, copy=False, default='01_ready', tracking=True,
        compute='_compute_state', store=True)
    date_start = fields.Date(
        string='Date From', required=True,
        default=lambda self: date.today().replace(day=1))
    date_end = fields.Date(
        string='Date To', required=True,
        default=lambda self: date.today() + relativedelta(day=31))
    structure_id = fields.Many2one(
        'hr.payroll.structure', string='Salary Structure',
        help="If set, only this structure is used when generating the payslips.")
    payslip_count = fields.Integer(compute='_compute_payslip_count', store=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, copy=False,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    gross_sum = fields.Monetary(compute='_compute_totals', store=True, string="Gross")
    net_sum = fields.Monetary(compute='_compute_totals', store=True, string="Net")
    employer_cost_sum = fields.Monetary(compute='_compute_totals', store=True, string="Employer Cost")

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        if any(run.date_start > run.date_end for run in self):
            raise UserError(self.env._("The batch start date must be before its end date."))

    @api.depends('slip_ids.state')
    def _compute_state(self):
        for run in self:
            states = set(run.slip_ids.mapped('state')) - {'cancel'}
            if not run.slip_ids:
                run.state = run.state or '01_ready'
            elif not states:
                run.state = '04_cancel'
            elif states == {'paid'}:
                run.state = '03_paid'
            elif 'draft' not in states:
                run.state = '02_close'
            else:
                run.state = '01_ready'

    @api.depends('slip_ids')
    def _compute_payslip_count(self):
        for run in self:
            run.payslip_count = len(run.slip_ids)

    @api.depends('slip_ids.gross_wage', 'slip_ids.net_wage', 'slip_ids.employer_cost', 'slip_ids.state')
    def _compute_totals(self):
        for run in self:
            slips = run.slip_ids.filtered(lambda s: s.state != 'cancel')
            run.gross_sum = sum(slips.mapped('gross_wage'))
            run.net_sum = sum(slips.mapped('net_wage'))
            run.employer_cost_sum = sum(slips.mapped('employer_cost'))

    @api.ondelete(at_uninstall=False)
    def _unlink_if_no_confirmed_slip(self):
        if any(slip.state not in ('draft', 'cancel') for slip in self.slip_ids):
            raise UserError(self.env._("You cannot delete a batch containing confirmed payslips."))

    def action_open_payslip_employees(self):
        self.ensure_one()
        return {
            'name': self.env._('Generate Payslips'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip.employees',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'active_id': self.id, 'active_model': 'hr.payslip.run'},
        }

    def action_compute_sheets(self):
        self.slip_ids.filtered(lambda s: s.state == 'draft').compute_sheet()

    def action_validate(self):
        self.slip_ids.filtered(lambda s: s.state == 'draft').action_payslip_done()

    def action_paid(self):
        self.slip_ids.filtered(lambda s: s.state == 'validated').action_payslip_paid()

    def action_draft(self):
        self.slip_ids.filtered(lambda s: s.state in ('validated', 'cancel')).action_payslip_draft()
        self.state = '01_ready'

    def action_cancel(self):
        self.slip_ids.filtered(lambda s: s.state != 'paid').action_payslip_cancel()

    def action_open_payslips(self):
        self.ensure_one()
        return {
            'name': self.env._('Payslips'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('id', 'in', self.slip_ids.ids)],
            'context': {'default_payslip_run_id': self.id,
                        'default_date_from': self.date_start, 'default_date_to': self.date_end},
        }

    def action_print_payslips(self):
        return self.env.ref('jkm_hr_payroll.action_report_payslip').report_action(
            self.slip_ids.filtered(lambda s: s.state in ('validated', 'paid')))
