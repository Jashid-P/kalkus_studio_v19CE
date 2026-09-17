# -*- coding: utf-8 -*-
"""Handlers for reports whose lines cannot be written as static definitions.

A general ledger has one line per account and an aged balance one per partner,
so their lines only exist at render time. Each handler exposes
``_dynamic_lines_generator(report, options, totals_by_group)`` and returns the
same flat line dictionaries a static report produces.
"""

from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.fields import Domain


class AccountReportHandlerMixin(models.AbstractModel):
    _name = 'account.report.handler.mixin'
    _description = "Common helpers for dynamic accounting reports"

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @api.model
    def _column_groups(self, options):
        return list(dict.fromkeys(column['column_group_key'] for column in options['columns']))

    @api.model
    def _group_dates(self, report, options, column_group_key):
        group = options['column_groups'][column_group_key]
        return fields.Date.to_date(group['date_from']), fields.Date.to_date(group['date_to'])

    @api.model
    def _make_line(self, report, options, line_id, name, values, level=1, **kwargs):
        """Assemble a line dict, pulling each column's figure out of ``values``.

        ``values`` is keyed by ``(column_group_key, expression_label)``.
        """
        columns = []
        for column in options['columns']:
            value = values.get((column['column_group_key'], column['expression_label']))
            columns.append({
                'name': report._format_value(value, column['figure_type'], column['blank_if_zero']),
                'no_format': value,
                'figure_type': column['figure_type'],
                'expression_label': column['expression_label'],
                'column_group_key': column['column_group_key'],
                'auditable': True,
            })
        line = {
            'id': line_id,
            'name': name,
            'level': level,
            'columns': columns,
            'unfoldable': False,
            'unfolded': False,
            'parent_id': None,
            'caret_options': False,
            'class': '',
        }
        line.update(kwargs)
        return line

    @api.model
    def _wrap_in_report_section(self, report, options, rows):
        """Put a report's rows under a heading named after the report.

        The rows below carry their own totals - per account, per partner - so no
        grand total is appended here.
        """
        root_id = report._build_line_id([('section', None, 0)])
        heading = self._make_line(
            report, options, root_id, report.name, {}, level=0,
            unfoldable=False, unfolded=True,
        )
        for row in rows:
            row['parent_id'] = row.get('parent_id') or root_id
            row['level'] = (row.get('level') or 1) + 1
        return [heading] + rows

    @api.model
    def _is_unfolded(self, options, line_id):
        return options.get('unfold_all') or line_id in options.get('unfolded_lines', [])


