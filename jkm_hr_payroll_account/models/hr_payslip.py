# -*- coding: utf-8 -*-
from collections import defaultdict

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import date_utils


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    date = fields.Date(
        'Accounting Date', copy=False,
        help="Date of the journal entry. Defaults to the last day of the payslip month.")
    journal_id = fields.Many2one(
        'account.journal', 'Salary Journal', compute='_compute_journal_id', compute_sudo=True)
    move_id = fields.Many2one('account.move', 'Accounting Entry', readonly=True, copy=False, index='btree_not_null')
    move_state = fields.Selection(related='move_id.state', string='Entry Status')
    batch_payroll_move_lines = fields.Boolean(related='company_id.batch_payroll_move_lines')
    net_move_line_ids = fields.Many2many('account.move.line', compute='_compute_net_move_line_ids', compute_sudo=True)
    has_net_to_pay = fields.Boolean(compute='_compute_net_move_line_ids', compute_sudo=True)

    @api.depends('struct_id', 'company_id')
    def _compute_journal_id(self):
        for slip in self:
            slip.journal_id = slip.struct_id.with_company(slip.company_id).journal_id

    @api.depends('move_id.line_ids.amount_residual', 'move_id.state')
    def _compute_net_move_line_ids(self):
        for slip in self.sudo():
            lines = slip._get_net_move_lines()
            slip.net_move_line_ids = lines
            slip.has_net_to_pay = slip.move_id.state == 'posted' and any(
                not line.company_currency_id.is_zero(line.amount_residual) for line in lines)

    def _get_net_move_lines(self):
        """Journal items holding the net salary owed to the employee."""
        self.ensure_one()
        partner = self.employee_id.work_contact_id
        if not self.move_id or not partner:
            return self.env['account.move.line']
        return self.move_id.line_ids.filtered(
            lambda line: line.partner_id == partner and line.account_id.reconcile)

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------

    def action_payslip_done(self):
        res = super().action_payslip_done()
        self._action_create_account_move()
        return res

    def action_payslip_cancel(self):
        self._remove_account_moves()
        return super().action_payslip_cancel()

    def action_payslip_draft(self):
        self._remove_account_moves()
        return super().action_payslip_draft()

    def _remove_account_moves(self):
        moves = self.sudo().move_id
        if not moves:
            return
        shared = moves.payslip_ids - self.sudo()
        if shared:
            raise UserError(self.env._(
                "The journal entry %(move)s also contains the payslips of %(employees)s. "
                "Cancel or reset the whole batch instead.",
                move=moves[:1].display_name, employees=', '.join(shared.employee_id.mapped('name'))))
        self.write({'move_id': False})
        self.sudo().payslip_run_id.filtered(lambda run: run.move_id in moves).move_id = False
        moves._unlink_or_reverse()

    def _update_paid_state_from_accounting(self):
        """Mark the payslips paid once their net salary is reconciled, unpaid otherwise."""
        for slip in self.sudo():
            lines = slip._get_net_move_lines()
            if not lines or slip.move_id.state != 'posted':
                continue
            is_paid = all(line.company_currency_id.is_zero(line.amount_residual) for line in lines)
            if is_paid and slip.state == 'validated':
                slip.action_payslip_paid()
            elif not is_paid and slip.state == 'paid':
                slip.action_payslip_unpaid()

    # ------------------------------------------------------------------
    # Journal entries
    # ------------------------------------------------------------------

    def _get_accounting_date(self):
        self.ensure_one()
        return self.date or date_utils.end_of(self.date_to, 'month')

    def _action_create_account_move(self):
        slips = self | self.payslip_run_id.slip_ids
        slips = slips.filtered(lambda s: s.state == 'validated' and not s.move_id and s.journal_id)
        # In batch mode, wait until every payslip of a batch is validated.
        batch_companies = slips.company_id.filtered('batch_payroll_move_lines')
        if batch_companies:
            slips = slips.filtered(lambda s: (
                s.company_id not in batch_companies or not s.payslip_run_id
                or all(other.state != 'draft' for other in s.payslip_run_id.slip_ids)
            ))
        if not slips:
            return self.env['account.move']

        groups = defaultdict(lambda: self.env['hr.payslip'])
        for slip in slips:
            if slip.company_id.batch_payroll_move_lines:
                key = (slip.company_id, slip.journal_id, slip._get_accounting_date(), slip.payslip_run_id)
            else:
                key = (slip.company_id, slip.journal_id, slip._get_accounting_date(), slip)
            groups[key] |= slip

        moves = self.env['account.move']
        for (company, journal, date, _group), group_slips in groups.items():
            move = self.env['account.move'].with_company(company).sudo().create(
                group_slips._prepare_account_move_vals(journal, date))
            group_slips.write({'move_id': move.id, 'date': date})
            if company.batch_payroll_move_lines:
                group_slips.payslip_run_id.write({'move_id': move.id})
            moves |= move
        return moves

    def _prepare_account_move_vals(self, journal, date):
        currency = self.company_id.currency_id
        lines = []
        narration = Markup()
        for slip in self:
            lines += slip._prepare_move_lines_vals()
            narration += Markup('%s - %s<br/>') % (slip.number or slip.name, slip.employee_id.name)
        lines = self._merge_move_lines(lines)

        balance = currency.round(sum(line['debit'] - line['credit'] for line in lines))
        if not currency.is_zero(balance):
            account = journal.default_account_id
            if not account:
                raise UserError(self.env._(
                    "The journal entry of %(slips)s is not balanced (difference: %(amount)s). "
                    "Set accounts on the salary rules, or a default account on the journal %(journal)s "
                    "to book the difference.",
                    slips=', '.join(self.mapped('name')), amount=balance, journal=journal.display_name))
            lines.append({
                'name': self.env._('Adjustment Entry'),
                'account_id': account.id,
                'debit': -balance if balance < 0 else 0.0,
                'credit': balance if balance > 0 else 0.0,
                'partner_id': False,
            })

        slip_date_to = max(self.mapped('date_to'))
        ref = self[:1].number if len(self) == 1 else self.payslip_run_id[:1].name
        return {
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': date,
            'ref': ref or date_utils.end_of(slip_date_to, 'month').strftime('%B %Y'),
            'narration': narration,
            'line_ids': [(0, 0, vals) for vals in lines],
        }

    def _prepare_move_lines_vals(self):
        """Journal items of one payslip, before merging."""
        self.ensure_one()
        company = self.company_id
        currency = company.currency_id
        batch = company.batch_payroll_move_lines
        excluded_from_net = sum(
            line.total for line in self.line_ids
            if line.salary_rule_id.not_computed_in_net
        )
        vals_list = []
        for line in self.line_ids:
            rule = line.salary_rule_id.with_company(company)
            amount = line.total
            if line.category_id.code == 'NET':
                amount -= excluded_from_net
            amount = currency.round(amount)
            if currency.is_zero(amount):
                continue
            if rule.employee_move_line and not batch:
                partner = self.employee_id.work_contact_id
            else:
                partner = rule.partner_id
            name = line.name if rule.split_move_lines else rule.name
            analytic = self.version_id.analytic_distribution or rule.analytic_distribution
            for account, tags, sign in (
                (rule.account_debit, rule.debit_tag_ids, 1),
                (rule.account_credit, rule.credit_tag_ids, -1),
            ):
                if not account:
                    continue
                signed = amount * sign
                vals_list.append({
                    'name': name,
                    'account_id': account.id,
                    'partner_id': partner.id,
                    'debit': signed if signed > 0 else 0.0,
                    'credit': -signed if signed < 0 else 0.0,
                    'analytic_distribution': analytic if account.internal_group in ('income', 'expense') else False,
                    'tax_tag_ids': [(6, 0, tags.ids)] if tags else False,
                })
        return vals_list

    @api.model
    def _merge_move_lines(self, vals_list):
        """Merge the journal items sharing account, partner, label, analytic and side."""
        merged = {}
        for vals in vals_list:
            key = (
                vals['account_id'], vals['partner_id'], vals['name'],
                str(vals['analytic_distribution'] or ''), str(vals['tax_tag_ids'] or ''),
                'debit' if vals['debit'] else 'credit',
            )
            if key in merged:
                merged[key]['debit'] += vals['debit']
                merged[key]['credit'] += vals['credit']
            else:
                merged[key] = dict(vals)
        result = []
        for vals in merged.values():
            if not vals['analytic_distribution']:
                vals.pop('analytic_distribution')
            if not vals['tax_tag_ids']:
                vals.pop('tax_tag_ids')
            result.append(vals)
        return result

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_open_move(self):
        self.ensure_one()
        return {
            'name': self.env._('Journal Entry'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.move_id.id,
        }

    def action_register_payment(self):
        lines = self.sudo().net_move_line_ids.filtered(
            lambda line: not line.company_currency_id.is_zero(line.amount_residual))
        if not lines:
            raise UserError(self.env._(
                "There is no net salary to pay: post the journal entry first, and check that the Net "
                "salary rule has 'Set employee on account line' and a reconcilable credit account."))
        employee = self.employee_id[:1]
        return {
            'name': self.env._('Register Payment'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'active_model': 'account.move.line',
                'active_ids': lines.ids,
                'hr_payroll_payment_register': True,
                'default_partner_bank_id': employee.primary_bank_account_id.id if len(self) == 1 else False,
            },
        }
