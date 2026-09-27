# -*- coding: utf-8 -*-
import base64
import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.tools import float_compare, float_round, format_date
from odoo.tools.safe_eval import datetime as safe_eval_datetime, dateutil as safe_eval_dateutil


class PayrollDict(defaultdict):
    """Dict used in the salary rules evaluation context.

    Supports both ``categories['BASIC']`` (Enterprise 17+ style) and
    ``categories.BASIC`` (legacy style) so rules can be ported unchanged.
    """

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self[name]


class PayslipInputSum:
    """Aggregation of the payslip inputs sharing the same code."""

    def __init__(self, input_lines, sign=1):
        self._lines = input_lines
        self._sign = sign

    @property
    def amount(self):
        return self._sign * sum(self._lines.mapped('amount'))

    @property
    def name(self):
        return self._lines[:1].name or self._lines[:1].input_type_id.name

    @property
    def code(self):
        return self._lines[:1].code

    @property
    def ids(self):
        return self._lines.ids


class HrPayslip(models.Model):
    _name = 'hr.payslip'
    _description = 'Pay Slip'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_to desc, id desc'

    struct_id = fields.Many2one(
        'hr.payroll.structure', string='Structure', tracking=True,
        compute='_compute_struct_id', store=True, readonly=False, precompute=True,
        domain="[('type_id', '=?', struct_type_id)]",
        help='Defines the rules that have to be applied to this payslip, according to the contract chosen.')
    struct_type_id = fields.Many2one('hr.payroll.structure.type', related='version_id.structure_type_id')
    wage_type = fields.Selection(related='version_id.wage_type')
    name = fields.Char(
        string='Payslip Name', required=True, compute='_compute_name', store=True, readonly=False,
        precompute=True)
    number = fields.Char(string='Reference', copy=False, readonly=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, tracking=True, index=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    image_128 = fields.Image(related='employee_id.image_128')
    department_id = fields.Many2one('hr.department', string='Department', related='employee_id.department_id',
                                    readonly=True, store=True)
    job_id = fields.Many2one('hr.job', string='Job Position', related='employee_id.job_id', readonly=True, store=True)
    date_from = fields.Date(
        string='From', required=True, tracking=True,
        default=lambda self: date.today().replace(day=1))
    date_to = fields.Date(
        string='To', required=True, tracking=True,
        compute='_compute_date_to', store=True, readonly=False, precompute=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('validated', 'Done'),
        ('paid', 'Paid'),
        ('cancel', 'Cancelled'),
    ], string='Status', index=True, readonly=True, copy=False, default='draft', tracking=True,
        help="* When the payslip is created the status is 'Draft'.\n"
             "* If the payslip is confirmed then status is set to 'Done'.\n"
             "* When the payslip is paid the status is 'Paid'.\n"
             "* When the user cancels a payslip, the status is 'Cancelled'.")
    line_ids = fields.One2many('hr.payslip.line', 'slip_id', string='Payslip Lines', readonly=True, copy=False)
    company_id = fields.Many2one(
        'res.company', string='Company', copy=False, required=True,
        compute='_compute_company_id', store=True, readonly=False, precompute=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    worked_days_line_ids = fields.One2many(
        'hr.payslip.worked_days', 'payslip_id', string='Payslip Worked Days', copy=True,
        compute='_compute_worked_days_line_ids', store=True, readonly=False)
    input_line_ids = fields.One2many('hr.payslip.input', 'payslip_id', string='Payslip Inputs', copy=True)
    note = fields.Text(string='Internal Note')
    version_id = fields.Many2one(
        'hr.version', string='Contract', tracking=True, index=True,
        compute='_compute_version_id', store=True, readonly=False, precompute=True,
        domain="[('employee_id', '=', employee_id), ('company_id', '=', company_id)]")
    credit_note = fields.Boolean(
        string='Credit Note', copy=False,
        help="Indicates this payslip has a refund of another")
    origin_payslip_id = fields.Many2one('hr.payslip', string="Origin Payslip", copy=False, readonly=True)
    refund_count = fields.Integer(compute='_compute_refund_count')
    payslip_run_id = fields.Many2one(
        'hr.payslip.run', string='Batch', index=True, copy=False, ondelete='cascade',
        domain="[('state', '=', '01_ready'), ('company_id', '=', company_id)]")
    compute_date = fields.Date('Computed On', readonly=True, copy=False)
    paid_date = fields.Date(string="Payment Date", readonly=True, copy=False, tracking=True)
    basic_wage = fields.Monetary(compute='_compute_basic_net', store=True, string="Basic Wage")
    gross_wage = fields.Monetary(compute='_compute_basic_net', store=True, string="Gross Wage")
    net_wage = fields.Monetary(compute='_compute_basic_net', store=True, string="Net Wage")
    employer_cost = fields.Monetary(compute='_compute_basic_net', store=True, string="Employer Cost")
    sum_worked_hours = fields.Float(compute='_compute_worked_hours', store=True, string="Worked Hours")
    salary_attachment_count = fields.Integer(compute='_compute_salary_attachment_count')
    warning_message = fields.Char(compute='_compute_warning_message')
    color = fields.Integer(compute='_compute_color')

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        if any(slip.date_from > slip.date_to for slip in self):
            raise ValidationError(self.env._("Payslip 'Date From' must be earlier than 'Date To'."))

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    @api.depends('employee_id')
    def _compute_company_id(self):
        for slip in self:
            if slip.employee_id:
                slip.company_id = slip.employee_id.company_id

    @api.depends('employee_id', 'date_from', 'date_to')
    def _compute_version_id(self):
        for slip in self:
            if slip.state not in ('draft', False) and slip.version_id:
                continue
            if not slip.employee_id or not slip.date_from or not slip.date_to:
                slip.version_id = False
                continue
            versions = slip.employee_id._get_versions_with_contract_overlap_with_period(
                slip.date_from, slip.date_to)
            if not versions:
                slip.version_id = False
                continue
            version = slip.employee_id._get_version(slip.date_to)
            slip.version_id = version if version in versions else max(versions, key=lambda v: v.date_version)

    @api.depends('version_id')
    def _compute_struct_id(self):
        for slip in self:
            default_struct = slip.version_id.structure_type_id.default_struct_id
            if not slip.struct_id or (default_struct and slip.struct_id.type_id != slip.version_id.structure_type_id):
                slip.struct_id = default_struct

    @api.depends('date_from', 'version_id', 'struct_id')
    def _compute_date_to(self):
        StructureType = self.env['hr.payroll.structure.type']
        for slip in self:
            if not slip.date_from:
                slip.date_to = False
                continue
            slip.date_to = StructureType._get_schedule_period_end(slip._get_schedule_pay(), slip.date_from)

    def _get_schedule_pay(self):
        self.ensure_one()
        # version_id depends on date_to, so read the schedule from the employee directly
        version = self.version_id or (self.employee_id and self.employee_id._get_version(self.date_from))
        return (version and version.schedule_pay) or self.struct_id.schedule_pay or 'monthly'

    @api.depends('employee_id', 'struct_id', 'date_from', 'date_to', 'credit_note')
    def _compute_name(self):
        for slip in self:
            if not slip.employee_id or not slip.date_from:
                slip.name = slip.name or self.env._('New Payslip')
                continue
            label = slip.struct_id.payslip_name or self.env._('Salary Slip')
            slip.name = '%(label)s - %(employee)s - %(period)s' % {
                'label': label,
                'employee': slip.employee_id.legal_name or slip.employee_id.name,
                'period': slip._get_period_name(),
            }
            if slip.credit_note:
                slip.name = self.env._('Refund: %s', slip.name)

    def _get_period_name(self):
        self.ensure_one()
        lang = self.employee_id.lang or self.env.user.lang
        date_to = self.date_to or self.date_from
        is_full_month = self.date_from.day == 1 and (date_to.month != (date_to + timedelta(days=1)).month)
        if is_full_month and self.date_from.month == date_to.month and self.date_from.year == date_to.year:
            return format_date(self.env, self.date_from, lang_code=lang, date_format='MMMM y')
        return '%s - %s' % (
            format_date(self.env, self.date_from, lang_code=lang),
            format_date(self.env, date_to, lang_code=lang),
        )

    @api.depends('employee_id', 'version_id', 'struct_id', 'date_from', 'date_to', 'struct_id.use_worked_day_lines')
    def _compute_worked_days_line_ids(self):
        for slip in self:
            if slip.state not in ('draft', False) or slip.credit_note:
                continue
            if not slip.version_id or not slip.struct_id.use_worked_day_lines \
                    or not slip.date_from or not slip.date_to:
                slip.worked_days_line_ids = [Command.clear()]
                continue
            slip.worked_days_line_ids = [Command.clear()] + [
                Command.create(vals) for vals in slip._get_worked_day_lines_values()
            ]

    @api.depends('line_ids.total', 'line_ids.code', 'line_ids.salary_rule_id.appears_on_employee_cost_dashboard')
    def _compute_basic_net(self):
        for slip in self:
            totals = defaultdict(float)
            employer_cost = 0.0
            for line in slip.line_ids:
                totals[line.code] += line.total
                if line.salary_rule_id.appears_on_employee_cost_dashboard:
                    employer_cost += line.total
            slip.basic_wage = totals['BASIC']
            slip.gross_wage = totals['GROSS']
            slip.net_wage = totals['NET']
            slip.employer_cost = employer_cost + totals['GROSS']

    @api.depends('worked_days_line_ids.number_of_hours', 'worked_days_line_ids.is_paid')
    def _compute_worked_hours(self):
        for slip in self:
            slip.sum_worked_hours = sum(slip.worked_days_line_ids.filtered('is_paid').mapped('number_of_hours'))

    def _compute_refund_count(self):
        counts = dict(self.env['hr.payslip']._read_group(
            [('origin_payslip_id', 'in', self.ids)], ['origin_payslip_id'], ['__count']))
        for slip in self:
            slip.refund_count = counts.get(slip, 0)

    def _compute_salary_attachment_count(self):
        for slip in self:
            slip.salary_attachment_count = len(slip._get_active_salary_attachments())

    @api.depends('version_id', 'struct_id', 'employee_id', 'date_from', 'date_to', 'state')
    def _compute_warning_message(self):
        for slip in self:
            messages = []
            if slip.employee_id and not slip.version_id:
                messages.append(self.env._("The employee has no contract running during this period."))
            elif slip.version_id and not slip.struct_id:
                messages.append(self.env._(
                    "No salary structure: set a default structure on the salary structure type '%s'.",
                    slip.version_id.structure_type_id.name or '-'))
            if slip.state == 'draft' and slip.version_id and slip._get_conflicting_work_entries():
                messages.append(self.env._("Some work entries of this period are in conflict."))
            slip.warning_message = ' '.join(messages)

    def _compute_color(self):
        colors = {'draft': 0, 'validated': 10, 'paid': 4, 'cancel': 1}
        for slip in self:
            slip.color = colors.get(slip.state, 0)

    # ------------------------------------------------------------------
    # Work entries and worked days
    # ------------------------------------------------------------------

    def _get_period_datetimes(self):
        """UTC naive datetimes covering the payslip period in the employee timezone."""
        self.ensure_one()
        tz = pytz.timezone(self.version_id.resource_calendar_id.tz or self.employee_id.tz or 'UTC')
        start = tz.localize(datetime.combine(self.date_from, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        stop = tz.localize(datetime.combine(self.date_to, time.max)).astimezone(pytz.utc).replace(tzinfo=None)
        return start, stop

    def _get_work_entries_domain(self):
        self.ensure_one()
        return Domain([
            ('employee_id', '=', self.employee_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('company_id', '=', self.company_id.id),
        ])

    def _get_conflicting_work_entries(self):
        self.ensure_one()
        return self.env['hr.work.entry'].sudo().search(
            self._get_work_entries_domain() & Domain('state', '=', 'conflict'), limit=1)

    def _generate_missing_work_entries(self):
        """Make sure the work entries of the payslip periods exist."""
        for slip in self.filtered(lambda s: s.version_id and s.date_from and s.date_to):
            versions = slip.employee_id._get_versions_with_contract_overlap_with_period(slip.date_from, slip.date_to)
            versions.sudo().generate_work_entries(slip.date_from, slip.date_to)

    def _is_fixed_30_proration(self):
        self.ensure_one()
        return (
            self.struct_id.proration_method == 'fixed_30'
            and self.version_id.wage_type != 'hourly'
            and self._get_schedule_pay() == 'monthly'
        )

    def _get_out_of_contract_ranges(self):
        self.ensure_one()
        version = self.version_id
        ranges = []
        if version.contract_date_start and version.contract_date_start > self.date_from:
            ranges.append((self.date_from, min(self.date_to, version.contract_date_start - timedelta(days=1))))
        if version.contract_date_end and version.contract_date_end < self.date_to:
            ranges.append((max(self.date_from, version.contract_date_end + timedelta(days=1)), self.date_to))
        return [(start, stop) for start, stop in ranges if start <= stop]

    def _get_out_of_contract_hours(self):
        """Working hours of the period falling outside the contract dates."""
        self.ensure_one()
        version = self.version_id
        calendar = version.resource_calendar_id
        if not calendar:
            return 0.0
        tz = pytz.timezone(calendar.tz or 'UTC')
        hours = 0.0
        for start, stop in self._get_out_of_contract_ranges():
            start_dt = tz.localize(datetime.combine(start, time.min))
            stop_dt = tz.localize(datetime.combine(stop, time.max))
            hours += self.employee_id._get_work_days_data_batch(
                start_dt, stop_dt, compute_leaves=False, calendar=calendar)[self.employee_id.id]['hours']
        return hours

    def _get_worked_day_lines_values(self):
        """Worked days lines computed from the work entries of the period."""
        self.ensure_one()
        hours_per_day = self.version_id.resource_calendar_id.hours_per_day or 8.0
        domain = self._get_work_entries_domain() & Domain('state', 'in', ['draft', 'validated'])
        work_hours = self.env['hr.work.entry'].sudo()._read_group(
            domain, ['work_entry_type_id'], ['duration:sum'])
        values = []
        for work_entry_type, hours in sorted(work_hours, key=lambda wh: (wh[0].sequence, wh[0].id)):
            if not work_entry_type or float_compare(hours, 0.0, precision_digits=2) <= 0:
                continue
            values.append({
                'sequence': work_entry_type.sequence,
                'work_entry_type_id': work_entry_type.id,
                'number_of_days': float_round(hours / hours_per_day, precision_rounding=0.01),
                'number_of_hours': float_round(hours, precision_rounding=0.01),
            })
        out_hours = self._get_out_of_contract_hours()
        out_days = out_hours / hours_per_day
        if self._is_fixed_30_proration():
            # On a 30-day basis, days out of contract are calendar days (at most 30).
            out_days = min(sum((stop - start).days + 1 for start, stop in self._get_out_of_contract_ranges()), 30)
        out_type = self.env.ref('hr_work_entry.hr_work_entry_type_out_of_contract', raise_if_not_found=False)
        if out_type and (float_compare(out_hours, 0.0, precision_digits=2) > 0 or out_days > 0):
            values.append({
                'sequence': 999,
                'work_entry_type_id': out_type.id,
                'number_of_days': float_round(out_days, precision_rounding=0.01),
                'number_of_hours': float_round(out_hours, precision_rounding=0.01),
            })
        return values

    # ------------------------------------------------------------------
    # Salary attachments
    # ------------------------------------------------------------------

    def _get_active_salary_attachments(self):
        self.ensure_one()
        if not self.employee_id or not self.date_from or not self.date_to:
            return self.env['hr.salary.attachment']
        return self.env['hr.salary.attachment'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'open'),
            ('date_start', '<=', self.date_to),
            ('company_id', '=', self.company_id.id),
        ])

    def _refresh_salary_attachment_inputs(self):
        """(Re)create the input lines coming from the running salary attachments."""
        for slip in self.filtered(lambda s: s.state == 'draft' and not s.credit_note):
            slip.input_line_ids.filtered('attachment_id').unlink()
            commands = []
            for attachment in slip._get_active_salary_attachments():
                amount = attachment._get_amount_for_payslip()
                if attachment.currency_id.is_zero(amount):
                    continue
                commands.append(Command.create({
                    'name': attachment.description,
                    'input_type_id': attachment.other_input_type_id.id,
                    'amount': amount,
                    'attachment_id': attachment.id,
                }))
            if commands:
                slip.input_line_ids = commands

    # ------------------------------------------------------------------
    # Salary rules evaluation
    # ------------------------------------------------------------------

    @property
    def paid_amount(self):
        """Wage due for the period, prorated by the paid worked days."""
        self.ensure_one()
        return self._get_paid_amount()

    def _get_paid_amount(self):
        self.ensure_one()
        if not self.struct_id.use_worked_day_lines:
            return self.version_id._get_contract_wage()
        return self.currency_id.round(sum(self.worked_days_line_ids.filtered('is_paid').mapped('amount')))

    def _rule_parameter(self, code, reference_date=False):
        return self.env['hr.rule.parameter']._get_parameter_from_code(code, reference_date or self.date_to)

    def _sum(self, code, from_date, to_date=None):
        """Sum of the lines with ``code`` over the confirmed payslips of the employee."""
        to_date = to_date or fields.Date.today()
        lines = self.env['hr.payslip.line'].search([
            ('employee_id', '=', self.employee_id.id),
            ('code', '=', code),
            ('date_from', '>=', from_date),
            ('date_to', '<=', to_date),
            ('state', 'in', ['validated', 'paid']),
        ])
        return sum(lines.mapped('total'))

    def _sum_category(self, code, from_date, to_date=None):
        to_date = to_date or fields.Date.today()
        category = self.env['hr.salary.rule.category'].search([('code', '=', code)])
        lines = self.env['hr.payslip.line'].search([
            ('employee_id', '=', self.employee_id.id),
            ('category_id', 'child_of', category.ids),
            ('date_from', '>=', from_date),
            ('date_to', '<=', to_date),
            ('state', 'in', ['validated', 'paid']),
        ])
        return sum(lines.mapped('total'))

    def _sum_worked_days(self, code, from_date, to_date=None):
        to_date = to_date or fields.Date.today()
        lines = self.env['hr.payslip.worked_days'].search([
            ('employee_id', '=', self.employee_id.id),
            ('work_entry_type_id.code', '=', code),
            ('payslip_id.date_from', '>=', from_date),
            ('payslip_id.date_to', '<=', to_date),
            ('payslip_id.state', 'in', ['validated', 'paid']),
        ])
        return sum(lines.mapped('amount'))

    def _get_base_local_dict(self):
        return {
            'float_round': float_round,
            'float_compare': float_compare,
            'relativedelta': safe_eval_dateutil.relativedelta.relativedelta,
            'ceil': math.ceil,
            'floor': math.floor,
            'UserError': UserError,
            'date': safe_eval_datetime.date,
            'datetime': safe_eval_datetime.datetime,
            'defaultdict': defaultdict,
        }

    def _get_localdict(self):
        self.ensure_one()
        rules = PayrollDict(lambda: dict(total=0.0, amount=0.0, quantity=0.0, rate=0.0))
        # Refunds carry negative worked days; inputs are reverted here so that
        # every rule naturally produces the opposite of the original payslip.
        sign = -1 if self.credit_note else 1
        return {
            **self._get_base_local_dict(),
            'categories': PayrollDict(float),
            'rules': rules,
            'result_rules': rules,
            'payslip': self,
            'employee': self.employee_id,
            'version': self.version_id,
            'contract': self.version_id,
            'worked_days': PayrollDict(
                lambda: self.env['hr.payslip.worked_days'],
                {line.code: line for line in self.worked_days_line_ids if line.code}),
            'inputs': PayrollDict(
                lambda: PayslipInputSum(self.env['hr.payslip.input']),
                {code: PayslipInputSum(lines, sign) for code, lines in self.input_line_ids.grouped('code').items() if code}),
        }

    def _get_payslip_line_total(self, amount, quantity, rate):
        return self.currency_id.round(amount * quantity * rate / 100.0)

    def _get_payslip_lines(self):
        self.ensure_one()
        localdict = self._get_localdict()
        rules_dict = localdict['rules']
        result = {}
        rules = self.struct_id.rule_ids.filtered('active').sorted(lambda r: (r.sequence, r.id))
        for rule in rules:
            localdict.update({
                'result': None,
                'result_qty': 1.0,
                'result_rate': 100.0,
                'result_name': False,
            })
            if not rule._satisfy_condition(localdict):
                continue
            amount, qty, rate = rule._compute_rule(localdict)
            previous_amount = localdict.get(rule.code, 0.0) if rule.code in result else 0.0
            total = self._get_payslip_line_total(amount, qty, rate)
            localdict[rule.code] = total
            rules_dict[rule.code] = {'total': total, 'amount': amount, 'quantity': qty, 'rate': rate}
            rule.category_id._sum_salary_rule_category(localdict, total - previous_amount)
            result[rule.code] = {
                'sequence': rule.sequence,
                'code': rule.code,
                'name': localdict['result_name'] or rule.name,
                'salary_rule_id': rule.id,
                'version_id': self.version_id.id,
                'employee_id': self.employee_id.id,
                'amount': amount,
                'quantity': qty,
                'rate': rate,
                'total': total,
                'slip_id': self.id,
            }
        return list(result.values())

    def compute_sheet(self):
        payslips = self.filtered(lambda slip: slip.state == 'draft')
        if not payslips:
            return True
        for slip in payslips:
            if not slip.version_id:
                raise UserError(self.env._("There is no contract for %(employee)s during the period %(period)s.",
                                           employee=slip.employee_id.name, period=slip._get_period_name()))
            if not slip.struct_id:
                raise UserError(self.env._("No salary structure is set on payslip %s.", slip.name))
        payslips._fill_missing_worked_days()
        # proration settings may have changed since the worked days were computed
        payslips.filtered(lambda s: not s.credit_note).worked_days_line_ids._compute_amount()
        payslips._refresh_salary_attachment_inputs()
        payslips.line_ids.unlink()
        sequence = self.env['ir.sequence']
        lines_vals = []
        for slip in payslips:
            if not slip.number:
                slip.number = sequence.next_by_code('salary.slip.refund' if slip.credit_note else 'salary.slip')
            lines_vals += slip._get_payslip_lines()
        self.env['hr.payslip.line'].create(lines_vals)
        payslips.compute_date = fields.Date.today()
        return True

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        # Work entries must exist before the worked days are computed.
        self._generate_work_entries_before_create(vals_list)
        payslips = super().create(vals_list)
        # The form computes the worked days before saving, when the work entries of
        # the period may not exist yet: fill them now that they have been generated.
        payslips._fill_missing_worked_days()
        return payslips

    def _fill_missing_worked_days(self):
        """Build the worked days of draft payslips that have none, generating the
        missing work entries first. Worked days edited by hand are kept."""
        slips = self.filtered(lambda s: (
            s.state == 'draft' and not s.credit_note and s.version_id
            and s.struct_id.use_worked_day_lines and not s.worked_days_line_ids
        ))
        if slips:
            slips._generate_missing_work_entries()
            slips._compute_worked_days_line_ids()

    @api.model
    def _generate_work_entries_before_create(self, vals_list):
        periods = defaultdict(list)
        for vals in vals_list:
            if vals.get('employee_id') and vals.get('date_from'):
                date_from = fields.Date.to_date(vals['date_from'])
                date_to = fields.Date.to_date(vals.get('date_to'))
                if not date_to:
                    employee = self.env['hr.employee'].sudo().browse(vals['employee_id'])
                    schedule = employee._get_version(date_from).schedule_pay or 'monthly'
                    date_to = self.env['hr.payroll.structure.type']._get_schedule_period_end(schedule, date_from)
                periods[(date_from, date_to)].append(vals['employee_id'])
        for (date_from, date_to), employee_ids in periods.items():
            employees = self.env['hr.employee'].sudo().browse(employee_ids)
            employees._get_versions_with_contract_overlap_with_period(date_from, date_to) \
                .generate_work_entries(date_from, date_to)

    @api.ondelete(at_uninstall=False)
    def _unlink_if_draft_or_cancel(self):
        if any(slip.state not in ('draft', 'cancel') for slip in self):
            raise UserError(self.env._('You cannot delete a payslip which is not draft or cancelled!'))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_refresh_from_work_entries(self):
        slips = self.filtered(lambda s: s.state == 'draft' and not s.credit_note)
        slips._generate_missing_work_entries()
        slips._compute_worked_days_line_ids()
        slips.compute_sheet()

    def _set_work_entries_state(self, state):
        for slip in self:
            domain = slip._get_work_entries_domain() & Domain(
                'state', 'in', ['draft'] if state == 'validated' else ['validated'])
            self.env['hr.work.entry'].sudo().search(domain).write({'state': state})

    def action_payslip_done(self):
        invalid = self.filtered(lambda s: s.state != 'draft')
        if invalid:
            raise UserError(self.env._("Only draft payslips can be validated."))
        for slip in self:
            if not slip.credit_note and slip._get_conflicting_work_entries():
                raise UserError(self.env._(
                    "Some work entries of %s are in conflict. Please solve them before validating the payslip.",
                    slip.employee_id.name))
        self.filtered(lambda s: not s.line_ids).compute_sheet()
        self.write({'state': 'validated'})
        self.filtered(lambda s: not s.credit_note)._set_work_entries_state('validated')
        attachments = self.input_line_ids.attachment_id
        attachments._update_state_after_payment()
        self.payslip_run_id._compute_state()
        if self.env.context.get('payslip_generate_pdf', True):
            self._generate_pdf()
        return True

    def action_payslip_paid(self):
        if any(slip.state != 'validated' for slip in self):
            raise UserError(self.env._('Cannot mark payslip as paid if not confirmed.'))
        self.write({'state': 'paid', 'paid_date': fields.Date.today()})
        self.payslip_run_id._compute_state()

    def action_payslip_unpaid(self):
        if any(slip.state != 'paid' for slip in self):
            raise UserError(self.env._('Cannot mark payslip as unpaid if not paid.'))
        self.write({'state': 'validated', 'paid_date': False})
        self.payslip_run_id._compute_state()

    def action_payslip_cancel(self):
        if any(slip.state == 'paid' for slip in self):
            raise UserError(self.env._("You cannot cancel a paid payslip. Mark it as unpaid first."))
        validated = self.filtered(lambda s: s.state == 'validated')
        self.write({'state': 'cancel'})
        validated.filtered(lambda s: not s.credit_note)._set_work_entries_state('draft')
        validated.input_line_ids.attachment_id._update_state_after_payment()
        self.payslip_run_id._compute_state()

    def action_payslip_draft(self):
        if any(slip.state == 'paid' for slip in self):
            raise UserError(self.env._("You cannot reset a paid payslip to draft. Mark it as unpaid first."))
        validated = self.filtered(lambda s: s.state == 'validated')
        self.write({'state': 'draft'})
        validated.filtered(lambda s: not s.credit_note)._set_work_entries_state('draft')
        validated.input_line_ids.attachment_id._update_state_after_payment()
        self.payslip_run_id._compute_state()

    def refund_sheet(self):
        refunds = self.env['hr.payslip']
        for slip in self:
            if slip.state not in ('validated', 'paid'):
                raise UserError(self.env._("Only confirmed payslips can be refunded."))
            refund = slip.copy({
                'name': self.env._('Refund: %s', slip.name),
                'credit_note': True,
                'origin_payslip_id': slip.id,
                'payslip_run_id': False,
                'date_to': slip.date_to,
                'version_id': slip.version_id.id,
                'struct_id': slip.struct_id.id,
            })
            for wd in refund.worked_days_line_ids:
                wd.write({
                    'number_of_hours': -wd.number_of_hours,
                    'number_of_days': -wd.number_of_days,
                    'amount': -wd.amount,
                })
            self.env['hr.payslip.line'].create([{
                'sequence': line.sequence,
                'code': line.code,
                'name': line.name,
                'salary_rule_id': line.salary_rule_id.id,
                'version_id': line.version_id.id,
                'employee_id': line.employee_id.id,
                'amount': -line.amount,
                'quantity': line.quantity,
                'rate': line.rate,
                'total': -line.total,
                'slip_id': refund.id,
            } for line in slip.line_ids])
            refund.number = self.env['ir.sequence'].next_by_code('salary.slip.refund')
            slip.message_post(body=self.env._("A refund has been created: %s", refund._get_html_link()))
            refunds |= refund
        return {
            'name': self.env._("Refund Payslip"),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('id', 'in', refunds.ids)],
        }

    def action_open_refunds(self):
        self.ensure_one()
        return {
            'name': self.env._("Refunds"),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip',
            'view_mode': 'list,form',
            'domain': [('origin_payslip_id', '=', self.id)],
        }

    def action_open_work_entries(self):
        self.ensure_one()
        return {
            'name': self.env._("Work Entries"),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.work.entry',
            'view_mode': 'list,calendar,pivot,form',
            'domain': list(self._get_work_entries_domain()),
            'context': {'default_employee_id': self.employee_id.id, 'initial_date': self.date_from},
        }

    def action_open_salary_attachments(self):
        self.ensure_one()
        return {
            'name': self.env._("Salary Attachments"),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.salary.attachment',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self._get_active_salary_attachments().ids)],
            'context': {'default_employee_id': self.employee_id.id},
        }

    def action_print_payslip(self):
        return self.env.ref('jkm_hr_payroll.action_report_payslip').report_action(self)

    def _get_report(self):
        self.ensure_one()
        return self.struct_id.report_id or self.env.ref('jkm_hr_payroll.action_report_payslip')

    def _generate_pdf(self):
        """Attach the PDF of each confirmed payslip to its chatter."""
        for slip in self:
            report = slip._get_report()
            try:
                pdf_content, _type = self.env['ir.actions.report'].sudo()._render_qweb_pdf(report, slip.ids)
            except Exception:  # noqa: BLE001 - wkhtmltopdf may be missing in some environments
                continue
            filename = '%s.pdf' % (slip.number or slip.name).replace('/', '_')
            self.env['ir.attachment'].sudo().create({
                'name': filename,
                'type': 'binary',
                'datas': base64.b64encode(pdf_content),
                'res_model': slip._name,
                'res_id': slip.id,
                'mimetype': 'application/pdf',
            })

    def action_payslip_send(self):
        self.ensure_one()
        template = self.env.ref('jkm_hr_payroll.mail_template_new_payslip', raise_if_not_found=False)
        return {
            'name': self.env._('Send Payslip'),
            'type': 'ir.actions.act_window',
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_model': 'hr.payslip',
                'default_res_ids': self.ids,
                'default_template_id': template.id if template else False,
                'default_composition_mode': 'comment',
                'default_email_layout_xmlid': 'mail.mail_notification_light',
            },
        }

    # ------------------------------------------------------------------
    # Helpers for reports
    # ------------------------------------------------------------------

    def _get_lines_to_print(self):
        self.ensure_one()
        lines = self.line_ids.filtered('appears_on_payslip')
        if self.struct_id.hide_basic_on_pdf:
            lines = lines.filtered(lambda line: line.code != 'BASIC')
        return lines