class AccountGeneralLedgerHandler(models.AbstractModel):
    _name = 'account.general.ledger.report.handler'
    _inherit = 'account.report.handler.mixin'
    _description = "General Ledger Report Handler"

    def _dynamic_lines_generator(self, report, options, totals_by_group):
        lines = []

        account_values = self._compute_account_values(report, options)
        accounts = self.env['account.account'].browse(list(account_values)).sorted(lambda a: (a.code or '', a.id))

        for account in accounts:
            values = account_values[account.id]
            if all(self._is_blank(value) for value in values.values()):
                continue
            line_id = report._build_line_id([(None, 'account.account', account.id)])
            unfolded = self._is_unfolded(options, line_id)
            lines.append(self._make_line(
                report, options, line_id,
                '%s %s' % (account.code or '', account.name),
                values,
                level=1,
                unfoldable=True,
                unfolded=unfolded,
                caret_options='account.account',
            ))
            if unfolded:
                lines.extend(self._account_move_lines(report, options, account, line_id, values))

        return self._wrap_in_report_section(report, options, lines)

    @api.model
    def _is_blank(self, value):
        return not value

    def _compute_account_values(self, report, options):
        """Initial balance, period movements and closing balance per account."""
        values = defaultdict(dict)
        for column_group_key in self._column_groups(options):
            date_from, date_to = self._group_dates(report, options, column_group_key)

            # Opening position: everything strictly before the period start.
            initial_domain = report._get_base_domain(options, 'to_beginning_of_period', column_group_key)
            for account, balance in self.env['account.move.line']._read_group(
                initial_domain, groupby=['account_id'], aggregates=['balance:sum'],
            ):
                values[account.id][(column_group_key, 'initial_balance')] = balance

            period_domain = report._get_base_domain(options, 'strict_range', column_group_key)
            for account, debit, credit, balance in self.env['account.move.line']._read_group(
                period_domain, groupby=['account_id'], aggregates=['debit:sum', 'credit:sum', 'balance:sum'],
            ):
                values[account.id][(column_group_key, 'debit')] = debit
                values[account.id][(column_group_key, 'credit')] = credit
                values[account.id][(column_group_key, 'balance')] = balance

            for account_id, account_values in values.items():
                initial = account_values.get((column_group_key, 'initial_balance'), 0.0)
                movement = account_values.get((column_group_key, 'balance'), 0.0)
                account_values[(column_group_key, 'end_balance')] = initial + movement
        return values

    def _account_move_lines(self, report, options, account, parent_line_id, account_values=None):
        """The journal items behind one account, opening on the balance brought forward.

        A ledger is read downwards: it opens on the opening balance and runs the
        period's movements, accumulating as it goes. Showing each item's own
        balance instead would leave the reader to add them up. The account row
        above already carries the totals, so none is repeated at the end.
        """
        lines = []
        column_group_key = self._column_groups(options)[0]
        base_id = report._parse_line_id(parent_line_id)

        opening = (account_values or {}).get((column_group_key, 'initial_balance'), 0.0)

        # Opening position, only where there is one to carry forward.
        if not self.env.company.currency_id.is_zero(opening):
            lines.append(self._make_line(
                report, options,
                report._build_line_id(base_id + [('initial', None, 0)]),
                _("Initial Balance"),
                {
                    (column_group_key, 'debit'): opening if opening > 0 else 0.0,
                    (column_group_key, 'credit'): -opening if opening < 0 else 0.0,
                    (column_group_key, 'end_balance'): opening,
                },
                level=3,
                parent_id=parent_line_id,
            ))

        domain = report._get_base_domain(options, 'strict_range', column_group_key) \
            & Domain('account_id', '=', account.id)
        limit = report.load_more_limit or 80
        move_lines = self.env['account.move.line'].search(domain, order='date, move_name, id', limit=limit)

        running = opening
        for move_line in move_lines:
            running += move_line.balance
            values = {
                (column_group_key, 'debit'): move_line.debit,
                (column_group_key, 'credit'): move_line.credit,
                (column_group_key, 'end_balance'): running,
                (column_group_key, 'date'): move_line.date,
                (column_group_key, 'partner_name'): move_line.partner_id.display_name or '',
            }
            lines.append(self._make_line(
                report, options,
                report._build_line_id(base_id + [(None, 'account.move.line', move_line.id)]),
                '%s %s' % (move_line.move_id.name or '', move_line.name or ''),
                values,
                level=3,
                parent_id=parent_line_id,
                caret_options='account.move.line',
            ))

        return lines


class AccountTrialBalanceHandler(models.AbstractModel):
    _name = 'account.trial.balance.report.handler'
    _inherit = 'account.report.handler.mixin'
    _description = "Trial Balance Report Handler"

    def _dynamic_lines_generator(self, report, options, totals_by_group):
        lines = []
        values_by_account = defaultdict(dict)

        for column_group_key in self._column_groups(options):
            initial_domain = report._get_base_domain(options, 'to_beginning_of_period', column_group_key)
            for account, balance in self.env['account.move.line']._read_group(
                initial_domain, groupby=['account_id'], aggregates=['balance:sum'],
            ):
                values_by_account[account.id][(column_group_key, 'initial_balance')] = balance

            period_domain = report._get_base_domain(options, 'strict_range', column_group_key)
            for account, debit, credit in self.env['account.move.line']._read_group(
                period_domain, groupby=['account_id'], aggregates=['debit:sum', 'credit:sum'],
            ):
                values_by_account[account.id][(column_group_key, 'debit')] = debit
                values_by_account[account.id][(column_group_key, 'credit')] = credit

            for account_values in values_by_account.values():
                # An account with no opening position still has one: nil. Leaving
                # the key absent would render a blank cell where a trial balance
                # is expected to show 0.00.
                for label in ('initial_balance', 'debit', 'credit'):
                    account_values.setdefault((column_group_key, label), 0.0)
                account_values[(column_group_key, 'end_balance')] = (
                    account_values[(column_group_key, 'initial_balance')]
                    + account_values[(column_group_key, 'debit')]
                    - account_values[(column_group_key, 'credit')]
                )

        accounts = self.env['account.account'].browse(list(values_by_account))
        accounts = accounts.filtered(
            lambda account: any(values_by_account[account.id].values())
        )

        # Accounts are read against their chart group, so the trial balance is
        # organised the same way the chart of accounts is.
        by_group = defaultdict(lambda: self.env['account.account'])
        for account in accounts:
            by_group[account.group_id] |= account

        def group_sort_key(group):
            # Ungrouped accounts collect at the end under a single heading.
            return (1, '') if not group else (0, group.code_prefix_start or group.name or '')

        for group in sorted(by_group, key=group_sort_key):
            group_accounts = by_group[group].sorted(lambda a: (a.code or '', a.id))
            group_id = report._build_line_id([
                ('group', 'account.group', group.id if group else 0),
            ])
            group_totals = defaultdict(float)
            account_lines = []

            for account in group_accounts:
                values = values_by_account[account.id]
                account_lines.append(self._make_line(
                    report, options,
                    report._build_line_id([
                        ('group', 'account.group', group.id if group else 0),
                        (None, 'account.account', account.id),
                    ]),
                    '%s %s' % (account.code or '', account.name),
                    values,
                    level=2,
                    parent_id=group_id,
                    caret_options='account.account',
                ))
                for key, value in values.items():
                    group_totals[key] += value or 0.0

            unfolded = self._is_unfolded(options, group_id) or not group
            lines.append(self._make_line(
                report, options, group_id,
                group.display_name if group else _("(No Group)"),
                dict(group_totals),
                level=1,
                unfoldable=True,
                unfolded=unfolded,
            ))
            if unfolded:
                lines.extend(account_lines)

        return self._wrap_in_report_section(report, options, lines)


