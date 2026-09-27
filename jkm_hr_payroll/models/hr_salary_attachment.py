# -*- coding: utf-8 -*-
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrSalaryAttachment(models.Model):
    _name = 'hr.salary.attachment'
    _description = 'Salary Attachment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'state, date_start desc, id desc'
    _rec_name = 'description'

    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, index=True, tracking=True,
        domain="[('company_id', 'in', allowed_company_ids)]")
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        compute='_compute_company_id', store=True, readonly=False,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    description = fields.Char(required=True, tracking=True)
    other_input_type_id = fields.Many2one(
        'hr.payslip.input.type', string='Type', required=True, tracking=True,
        domain=[('available_in_attachments', '=', True)])
    date_start = fields.Date(
        string='Start Date', required=True, tracking=True,
        default=lambda self: date.today().replace(day=1))
    date_estimated_end = fields.Date(
        string='Estimated End Date', compute='_compute_estimated_end',
        help="Approximated end date based on the monthly amount and the remaining amount to pay.")
    date_end = fields.Date(
        string='End Date', tracking=True, copy=False,
        help="Date at which this assignment has been set as completed or cancelled.")
    no_end_date = fields.Boolean(
        string="No End Date", tracking=True,
        help="Deduct the monthly amount every month until the attachment is manually closed.")
    monthly_amount = fields.Monetary(string='Payslip Amount', required=True, tracking=True,
                                     help="Amount to pay each payslip.")
    total_amount = fields.Monetary(string='Total Amount', tracking=True, help="Total amount to be paid.")
    paid_amount = fields.Monetary(string='Paid Amount', compute='_compute_paid_amount', store=True)
    remaining_amount = fields.Monetary(string='Remaining Amount', compute='_compute_remaining_amount', store=True)
    state = fields.Selection([
        ('open', 'Running'),
        ('close', 'Completed'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='open', required=True, tracking=True, copy=False)
    payslip_input_ids = fields.One2many('hr.payslip.input', 'attachment_id', string='Payslip Inputs', readonly=True)
    payslip_count = fields.Integer(compute='_compute_payslip_count')
    note = fields.Text()

    _check_monthly_amount = models.Constraint(
        'CHECK (monthly_amount > 0)', 'Payslip amount must be strictly positive.')
    _check_total_amount = models.Constraint(
        'CHECK ((total_amount > 0 AND total_amount >= monthly_amount) OR no_end_date = True)',
        'Total amount must be strictly positive and greater than or equal to the payslip amount.')

    @api.depends('employee_id')
    def _compute_company_id(self):
        for attachment in self:
            if attachment.employee_id:
                attachment.company_id = attachment.employee_id.company_id

    @api.depends('payslip_input_ids.amount', 'payslip_input_ids.payslip_id.state',
                 'payslip_input_ids.payslip_id.credit_note')
    def _compute_paid_amount(self):
        for attachment in self:
            paid = 0.0
            for payslip_input in attachment.payslip_input_ids:
                slip = payslip_input.payslip_id
                if slip.state in ('validated', 'paid'):
                    paid += -payslip_input.amount if slip.credit_note else payslip_input.amount
            attachment.paid_amount = paid

    @api.depends('total_amount', 'paid_amount', 'no_end_date')
    def _compute_remaining_amount(self):
        for attachment in self:
            attachment.remaining_amount = 0.0 if attachment.no_end_date \
                else max(attachment.total_amount - attachment.paid_amount, 0.0)

    @api.depends('date_start', 'monthly_amount', 'remaining_amount', 'no_end_date')
    def _compute_estimated_end(self):
        for attachment in self:
            if attachment.no_end_date or not attachment.monthly_amount or attachment.state != 'open':
                attachment.date_estimated_end = False
                continue
            months = -(-attachment.remaining_amount // attachment.monthly_amount)  # ceil
            start = max(attachment.date_start, date.today().replace(day=1))
            attachment.date_estimated_end = start + relativedelta(months=int(months), days=-1)

    @api.depends('payslip_input_ids')
    def _compute_payslip_count(self):
        for attachment in self:
            attachment.payslip_count = len(attachment.payslip_input_ids.payslip_id)

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for attachment in self:
            if attachment.date_end and attachment.date_end < attachment.date_start:
                raise ValidationError(self.env._("End date may not be before the starting date."))

    def _get_amount_for_payslip(self):
        """Amount to deduct on the next payslip."""
        self.ensure_one()
        if self.no_end_date:
            return self.monthly_amount
        return min(self.monthly_amount, self.remaining_amount)

    def _update_state_after_payment(self):
        for attachment in self:
            if attachment.state == 'open' and not attachment.no_end_date \
                    and attachment.currency_id.compare_amounts(attachment.remaining_amount, 0) <= 0:
                attachment.write({'state': 'close', 'date_end': fields.Date.today()})
            elif attachment.state == 'close' and not attachment.no_end_date \
                    and attachment.currency_id.compare_amounts(attachment.remaining_amount, 0) > 0:
                attachment.write({'state': 'open', 'date_end': False})

    def action_done(self):
        self.write({'state': 'close', 'date_end': fields.Date.today()})

    def action_cancel(self):
        self.write({'state': 'cancel', 'date_end': fields.Date.today()})

    def action_open(self):
        self.write({'state': 'open', 'date_end': False})

    def action_open_payslips(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('jkm_hr_payroll.action_view_hr_payslip_month_form')
        action['domain'] = [('id', 'in', self.payslip_input_ids.payslip_id.ids)]
        action['context'] = {}
        return action