class AccountPartnerLedgerHandler(models.AbstractModel):
    _name = 'account.partner.ledger.report.handler'
    _inherit = 'account.report.handler.mixin'
    _description = "Partner Ledger Report Handler"

    # Only what a partner actually owes or is owed belongs in a partner ledger.
    def _receivable_payable_domain(self):
        return Domain('account_id.account_type', 'in', ('asset_receivable', 'liability_payable'))

    def _dynamic_lines_generator(self, report, options, totals_by_group):
        lines = []
        values_by_partner = defaultdict(dict)
        scope = self._receivable_payable_domain()

        for column_group_key in self._column_groups(options):
            initial_domain = report._get_base_domain(options, 'to_beginning_of_period', column_group_key) & scope
            for partner, balance in self.env['account.move.line']._read_group(
                initial_domain, groupby=['partner_id'], aggregates=['balance:sum'],
            ):
                values_by_partner[partner.id][(column_group_key, 'initial_balance')] = balance

            period_domain = report._get_base_domain(options, 'strict_range', column_group_key) & scope
            for partner, debit, credit in self.env['account.move.line']._read_group(
                period_domain, groupby=['partner_id'], aggregates=['debit:sum', 'credit:sum'],
            ):
                values_by_partner[partner.id][(column_group_key, 'debit')] = debit
                values_by_partner[partner.id][(column_group_key, 'credit')] = credit

            for partner_values in values_by_partner.values():
                partner_values[(column_group_key, 'balance')] = (
                    partner_values.get((column_group_key, 'initial_balance'), 0.0)
                    + partner_values.get((column_group_key, 'debit'), 0.0)
                    - partner_values.get((column_group_key, 'credit'), 0.0)
                )

        partners = self.env['res.partner'].browse([pid for pid in values_by_partner if pid])
        for partner in partners.sorted(lambda p: p.display_name or ''):
            values = values_by_partner[partner.id]
            if all(not value for value in values.values()):
                continue

            line_id = report._build_line_id([(None, 'res.partner', partner.id)])
            unfolded = self._is_unfolded(options, line_id)
            lines.append(self._make_line(
                report, options, line_id, partner.display_name, values,
                level=1,
                unfoldable=True,
                unfolded=unfolded,
                caret_options='res.partner',
            ))

            # A partner's balance is only auditable if the entries behind it can
            # be read, so the row expands into the items that make it up. The
            # partner row already carries the totals, so no subtotal is repeated
            # underneath.
            if unfolded:
                lines.extend(self._partner_move_lines(report, options, partner, line_id))

        return self._wrap_in_report_section(report, options, lines)

    def _partner_move_lines(self, report, options, partner, parent_line_id):
        """The journal items making up one partner's movement in the period."""
        lines = []
        column_group_key = self._column_groups(options)[0]
        domain = (
            report._get_base_domain(options, 'strict_range', column_group_key)
            & self._receivable_payable_domain()
            & Domain('partner_id', '=', partner.id)
        )
        limit = report.load_more_limit or 80
        move_lines = self.env['account.move.line'].search(domain, order='date, move_name, id', limit=limit)

        # Balance runs forward from the opening position, the way a ledger reads.
        opening_domain = (
            report._get_base_domain(options, 'to_beginning_of_period', column_group_key)
            & self._receivable_payable_domain()
            & Domain('partner_id', '=', partner.id)
        )
        opening = self.env['account.move.line']._read_group(opening_domain, aggregates=['balance:sum'])
        running = opening[0][0] or 0.0

        for move_line in move_lines:
            running += move_line.balance
            values = {
                (column_group_key, 'journal_code'): move_line.journal_id.code or '',
                (column_group_key, 'account_code'): move_line.account_id.code or '',
                (column_group_key, 'invoice_date'): move_line.move_id.invoice_date or move_line.date,
                (column_group_key, 'date_maturity'): move_line.date_maturity or '',
                (column_group_key, 'matching_number'): move_line.matching_number or '',
                (column_group_key, 'debit'): move_line.debit,
                (column_group_key, 'credit'): move_line.credit,
                (column_group_key, 'amount_currency'): move_line.amount_currency,
                (column_group_key, 'balance'): running,
            }
            lines.append(self._make_line(
                report, options,
                report._build_line_id([
                    (None, 'res.partner', partner.id),
                    (None, 'account.move.line', move_line.id),
                ]),
                '%s %s' % (move_line.move_id.name or '', move_line.name or ''),
                values,
                level=3,
                parent_id=parent_line_id,
                caret_options='account.move.line',
            ))
        return lines


class AccountAgedPartnerBalanceHandler(models.AbstractModel):
    _name = 'account.aged.partner.balance.report.handler'
    _inherit = 'account.report.handler.mixin'
    _description = "Aged Partner Balance Report Handler"

    # Days overdue, read against the report date.
    BUCKETS = (
        ('period0', 30),
        ('period1', 60),
        ('period2', 90),
        ('period3', 120),
        ('period4', None),
    )

    # Overridden by the payable variant.
    def _get_account_types(self):
        return ('asset_receivable',)

    def _bucket_for(self, days_overdue):
        """Which ageing column an amount falls into.

        Anything not yet due sits in 'at_date': it is outstanding at the report
        date but not late, so it does not belong in an overdue bucket.
        """
        if days_overdue <= 0:
            return 'at_date'
        for name, limit in self.BUCKETS:
            if limit is None or days_overdue <= limit:
                return name
        return self.BUCKETS[-1][0]

    def _open_items_domain(self, report, options, column_group_key):
        return (
            report._get_base_domain(options, 'from_beginning', column_group_key)
            & Domain('account_id.account_type', 'in', self._get_account_types())
            & Domain('full_reconcile_id', '=', False)
            & Domain('balance', '!=', 0)
        )

    def _dynamic_lines_generator(self, report, options, totals_by_group):
        lines = []
        values_by_partner = defaultdict(lambda: defaultdict(float))
        items_by_partner = defaultdict(list)

        for column_group_key in self._column_groups(options):
            _date_from, date_to = self._group_dates(report, options, column_group_key)
            move_lines = self.env['account.move.line'].search(
                self._open_items_domain(report, options, column_group_key),
                order='date_maturity, date, id',
            )

            for move_line in move_lines:
                # Residual, so partially paid invoices age only by what is left.
                residual = move_line.amount_residual
                if not residual:
                    continue
                due_date = move_line.date_maturity or move_line.date
                bucket = self._bucket_for((date_to - due_date).days)

                partner_values = values_by_partner[move_line.partner_id.id]
                partner_values[(column_group_key, bucket)] += residual
                partner_values[(column_group_key, 'total')] += residual

                items_by_partner[move_line.partner_id.id].append((move_line, column_group_key, bucket, residual))

        partners = self.env['res.partner'].browse([pid for pid in values_by_partner if pid])
        for partner in partners.sorted(lambda p: p.display_name or ''):
            line_id = report._build_line_id([(None, 'res.partner', partner.id)])
            unfolded = self._is_unfolded(options, line_id)
            lines.append(self._make_line(
                report, options, line_id,
                partner.display_name,
                dict(values_by_partner[partner.id]),
                level=1,
                unfoldable=True,
                unfolded=unfolded,
                caret_options='res.partner',
            ))
            # A partner's ageing is only checkable against the invoices behind
            # it, so the row opens onto them.
            if unfolded:
                lines.extend(self._partner_open_items(report, options, partner, line_id, items_by_partner[partner.id]))

        return self._wrap_in_report_section(report, options, lines)

    def _partner_open_items(self, report, options, partner, parent_line_id, items):
        """One line per outstanding entry, placed in the bucket it has reached."""
        lines = []
        for move_line, column_group_key, bucket, residual in items:
            values = {
                (column_group_key, 'invoice_date'): move_line.move_id.invoice_date or move_line.date,
                (column_group_key, bucket): residual,
            }
            lines.append(self._make_line(
                report, options,
                report._build_line_id([
                    (None, 'res.partner', partner.id),
                    (None, 'account.move.line', move_line.id),
                ]),
                move_line.move_id.name or move_line.name or '',
                values,
                level=2,
                parent_id=parent_line_id,
                caret_options='account.move.line',
            ))
        return lines


class AccountAgedPayableHandler(models.AbstractModel):
    _name = 'account.aged.payable.report.handler'
    _inherit = 'account.aged.partner.balance.report.handler'
    _description = "Aged Payable Report Handler"

    def _get_account_types(self):
        return ('liability_payable',)


class AccountCashFlowHandler(models.AbstractModel):
    """A company-neutral cash movement report.

    Odoo Community already records the authoritative cash journal items.  This
    handler reports their posted movement and closing balance without making
    assumptions about a country's statutory cash-flow classification. Country
    modules can add a richer classification later through report definitions.
    """

    _name = 'account.cash.flow.report.handler'
    _inherit = 'account.report.handler.mixin'
    _description = "Cash Flow Report Handler"

    # What counts as cash: the balance the statement opens and closes on.
    CASH_TYPES = ('asset_cash', 'liability_credit_card')

    # Where a movement is classified, read from the account on the other side of
    # the entry. Cash never explains itself - what it was for is on the
    # counterpart line.
    OPERATING_TYPES = (
        'asset_receivable', 'liability_payable',
        'income', 'income_other', 'expense', 'expense_direct_cost',
        'expense_depreciation', 'expense_other',
    )
    INVESTING_TYPES = ('asset_fixed', 'asset_non_current')
    FINANCING_TYPES = ('liability_non_current', 'equity', 'equity_unaffected')

    def _cash_domain(self, report, options, date_scope, column_group_key):
        return (
            report._get_base_domain(options, date_scope, column_group_key)
            & Domain('account_id.account_type', 'in', self.CASH_TYPES)
        )

    def _classify(self, account):
        """Section and sub-line an entry's counterpart belongs to."""
        account_type = account.account_type
        if account_type in ('asset_receivable', 'liability_payable'):
            # Money moved against a receivable or payable with no profit impact
            # is an advance: paid or received before the invoice catches up.
            return 'operating', 'advance'
        if account_type in self.OPERATING_TYPES:
            return 'operating', 'trading'
        if account_type in self.INVESTING_TYPES:
            return 'investing', 'flow'
        if account_type in self.FINANCING_TYPES:
            return 'financing', 'flow'
        return 'unclassified', 'flow'

    def _dynamic_lines_generator(self, report, options, totals_by_group):
        column_group_key = self._column_groups(options)[0]
        buckets = defaultdict(float)

        opening = self._cash_balance(report, options, 'to_beginning_of_period', column_group_key)
        closing = self._cash_balance(report, options, 'from_beginning', column_group_key)

        cash_lines = self.env['account.move.line'].search(
            self._cash_domain(report, options, 'strict_range', column_group_key)
        )
        for cash_line in cash_lines:
            counterparts = cash_line.move_id.line_ids.filtered(
                lambda line: line.account_id.account_type not in self.CASH_TYPES
            )
            total_weight = sum(abs(line.balance) for line in counterparts)
            if not counterparts or not total_weight:
                buckets[('unclassified', 'flow', cash_line.balance > 0)] += cash_line.balance
                continue
            # A payment can settle several things at once, so the cash is split
            # across its counterparts rather than attributed to the first one.
            for counterpart in counterparts:
                share = cash_line.balance * (abs(counterpart.balance) / total_weight)
                section, kind = self._classify(counterpart.account_id)
                buckets[(section, kind, share > 0)] += share

        def value(section, kind, inflow):
            return {(column_group_key, 'balance'): buckets.get((section, kind, inflow), 0.0)}

        def band(key, name, amount, level=0):
            return self._make_line(
                report, options, report._build_line_id([(key, None, 0)]), name,
                {(column_group_key, 'balance'): amount}, level=level, **{'class': 'total'},
            )

        def row(key, name, section, kind, inflow, level=2):
            return self._make_line(
                report, options, report._build_line_id([(key, None, 0)]), name,
                value(section, kind, inflow), level=level,
            )

        def heading(key, name):
            return self._make_line(
                report, options, report._build_line_id([(key, None, 0)]), name, {},
                level=1, **{'class': 'subtotal'},
            )

        lines = [
            band('opening', _("Cash and cash equivalents, beginning of period"), opening),
            band('net', _("Net increase in cash and cash equivalents"), closing - opening),

            heading('operating', _("Cash flows from operating activities")),
            row('op_adv_in', _("Advance Payments received from customers"), 'operating', 'advance', True),
            row('op_in', _("Cash received from operating activities"), 'operating', 'trading', True),
            row('op_adv_out', _("Advance payments made to suppliers"), 'operating', 'advance', False),
            row('op_out', _("Cash paid for operating activities"), 'operating', 'trading', False),

            heading('investing', _("Cash flows from investing & extraordinary activities")),
            row('inv_in', _("Cash in"), 'investing', 'flow', True),
            row('inv_out', _("Cash out"), 'investing', 'flow', False),

            heading('financing', _("Cash flows from financing activities")),
            row('fin_in', _("Cash in"), 'financing', 'flow', True),
            row('fin_out', _("Cash out"), 'financing', 'flow', False),

            heading('unclassified', _("Cash flows from unclassified activities")),
            row('unc_in', _("Cash in"), 'unclassified', 'flow', True),
            row('unc_out', _("Cash out"), 'unclassified', 'flow', False),

            band('closing', _("Cash and cash equivalents, closing balance"), closing),
        ]
        return lines

    def _cash_balance(self, report, options, date_scope, column_group_key):
        aggregated = self.env['account.move.line']._read_group(
            self._cash_domain(report, options, date_scope, column_group_key),
            aggregates=['balance:sum'],
        )
        return aggregated[0][0] or 0.0


class AccountTaxAuditHandler(models.AbstractModel):
    """Generic tax audit report that works with any country localization."""

    _name = 'account.tax.audit.report.handler'
    _inherit = 'account.report.handler.mixin'
    _description = "Tax Report Handler"

    # Sales tax is collected and sits as a credit; purchase tax is paid and sits
    # as a debit. A return reads both as positive amounts, so the sign is taken
    # from what the tax is for rather than from the ledger.
    SECTIONS = (
        ('sale', "Sales", -1),
        ('purchase', "Purchases", 1),
    )

    def _dynamic_lines_generator(self, report, options, totals_by_group):
        lines = []
        column_group_key = self._column_groups(options)[0]

        domain = (
            report._get_base_domain(options, 'strict_range', column_group_key)
            & Domain('tax_line_id', '!=', False)
        )
        grouped = self.env['account.move.line']._read_group(
            domain, groupby=['tax_line_id'], aggregates=['tax_base_amount:sum', 'balance:sum'],
        )
        by_tax = {tax: (base, balance) for tax, base, balance in grouped}

        for type_tax_use, section_name, sign in self.SECTIONS:
            taxes = [tax for tax in by_tax if tax.type_tax_use == type_tax_use]
            if not taxes:
                continue
            taxes.sort(key=lambda tax: (tax.sequence, tax.name or '', tax.id))

            section_net = section_tax = 0.0
            tax_lines = []
            for tax in taxes:
                base, balance = by_tax[tax]
                net = sign * (base or 0.0)
                amount = sign * (balance or 0.0)
                section_net += net
                section_tax += amount
                tax_lines.append(self._make_line(
                    report, options,
                    report._build_line_id([
                        ('section', None, 0), (None, 'account.tax', tax.id),
                    ]),
                    tax.display_name,
                    {
                        (column_group_key, 'net'): net,
                        (column_group_key, 'tax'): amount,
                    },
                    level=2,
                    caret_options='account.tax',
                ))

            # The section heading states the tax at stake; the net belongs to
            # the individual rates, which can differ within one section.
            lines.append(self._make_line(
                report, options,
                report._build_line_id([('section', None, 0), (type_tax_use, None, 0)]),
                section_name,
                {(column_group_key, 'tax'): section_tax},
                level=0, **{'class': 'total'},
            ))
            lines.extend(tax_lines)
            lines.append(self._make_line(
                report, options,
                report._build_line_id([('section', None, 0), (type_tax_use, 'total', 0)]),
                _("Total %(section)s", section=section_name),
                {(column_group_key, 'tax'): section_tax},
                level=1, **{'class': 'subtotal'},
            ))

        return lines
