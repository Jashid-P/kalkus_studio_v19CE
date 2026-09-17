# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestCommunityAccountingReports(AccountTestInvoicingCommon):
    """Check that the report engine produces correct figures, not just a payload."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env['account.report'])
        cls.bank_account = cls.company_data['default_account_assets']
        cls.revenue_account = cls.company_data['default_account_revenue']
        cls.expense_account = cls.company_data['default_account_expense']
        cls.receivable_account = cls.company_data['default_account_receivable']

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _post_entry(self, lines, date=None):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': date or self.today,
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': account.id, 'debit': debit, 'credit': credit, 'partner_id': partner.id if partner else False})
                for account, debit, credit, partner in lines
            ],
        })
        move.action_post()
        return move

    def _values_by_code(self, report, options=None):
        """Map each static report line's code to its first column value.

        Foldable lines are collapsed by default, so the report is unfolded here
        to make every line inspectable.
        """
        options = options or report._get_options({'unfold_all': True})
        lines = report._get_lines(options)
        result = {}
        for line in lines:
            report_line_id = line.get('report_line_id')
            if not report_line_id:
                continue
            code = self.env['account.report.line'].browse(report_line_id).code
            if code:
                result[code] = line['columns'][0]['no_format']
        return result

    # ------------------------------------------------------------------
    # Balance sheet
    # ------------------------------------------------------------------

    def test_balance_sheet_equation_holds(self):
        """Assets must equal liabilities plus equity after any posted entry."""
        self._post_entry([
            (self.bank_account, 1000.0, 0.0, None),
            (self.revenue_account, 0.0, 1000.0, None),
        ])
        report = self.env.ref('jkm_full_accounting.balance_sheet')
        values = self._values_by_code(report)

        self.assertAlmostEqual(values['BS_ASSETS'], 1000.0, places=2)
        # Revenue is unallocated until the year is closed, so it lands in equity.
        self.assertAlmostEqual(values['BS_CY_EARNINGS'], 1000.0, places=2)
        self.assertAlmostEqual(
            values['BS_ASSETS'], values['BS_LIAB'] + values['BS_EQUITY'], places=2,
            msg="Balance sheet does not balance: assets != liabilities + equity",
        )

    def test_balance_sheet_liabilities_are_positive(self):
        """Credit-balance accounts are reported as positive figures."""
        self._post_entry([
            (self.expense_account, 400.0, 0.0, None),
            (self.company_data['default_account_payable'], 0.0, 400.0, self.partner_a),
        ])
        values = self._values_by_code(self.env.ref('jkm_full_accounting.balance_sheet'))
        self.assertAlmostEqual(values['BS_PAY'], 400.0, places=2)
        self.assertAlmostEqual(
            values['BS_ASSETS'], values['BS_LIAB'] + values['BS_EQUITY'], places=2,
        )

    def test_balance_sheet_excludes_draft_entries_by_default(self):
        self.env['account.move'].create({
            'move_type': 'entry',
            'date': self.today,
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.bank_account.id, 'debit': 500.0, 'credit': 0.0}),
                (0, 0, {'account_id': self.revenue_account.id, 'debit': 0.0, 'credit': 500.0}),
            ],
        })  # left in draft on purpose
        report = self.env.ref('jkm_full_accounting.balance_sheet')
        self.assertAlmostEqual(self._values_by_code(report)['BS_ASSETS'], 0.0, places=2)

        with_draft = self._values_by_code(report, report._get_options({'all_entries': True, 'unfold_all': True}))
        self.assertAlmostEqual(with_draft['BS_ASSETS'], 500.0, places=2)

    # ------------------------------------------------------------------
    # Profit and loss
    # ------------------------------------------------------------------

    def test_profit_and_loss_net_profit(self):
        """Revenue is shown positive, costs subtract from it."""
        self._post_entry([
            (self.bank_account, 1000.0, 0.0, None),
            (self.revenue_account, 0.0, 1000.0, None),
        ])
        self._post_entry([
            (self.expense_account, 300.0, 0.0, None),
            (self.bank_account, 0.0, 300.0, None),
        ])
        values = self._values_by_code(self.env.ref('jkm_full_accounting.profit_and_loss'))
        self.assertAlmostEqual(values['PL_INCOME'], 1000.0, places=2)
        self.assertAlmostEqual(values['PL_EXPENSE'], 300.0, places=2)
        self.assertAlmostEqual(values['PL_NET'], 700.0, places=2)

    # ------------------------------------------------------------------
    # Dynamic reports
    # ------------------------------------------------------------------

    def test_general_ledger_account_movements(self):
        self._post_entry([
            (self.bank_account, 1000.0, 0.0, None),
            (self.revenue_account, 0.0, 1000.0, None),
        ])
        report = self.env.ref('jkm_full_accounting.general_ledger_report')
        options = report._get_options({})
        lines = report._get_lines(options)

        labels = [column['expression_label'] for column in options['columns']]
        bank_line = next(line for line in lines if line['name'].startswith(self.bank_account.code))
        values = dict(zip(labels, [column['no_format'] for column in bank_line['columns']]))
        self.assertAlmostEqual(values['debit'], 1000.0, places=2)
        self.assertAlmostEqual(values['credit'], 0.0, places=2)
        self.assertAlmostEqual(values['end_balance'], 1000.0, places=2)

    def test_trial_balance_debits_equal_credits(self):
        self._post_entry([
            (self.bank_account, 1000.0, 0.0, None),
            (self.revenue_account, 0.0, 1000.0, None),
        ])
        report = self.env.ref('jkm_full_accounting.trial_balance_report')
        options = report._get_options({})
        lines = report._get_lines(options)
        labels = [column['expression_label'] for column in options['columns']]

        account_rows = [l for l in lines if l.get('caret_options') == 'account.account']
        self.assertTrue(account_rows)
        summed = {label: 0.0 for label in labels}
        for row in account_rows:
            for label, column in zip(labels, row['columns']):
                summed[label] += column['no_format'] or 0.0
        self.assertAlmostEqual(summed['debit'], summed['credit'], places=2,
                               msg="Trial balance debits and credits differ")
        # Every entry balances, so the closing position across all accounts is nil.
        self.assertAlmostEqual(summed['end_balance'], 0.0, places=2)

    def test_aged_receivable_buckets_by_days_overdue(self):
        """An invoice 45 days past due belongs in the 31-60 bucket."""
        move = self._post_entry(
            [
                (self.receivable_account, 600.0, 0.0, self.partner_a),
                (self.revenue_account, 0.0, 600.0, None),
            ],
            date=self.today - timedelta(days=45),
        )
        move.line_ids.filtered(lambda l: l.account_id == self.receivable_account).write({
            'date_maturity': self.today - timedelta(days=45),
        })

        report = self.env.ref('jkm_full_accounting.aged_receivable_report')
        options = report._get_options({})
        lines = report._get_lines(options)
        labels = [column['expression_label'] for column in options['columns']]

        partner_line = next(line for line in lines if line['name'] == self.partner_a.display_name)
        values = dict(zip(labels, [column['no_format'] for column in partner_line['columns']]))
        self.assertAlmostEqual(values.get('period1') or 0.0, 600.0, places=2)
        self.assertAlmostEqual(values.get('total') or 0.0, 600.0, places=2)
        self.assertFalse(values.get('at_date'), "An overdue item must not sit in At Date")

    # ------------------------------------------------------------------
    # Payload contract
    # ------------------------------------------------------------------

    def test_all_reports_generate_payloads(self):
        reports = self.env['account.report'].search([
            ('id', 'in', [
                self.env.ref('jkm_full_accounting.%s' % xmlid).id
                for xmlid in (
                    'balance_sheet', 'profit_and_loss', 'general_ledger_report',
                    'trial_balance_report', 'partner_ledger_report',
                    'aged_receivable_report', 'aged_payable_report',
                )
            ]),
        ])
        for report in reports:
            payload = self.env['account.report'].get_report_data(report.id, {})
            self.assertEqual(payload['report']['id'], report.id)
            self.assertTrue(payload['options']['columns'])
            self.assertIsInstance(payload['lines'], list)

    def test_missing_report_is_rejected(self):
        with self.assertRaises(UserError):
            self.env['account.report'].get_report_data(0, {})


@tagged('post_install', '-at_install')
class TestAccountingApp(AccountTestInvoicingCommon):
    """The Accounting app layer: menu switch, fiscal years and lock dates."""

    def test_accounting_menu_replaces_invoicing(self):
        """All accounting sections hang off the new Accounting root."""
        accounting = self.env.ref('jkm_full_accounting.menu_accounting')
        invoicing = self.env.ref('account.menu_finance')

        self.assertFalse(accounting.parent_id, "Accounting must be a root menu")
        self.assertFalse(
            invoicing.child_id,
            "Invoicing should have no children left, so it stops being rendered",
        )
        moved = {
            'account.menu_board_journal_1',
            'account.menu_finance_receivables',
            'account.menu_finance_payables',
            'account.menu_finance_entries',
            'account.account_audit_menu',
            'account.menu_finance_reports',
            'account.menu_finance_configuration',
        }
        for xmlid in moved:
            self.assertEqual(
                self.env.ref(xmlid).parent_id, accounting,
                "%s was not moved under the Accounting menu" % xmlid,
            )

    def test_fiscal_year_record_overrides_computed_dates(self):
        """An explicit fiscal year wins over the company's closing day/month."""
        company = self.env.company
        anchor = fields.Date.to_date('2026-06-15')

        computed = company.compute_fiscalyear_dates(anchor)
        self.assertEqual(computed['date_from'], fields.Date.to_date('2026-01-01'))
        self.assertEqual(computed['date_to'], fields.Date.to_date('2026-12-31'))

        fiscal_year = self.env['account.fiscal.year'].create({
            'name': 'Short FY 2026',
            'date_from': '2026-01-01',
            'date_to': '2026-06-30',
            'company_id': company.id,
        })
        overridden = company.compute_fiscalyear_dates(anchor)
        self.assertEqual(overridden['date_to'], fields.Date.to_date('2026-06-30'))
        self.assertEqual(overridden['record'], fiscal_year)

    def test_fiscal_year_gap_shortens_computed_range(self):
        """A recorded year adjacent to the computed range trims that range."""
        company = self.env.company
        self.env['account.fiscal.year'].create({
            'name': 'Short FY 2026',
            'date_from': '2026-01-01',
            'date_to': '2026-06-30',
            'company_id': company.id,
        })
        # 2026-09-15 is outside the recorded year, so the computed calendar year
        # is trimmed to start the day after that year ends.
        dates = company.compute_fiscalyear_dates(fields.Date.to_date('2026-09-15'))
        self.assertEqual(dates['date_from'], fields.Date.to_date('2026-07-01'))
        self.assertEqual(dates['date_to'], fields.Date.to_date('2026-12-31'))

    def test_fiscal_year_overlap_is_rejected(self):
        company = self.env.company
        self.env['account.fiscal.year'].create({
            'name': 'FY A', 'date_from': '2026-01-01', 'date_to': '2026-06-30',
            'company_id': company.id,
        })
        with self.assertRaises(ValidationError):
            self.env['account.fiscal.year'].create({
                'name': 'FY B', 'date_from': '2026-06-01', 'date_to': '2026-12-31',
                'company_id': company.id,
            })

    def test_fiscal_year_end_before_start_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['account.fiscal.year'].create({
                'name': 'Backwards', 'date_from': '2026-12-31', 'date_to': '2026-01-01',
                'company_id': self.env.company.id,
            })

    def test_lock_date_wizard_applies_dates(self):
        wizard = self.env['account.change.lock.date'].create({
            'company_id': self.env.company.id,
            'fiscalyear_lock_date': '2026-01-31',
            'tax_lock_date': '2026-01-31',
        })
        wizard.action_apply()
        self.assertEqual(self.env.company.fiscalyear_lock_date, fields.Date.to_date('2026-01-31'))
        self.assertEqual(self.env.company.tax_lock_date, fields.Date.to_date('2026-01-31'))

    def test_hard_lock_date_cannot_be_moved_back(self):
        """The hard lock is one-way, so an earlier date must be refused."""
        self.env.company.sudo().hard_lock_date = fields.Date.to_date('2026-06-30')
        with self.assertRaises(UserError):
            self.env['account.change.lock.date'].create({
                'company_id': self.env.company.id,
                'hard_lock_date': '2026-01-31',
            })

    def test_report_action_contexts_are_client_evaluable(self):
        """Client action contexts must not rely on server-only builtins.

        The context is stored as a string and evaluated by the web client, so a
        leftover ``ref(...)`` raises "Name 'ref' is not defined" in the browser
        the moment the menu is opened.
        """
        import ast as _ast

        actions = self.env['ir.actions.client'].search([('tag', '=', 'account_report')])
        self.assertTrue(actions, "No accounting report client actions were found")

        for action in actions:
            with self.subTest(action=action.name):
                self.assertNotIn(
                    'ref(', action.context,
                    "%s still evaluates ref() in the browser" % action.name,
                )
                context = _ast.literal_eval(action.context)
                report_id = context.get('report_id')
                self.assertIsInstance(
                    report_id, int,
                    "%s must carry a literal report id" % action.name,
                )
                self.assertTrue(
                    self.env['account.report'].browse(report_id).exists(),
                    "%s points at a report that does not exist" % action.name,
                )

    def test_accounting_menu_opens_the_dashboard(self):
        """Opening the app must land on the journal dashboard for any user.

        Relying on the first visible child instead would send users without
        account.group_account_basic to Customers, since the Dashboard menu is
        restricted to that group.
        """
        accounting = self.env.ref('jkm_full_accounting.menu_accounting')
        dashboard_action = self.env.ref('account.open_account_journal_dashboard_kanban')

        self.assertTrue(accounting.action, "The Accounting menu has no action set")
        self.assertEqual(accounting.action.id, dashboard_action.id)
        self.assertEqual(accounting.action._name, 'ir.actions.act_window')


@tagged('post_install', '-at_install')
class TestReconcileWorkflow(AccountTestInvoicingCommon):
    """The Journal Items reconcile workflow driven from the list view."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.receivable = cls.company_data['default_account_receivable']
        cls.revenue = cls.company_data['default_account_revenue']
        cls.bank = cls.company_data['default_account_assets']
        cls.today = fields.Date.context_today(cls.env['account.move.line'])

    def _post(self, lines):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': self.today,
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': acc.id, 'debit': d, 'credit': c, 'partner_id': self.partner_a.id})
                for acc, d, c in lines
            ],
        })
        move.action_post()
        return move

    def test_balanced_selection_reconciles_without_a_wizard(self):
        """Nothing to write off, so reconciliation happens silently."""
        invoice = self._post([(self.receivable, 500.0, 0.0), (self.revenue, 0.0, 500.0)])
        payment = self._post([(self.bank, 500.0, 0.0), (self.receivable, 0.0, 500.0)])

        lines = (invoice.line_ids + payment.line_ids).filtered(
            lambda line: line.account_id == self.receivable
        )
        result = lines.action_reconcile()

        self.assertNotEqual(
            (result or {}).get('res_model'), 'account.reconcile.wizard',
            "A balanced selection must not open the write-off wizard",
        )
        self.assertTrue(all(lines.mapped('reconciled')), "Lines were not reconciled")
        self.assertTrue(lines.mapped('full_reconcile_id'))

    def test_unbalanced_selection_opens_the_wizard(self):
        invoice = self._post([(self.receivable, 500.0, 0.0), (self.revenue, 0.0, 500.0)])
        payment = self._post([(self.bank, 450.0, 0.0), (self.receivable, 0.0, 450.0)])

        lines = (invoice.line_ids + payment.line_ids).filtered(
            lambda line: line.account_id == self.receivable
        )
        action = lines.action_reconcile()

        self.assertEqual(action['res_model'], 'account.reconcile.wizard')
        wizard = self.env['account.reconcile.wizard'].browse(action['res_id'])
        self.assertTrue(wizard.is_write_off_required)
        self.assertAlmostEqual(wizard.amount, 50.0, places=2)

    def test_write_off_absorbs_the_residual(self):
        invoice = self._post([(self.receivable, 500.0, 0.0), (self.revenue, 0.0, 500.0)])
        payment = self._post([(self.bank, 450.0, 0.0), (self.receivable, 0.0, 450.0)])
        lines = (invoice.line_ids + payment.line_ids).filtered(
            lambda line: line.account_id == self.receivable
        )

        wizard = self.env['account.reconcile.wizard'].with_context(
            active_model='account.move.line', active_ids=lines.ids,
        ).create({
            'account_id': self.company_data['default_account_expense'].id,
            'journal_id': self.company_data['default_journal_misc'].id,
        })
        wizard.reconcile()

        self.assertTrue(all(lines.mapped('reconciled')))
        # The 50.00 shortfall is now carried by the write-off account.
        write_off = self.env['account.move.line'].search([
            ('account_id', '=', self.company_data['default_account_expense'].id),
            ('name', '=', 'Write-Off'),
        ])
        self.assertAlmostEqual(sum(write_off.mapped('balance')), 50.0, places=2)

    def test_partial_reconcile_leaves_the_residual_open(self):
        invoice = self._post([(self.receivable, 500.0, 0.0), (self.revenue, 0.0, 500.0)])
        payment = self._post([(self.bank, 450.0, 0.0), (self.receivable, 0.0, 450.0)])
        lines = (invoice.line_ids + payment.line_ids).filtered(
            lambda line: line.account_id == self.receivable
        )

        wizard = self.env['account.reconcile.wizard'].with_context(
            active_model='account.move.line', active_ids=lines.ids,
        ).create({'allow_partials': True})
        wizard.reconcile()

        self.assertFalse(
            any(lines.mapped('full_reconcile_id')),
            "A partial reconciliation must not fully reconcile the lines",
        )
        self.assertAlmostEqual(sum(lines.mapped('amount_residual')), 50.0, places=2)

    def test_more_than_two_accounts_is_rejected(self):
        move = self._post([
            (self.receivable, 500.0, 0.0),
            (self.bank, 200.0, 0.0),
            (self.revenue, 0.0, 700.0),
        ])
        with self.assertRaises(UserError):
            self.env['account.reconcile.wizard'].with_context(
                active_model='account.move.line', active_ids=move.line_ids.ids,
            ).create({})

    def test_reconcile_menu_sits_under_closing(self):
        reconcile_menu = self.env.ref('jkm_full_accounting.menu_account_reconcile')
        lock_menu = self.env.ref('jkm_full_accounting.menu_account_change_lock_date')
        closing = self.env.ref('account.account_closing_menu')
        self.assertEqual(reconcile_menu.parent_id, closing)
        self.assertEqual(lock_menu.parent_id, closing)

    def test_admin_gets_full_accounting_features(self):
        """Community grants account.group_account_user to nobody.

        Everything gated on it - the Reconcile action among them - is invisible
        until the module hands the group out, so the app would look complete
        while half its features were missing.
        """
        admin = self.env.ref('base.user_admin')
        self.assertTrue(
            admin.has_group('account.group_account_user'),
            "Administrator was not granted full accounting features",
        )
        manager = self.env.ref('account.group_account_manager')
        user_group = self.env.ref('account.group_account_user')
        self.assertIn(
            user_group, manager.implied_ids,
            "Accounting managers must imply the full accounting group",
        )

    def test_reconcile_button_is_visible_to_accountants(self):
        """The Reconcile button must survive the group filtering of the arch."""
        admin = self.env.ref('base.user_admin')
        arch = self.env['account.move.line'].with_user(admin).get_view(view_type='list')['arch']
        self.assertIn('action_reconcile', arch, "Reconcile button is missing from Journal Items")
        self.assertIn('matching_link_widget', arch, "Matching link widget is missing")

    def test_journal_entries_and_items_menus_are_in_place(self):
        """Both menus hang where the Accounting app expects them."""
        entries = self.env.ref('account.menu_action_move_journal_line_form')
        items = self.env.ref('account.menu_action_account_moves_all')

        self.assertEqual(entries.parent_id, self.env.ref('account.account_transactions_menu'))
        self.assertEqual(items.parent_id, self.env.ref('account.account_audit_control_menu'))
        self.assertEqual(entries.action.res_model, 'account.move')
        self.assertEqual(items.action.res_model, 'account.move.line')


@tagged('post_install', '-at_install')
class TestSalesBreakdown(AccountTestInvoicingCommon):
    """Revenue booked to one account must still be traceable to its journal."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env['account.report'])
        cls.revenue = cls.company_data['default_account_revenue']
        cls.bank = cls.company_data['default_account_assets']
        # A second sale journal stands in for the Point of Sale journal, which
        # posts takings to the very same revenue account as invoicing.
        cls.pos_journal = cls.env['account.journal'].create({
            'name': 'Point of Sale',
            'code': 'POSS',
            'type': 'general',
            'company_id': cls.env.company.id,
        })

    def _post(self, journal, amount):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': self.today,
            'journal_id': journal.id,
            'line_ids': [
                (0, 0, {'account_id': self.bank.id, 'debit': amount, 'credit': 0.0}),
                (0, 0, {'account_id': self.revenue.id, 'debit': 0.0, 'credit': amount}),
            ],
        })
        move.action_post()
        return move

    def test_income_splits_by_journal_under_the_account(self):
        self._post(self.company_data['default_journal_sale'], 100.0)
        self._post(self.pos_journal, 40.0)

        report = self.env.ref('jkm_full_accounting.profit_and_loss')
        options = report._get_options({'unfold_all': True})
        lines = report._get_lines(options)

        by_name = {}
        for line in lines:
            by_name.setdefault(line['name'], 0.0)
            by_name[line['name']] += line['columns'][0]['no_format'] or 0.0

        # Both journals feed the same account, so the account totals 140...
        account_label = self.revenue.display_name
        self.assertAlmostEqual(by_name.get(account_label, 0.0), 140.0, places=2)
        # ...but each journal is still visible underneath it.
        self.assertAlmostEqual(by_name.get('Point of Sale', 0.0), 40.0, places=2,
                               msg="Point of Sale takings are not broken out by journal")
        self.assertIn(
            self.company_data['default_journal_sale'].name, by_name,
            "The sales journal is missing from the breakdown",
        )

    def test_nested_groupby_only_expands_when_unfolded(self):
        """The second level must stay collapsed until it is asked for."""
        self._post(self.pos_journal, 40.0)
        report = self.env.ref('jkm_full_accounting.profit_and_loss')

        options = report._get_options({})
        names = {line['name'] for line in report._get_lines(options)}
        self.assertNotIn('Point of Sale', names, "Journal level leaked into the folded report")

        options = report._get_options({'unfold_all': True})
        names = {line['name'] for line in report._get_lines(options)}
        self.assertIn('Point of Sale', names)


@tagged('post_install', '-at_install')
class TestReportPresentation(AccountTestInvoicingCommon):
    """Every report must hand the client what it needs to render itself."""

    REPORTS = (
        'balance_sheet', 'profit_and_loss', 'general_ledger_report',
        'trial_balance_report', 'partner_ledger_report', 'aged_receivable_report',
        'aged_payable_report', 'cash_flow_report', 'tax_audit_report',
    )

    def test_every_report_declares_its_layout(self):
        """A missing layout would silently fall back to statement banding."""
        statement_reports = {'balance_sheet', 'profit_and_loss'}
        for xmlid in self.REPORTS:
            report = self.env.ref('jkm_full_accounting.%s' % xmlid)
            with self.subTest(report=xmlid):
                payload = self.env['account.report'].get_report_data(report.id, {})
                layout = payload['report']['layout']
                self.assertIn(layout, ('hierarchy', 'list'))
                expected = 'hierarchy' if xmlid in statement_reports else 'list'
                self.assertEqual(
                    layout, expected,
                    "%s should render as a %s report" % (xmlid, expected),
                )
                self.assertEqual(
                    payload['report']['column_count'], len(payload['options']['columns']),
                )

    def test_every_report_exposes_filters_and_headers(self):
        for xmlid in self.REPORTS:
            report = self.env.ref('jkm_full_accounting.%s' % xmlid)
            with self.subTest(report=xmlid):
                payload = self.env['account.report'].get_report_data(report.id, {})
                options = payload['options']
                self.assertTrue(options['columns'], "%s has no columns" % xmlid)
                self.assertTrue(options['column_headers'], "%s has no period header" % xmlid)
                self.assertIn('date', options)
                self.assertIn('all_entries', options)
                self.assertIsInstance(payload['warnings'], list)
                for column in options['columns']:
                    self.assertTrue(column.get('figure_type'),
                                    "%s has a column with no figure type" % xmlid)

    def test_draft_entries_raise_a_warning(self):
        """The reader must be told when posted-only figures hide draft entries."""
        report = self.env.ref('jkm_full_accounting.balance_sheet')
        self.assertFalse(self.env['account.report'].get_report_data(report.id, {})['warnings'])

        self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(report),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.company_data['default_account_assets'].id,
                        'debit': 100.0, 'credit': 0.0}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': 100.0}),
            ],
        })  # left in draft

        warnings = self.env['account.report'].get_report_data(report.id, {})['warnings']
        self.assertTrue(warnings, "Draft entries did not raise a warning")
        self.assertEqual(warnings[0]['action'], 'toggle_all_entries')

        # Including them resolves the warning.
        payload = self.env['account.report'].get_report_data(report.id, {'all_entries': True})
        self.assertFalse(payload['warnings'])

    def test_every_report_payload_carries_annotations(self):
        for xmlid in self.REPORTS:
            report = self.env.ref('jkm_full_accounting.%s' % xmlid)
            with self.subTest(report=xmlid):
                payload = self.env['account.report'].get_report_data(report.id, {})
                self.assertIsInstance(payload['annotations'], dict)

    def test_annotation_round_trip(self):
        report = self.env.ref('jkm_full_accounting.balance_sheet')
        line_id = report._get_lines(report._get_options({}))[0]['id']

        saved = self.env['account.report'].set_line_annotation(report.id, line_id, "Check with auditor")
        self.assertEqual(saved['text'], "Check with auditor")

        payload = self.env['account.report'].get_report_data(report.id, {})
        self.assertEqual(payload['annotations'][line_id]['text'], "Check with auditor")

        # Re-saving updates rather than duplicating.
        self.env['account.report'].set_line_annotation(report.id, line_id, "Cleared")
        self.assertEqual(
            self.env['jkm.report.annotation'].search_count([('line_id', '=', line_id)]), 1,
        )

        # Emptying the text removes the note.
        self.assertFalse(self.env['account.report'].set_line_annotation(report.id, line_id, "  "))
        self.assertFalse(self.env['account.report'].get_report_data(report.id, {})['annotations'])

    def test_line_drill_through_opens_the_journal_entry(self):
        """The ellipsis on a journal item must open its entry, not the line."""
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.company_data['default_account_assets'].id,
                        'debit': 250.0, 'credit': 0.0}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': 250.0}),
            ],
        })
        move.action_post()

        report = self.env.ref('jkm_full_accounting.general_ledger_report')
        options = report._get_options({'unfold_all': True})
        lines = report._get_lines(options)

        item_line = next(
            (l for l in lines if l.get('caret_options') == 'account.move.line'), None,
        )
        self.assertIsNotNone(item_line, "General Ledger produced no journal item lines")

        action = report.action_open_line_record(item_line['id'])
        self.assertEqual(action['res_model'], 'account.move')
        self.assertEqual(action['res_id'], move.id)

    def test_drill_through_ignores_lines_without_a_record(self):
        report = self.env.ref('jkm_full_accounting.balance_sheet')
        line_id = report._get_lines(report._get_options({}))[0]['id']
        self.assertFalse(report.action_open_line_record(line_id))

    def test_line_chatter_resolves_to_the_journal_entry(self):
        """The conversation lives on the entry, not on its individual lines."""
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.company_data['default_account_assets'].id,
                        'debit': 75.0, 'credit': 0.0}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': 75.0}),
            ],
        })
        move.action_post()

        report = self.env.ref('jkm_full_accounting.general_ledger_report')
        lines = report._get_lines(report._get_options({'unfold_all': True}))
        item_line = next(l for l in lines if l.get('caret_options') == 'account.move.line')

        thread = report.get_line_thread(item_line['id'])
        self.assertEqual(thread['model'], 'account.move')
        self.assertEqual(thread['id'], move.id)
        self.assertTrue(thread['name'])

    def test_section_lines_have_no_chatter(self):
        """A report heading has no record, so the icon falls back to a note."""
        report = self.env.ref('jkm_full_accounting.balance_sheet')
        line_id = report._get_lines(report._get_options({}))[0]['id']
        self.assertFalse(report.get_line_thread(line_id))

    def test_chatter_target_tracks_messages(self):
        """Whatever the resolver returns must actually accept messages."""
        report = self.env.ref('jkm_full_accounting.partner_ledger_report')
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.company_data['default_account_receivable'].id,
                        'debit': 30.0, 'credit': 0.0, 'partner_id': self.partner_a.id}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': 30.0}),
            ],
        })
        move.action_post()

        lines = report._get_lines(report._get_options({'unfold_all': True}))
        partner_line = next(l for l in lines if l.get('caret_options') == 'res.partner')
        thread = report.get_line_thread(partner_line['id'])
        self.assertTrue(thread)
        self.assertIn('message_ids', self.env[thread['model']]._fields)

    def test_partner_ledger_expands_into_records(self):
        """A partner row must open into the entries behind its balance."""
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.company_data['default_account_receivable'].id,
                        'debit': 120.0, 'credit': 0.0, 'partner_id': self.partner_a.id}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': 120.0}),
            ],
        })
        move.action_post()

        report = self.env.ref('jkm_full_accounting.partner_ledger_report')

        # Folded: the partner is a single summary row.
        folded = report._get_lines(report._get_options({}))
        partner_line = next(l for l in folded if l['name'] == self.partner_a.display_name)
        self.assertTrue(partner_line['unfoldable'], "Partner row is not expandable")
        self.assertFalse(
            any(l.get('caret_options') == 'account.move.line' for l in folded),
            "Journal items leaked into the folded report",
        )

        # Unfolded: its journal items and a per-partner total appear.
        expanded = report._get_lines(report._get_options({'unfold_all': True}))
        items = [l for l in expanded if l.get('caret_options') == 'account.move.line']
        self.assertTrue(items, "Partner row did not expand into journal items")
        self.assertFalse(
            any(l['name'].startswith('Total %s' % self.partner_a.display_name) for l in expanded),
            "The partner row already carries the totals; no subtotal is repeated",
        )

        labels = [c['expression_label'] for c in report._get_options({})['columns']]
        values = dict(zip(labels, [c['no_format'] for c in items[0]['columns']]))
        self.assertAlmostEqual(values['debit'], 120.0, places=2)
        self.assertAlmostEqual(values['balance'], 120.0, places=2)
        self.assertEqual(values['journal_code'], self.company_data['default_journal_misc'].code)

    def test_partner_ledger_running_balance_accumulates(self):
        """The balance column carries forward down the partner's items."""
        for amount in (100.0, 50.0):
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'date': fields.Date.context_today(self.env['account.report']),
                'journal_id': self.company_data['default_journal_misc'].id,
                'line_ids': [
                    (0, 0, {'account_id': self.company_data['default_account_receivable'].id,
                            'debit': amount, 'credit': 0.0, 'partner_id': self.partner_a.id}),
                    (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                            'debit': 0.0, 'credit': amount}),
                ],
            })
            move.action_post()

        report = self.env.ref('jkm_full_accounting.partner_ledger_report')
        options = report._get_options({'unfold_all': True})
        labels = [c['expression_label'] for c in options['columns']]
        items = [l for l in report._get_lines(options) if l.get('caret_options') == 'account.move.line']

        balances = [dict(zip(labels, [c['no_format'] for c in l['columns']]))['balance'] for l in items]
        self.assertEqual(len(balances), 2)
        self.assertAlmostEqual(balances[-1], 150.0, places=2,
                               msg="Running balance did not accumulate to the partner total")

    def test_general_ledger_balance_runs_forward(self):
        """Each item shows the balance so far, not its own movement."""
        for amount in (100.0, 40.0, 25.0):
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'date': fields.Date.context_today(self.env['account.report']),
                'journal_id': self.company_data['default_journal_misc'].id,
                'line_ids': [
                    (0, 0, {'account_id': self.company_data['default_account_assets'].id,
                            'debit': amount, 'credit': 0.0}),
                    (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                            'debit': 0.0, 'credit': amount}),
                ],
            })
            move.action_post()

        report = self.env.ref('jkm_full_accounting.general_ledger_report')
        options = report._get_options({'unfold_all': True})
        labels = [c['expression_label'] for c in options['columns']]
        lines = report._get_lines(options)

        asset_code = self.company_data['default_account_assets'].code
        items = [
            l for l in lines
            if l.get('caret_options') == 'account.move.line'
            and (l.get('parent_id') or '').endswith(str(self.company_data['default_account_assets'].id))
        ]
        self.assertEqual(len(items), 3)

        balances = [dict(zip(labels, [c['no_format'] for c in l['columns']]))['end_balance'] for l in items]
        self.assertEqual(
            [round(b, 2) for b in balances], [100.0, 140.0, 165.0],
            "General Ledger balance column is not cumulative",
        )

    def test_general_ledger_account_row_carries_the_totals(self):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.company_data['default_account_assets'].id,
                        'debit': 210.0, 'credit': 0.0}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': 210.0}),
            ],
        })
        move.action_post()

        report = self.env.ref('jkm_full_accounting.general_ledger_report')
        options = report._get_options({'unfold_all': True})
        labels = [c['expression_label'] for c in options['columns']]
        lines = report._get_lines(options)

        account = self.company_data['default_account_assets']
        self.assertFalse(
            [l for l in lines if l['name'].startswith('Total %s' % account.code)],
            "The account row already carries the totals; none is repeated below",
        )
        # The account row itself still states what the period came to.
        account_line = next(l for l in lines if l['name'].startswith(account.code))
        values = dict(zip(labels, [c['no_format'] for c in account_line['columns']]))
        self.assertAlmostEqual(values['debit'], 210.0, places=2)
        self.assertAlmostEqual(values['end_balance'], 210.0, places=2)

    def test_general_ledger_shows_the_opening_balance(self):
        """An account carrying a prior balance opens on it."""
        report = self.env.ref('jkm_full_accounting.general_ledger_report')
        today = fields.Date.context_today(self.env['account.report'])

        for date, amount in ((today - timedelta(days=60), 500.0), (today, 70.0)):
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'date': date,
                'journal_id': self.company_data['default_journal_misc'].id,
                'line_ids': [
                    (0, 0, {'account_id': self.company_data['default_account_assets'].id,
                            'debit': amount, 'credit': 0.0}),
                    (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                            'debit': 0.0, 'credit': amount}),
                ],
            })
            move.action_post()

        # A month-scoped period leaves the older entry in the opening balance.
        options = report._get_options({'unfold_all': True, 'date': {'filter': 'this_month'}})
        labels = [c['expression_label'] for c in options['columns']]
        lines = report._get_lines(options)

        opening = next((l for l in lines if l['name'] == 'Initial Balance'), None)
        self.assertIsNotNone(opening, "No opening balance shown for a brought-forward account")
        values = dict(zip(labels, [c['no_format'] for c in opening['columns']]))
        self.assertAlmostEqual(values['end_balance'], 500.0, places=2)

    def test_journal_items_button_filters_to_the_account(self):
        """The drill-down must show that account's items and no others."""
        assets = self.company_data['default_account_assets']
        revenue = self.company_data['default_account_revenue']
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': assets.id, 'debit': 90.0, 'credit': 0.0}),
                (0, 0, {'account_id': revenue.id, 'debit': 0.0, 'credit': 90.0}),
            ],
        })
        move.action_post()

        report = self.env.ref('jkm_full_accounting.general_ledger_report')
        options = report._get_options({})
        account_line = next(
            l for l in report._get_lines(options)
            if l.get('caret_options') == 'account.account'
            and l['name'].startswith(assets.code)
        )

        action = report.action_open_journal_items(account_line['id'], options)
        self.assertEqual(action['res_model'], 'account.move.line')
        self.assertEqual(
            action['context'].get('search_default_group_by_account'), 1,
            "Drill-down should arrive grouped by account",
        )

        found = self.env['account.move.line'].search(action['domain'])
        self.assertTrue(found, "Drill-down returned no journal items")
        self.assertEqual(
            found.account_id, assets,
            "Drill-down leaked items from other accounts",
        )

    def test_journal_items_button_respects_the_report_period(self):
        """Items outside the report's dates must not appear in the drill-down."""
        assets = self.company_data['default_account_assets']
        today = fields.Date.context_today(self.env['account.report'])

        for date in (today, today - timedelta(days=400)):
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'date': date,
                'journal_id': self.company_data['default_journal_misc'].id,
                'line_ids': [
                    (0, 0, {'account_id': assets.id, 'debit': 10.0, 'credit': 0.0}),
                    (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                            'debit': 0.0, 'credit': 10.0}),
                ],
            })
            move.action_post()

        report = self.env.ref('jkm_full_accounting.general_ledger_report')
        options = report._get_options({'date': {'filter': 'this_month'}})
        account_line = next(
            l for l in report._get_lines(options)
            if l.get('caret_options') == 'account.account'
            and l['name'].startswith(assets.code)
        )

        found = self.env['account.move.line'].search(
            report.action_open_journal_items(account_line['id'], options)['domain']
        )
        self.assertEqual(len(found), 1, "Drill-down ignored the report's date range")
        self.assertEqual(found.date, today)

    def test_journal_items_button_rejects_section_lines(self):
        report = self.env.ref('jkm_full_accounting.balance_sheet')
        options = report._get_options({})
        line_id = report._get_lines(options)[0]['id']
        self.assertFalse(report.action_open_journal_items(line_id, options))

    def test_balance_sheet_closes_sections_with_totals(self):
        """Each expanded section ends on its own total."""
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.company_data['default_account_assets'].id,
                        'debit': 800.0, 'credit': 0.0}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': 800.0}),
            ],
        })
        move.action_post()

        report = self.env.ref('jkm_full_accounting.balance_sheet')
        options = report._get_options({'unfold_all': True})
        lines = report._get_lines(options)
        names = [l['name'] for l in lines]

        self.assertIn('Total Assets', names)
        self.assertIn('Total Current Assets', names)
        self.assertIn('Total Accounts Receivable', names)
        self.assertIn('Total Liabilities', names)

        # The total must restate the section it closes, not recompute it.
        assets = next(l for l in lines if l['name'] == 'Assets')
        total_assets = next(l for l in lines if l['name'] == 'Total Assets')
        self.assertAlmostEqual(
            assets['columns'][0]['no_format'],
            total_assets['columns'][0]['no_format'], places=2,
        )

    def test_ledger_style_reports_have_no_section_totals(self):
        """Section totals suit statements; a flat ledger must not sprout them."""
        report = self.env.ref('jkm_full_accounting.general_ledger_report')
        # Ledger reports frame themselves and total their own accounts, so the
        # static-line section feature must stay off or totals would double up.
        self.assertFalse(report.show_section_totals)
        names = [l['name'] for l in report._get_lines(report._get_options({'unfold_all': True}))]
        self.assertNotIn(
            'Total General Ledger', names,
            "Ledger reports carry no grand total row",
        )

    def test_balance_sheet_account_traces_to_the_general_ledger(self):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.company_data['default_account_assets'].id,
                        'debit': 300.0, 'credit': 0.0}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': 300.0}),
            ],
        })
        move.action_post()

        report = self.env.ref('jkm_full_accounting.balance_sheet')
        options = report._get_options({'unfold_all': True})
        account_line = next(
            l for l in report._get_lines(options) if l.get('caret_options') == 'account.account'
        )

        action = report.action_open_general_ledger(account_line['id'], options)
        ledger = self.env.ref('jkm_full_accounting.general_ledger_report')
        self.assertEqual(action['tag'], 'account_report')
        self.assertEqual(action['context']['report_id'], ledger.id)
        # The chosen account arrives already opened.
        self.assertTrue(action['context']['default_options']['unfolded_lines'])

    def test_general_ledger_trace_rejects_non_account_lines(self):
        report = self.env.ref('jkm_full_accounting.balance_sheet')
        options = report._get_options({})
        line_id = report._get_lines(options)[0]['id']
        self.assertFalse(report.action_open_general_ledger(line_id, options))


@tagged('post_install', '-at_install')
class TestProfitAndLossLayout(AccountTestInvoicingCommon):
    """The statement reads top to bottom, each band following from the last."""

    def _values_by_code(self, report):
        options = report._get_options({})
        result = {}
        for line in report._get_lines(options):
            report_line_id = line.get('report_line_id')
            if not report_line_id:
                continue
            code = self.env['account.report.line'].browse(report_line_id).code
            if code:
                result[code] = line['columns'][0]['no_format']
        return result

    def _post(self, account, contra, amount):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': account.id, 'debit': amount, 'credit': 0.0}),
                (0, 0, {'account_id': contra.id, 'debit': 0.0, 'credit': amount}),
            ],
        })
        move.action_post()
        return move

    def test_sections_appear_in_statement_order(self):
        report = self.env.ref('jkm_full_accounting.profit_and_loss')
        names = [l['name'] for l in report._get_lines(report._get_options({}))]

        expected = [
            'Income', 'Cost of Sales', 'Gross Profit', 'Expense',
            'Net Operating Income', 'Other Income', 'Other Expense',
            'Net Other Income', 'Net Income',
        ]
        positions = [names.index(n) for n in expected]
        self.assertEqual(
            positions, sorted(positions),
            "Profit and Loss sections are out of order: %s" % names,
        )

    def test_every_line_is_top_level(self):
        """The statement is a flat sequence, not a tree."""
        report = self.env.ref('jkm_full_accounting.profit_and_loss')
        for line in report.line_ids:
            self.assertFalse(
                line.parent_id,
                "%s is nested; the statement should be flat" % line.name,
            )

    def test_subtotals_chain_correctly(self):
        self._post(self.company_data['default_account_assets'],
                   self.company_data['default_account_revenue'], 1000.0)
        self._post(self.company_data['default_account_expense'],
                   self.company_data['default_account_assets'], 300.0)

        values = self._values_by_code(self.env.ref('jkm_full_accounting.profit_and_loss'))
        self.assertAlmostEqual(values['PL_GROSS'], values['PL_INCOME'] - values['PL_COST'], places=2)
        self.assertAlmostEqual(values['PL_NET_OP'], values['PL_GROSS'] - values['PL_EXPENSE'], places=2)
        self.assertAlmostEqual(
            values['PL_NET_OTHER'],
            values['PL_OTHER_INCOME'] - values['PL_OTHER_EXPENSE'], places=2,
        )
        self.assertAlmostEqual(values['PL_NET'], values['PL_NET_OP'] + values['PL_NET_OTHER'], places=2)
        self.assertAlmostEqual(values['PL_NET'], 700.0, places=2)


@tagged('post_install', '-at_install')
class TestTrialBalanceLayout(AccountTestInvoicingCommon):
    """Opening, movement and closing sit under headings of their own."""

    def _post(self, amount=250.0):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.company_data['default_account_assets'].id,
                        'debit': amount, 'credit': 0.0}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': amount}),
            ],
        })
        move.action_post()
        return move

    def test_columns_are_grouped_under_three_headings(self):
        report = self.env.ref('jkm_full_accounting.trial_balance_report')
        options = report._get_options({})

        self.assertEqual(
            [c['expression_label'] for c in options['columns']],
            ['initial_balance', 'debit', 'credit', 'end_balance'],
        )
        headers = [(h['name'], h['colspan']) for h in options['column_headers']]
        self.assertEqual(headers[0], ('Initial Balance', 1))
        self.assertEqual(headers[-1], ('End Balance', 1))
        # Debit and Credit share the period heading between them.
        self.assertEqual(headers[1][1], 2)
        self.assertEqual(headers[1][0], options['date']['string'])

    def test_accounts_are_grouped_by_account_group(self):
        self._post()
        report = self.env.ref('jkm_full_accounting.trial_balance_report')
        lines = report._get_lines(report._get_options({'unfold_all': True}))

        group_lines = [l for l in lines if l.get('unfoldable')]
        self.assertTrue(group_lines, "Trial balance shows no account groups")
        # Accounts hang off a group rather than sitting at the root.
        account_lines = [l for l in lines if l.get('caret_options') == 'account.account']
        self.assertTrue(account_lines)
        self.assertTrue(all(l.get('parent_id') for l in account_lines))

    def test_closing_balance_follows_from_opening_and_movement(self):
        self._post(250.0)
        report = self.env.ref('jkm_full_accounting.trial_balance_report')
        options = report._get_options({'unfold_all': True})
        labels = [c['expression_label'] for c in options['columns']]

        assets = self.company_data['default_account_assets']
        line = next(
            l for l in report._get_lines(options)
            if l.get('caret_options') == 'account.account' and l['name'].startswith(assets.code)
        )
        values = dict(zip(labels, [c['no_format'] for c in line['columns']]))
        self.assertAlmostEqual(
            values['end_balance'],
            values['initial_balance'] + values['debit'] - values['credit'], places=2,
        )
        self.assertAlmostEqual(values['debit'], 250.0, places=2)

    def test_lines_expose_their_record_type_for_badges(self):
        """The client labels its badges from caret_options, so it must be set."""
        expected = {
            'general_ledger_report': 'account.account',
            'trial_balance_report': 'account.account',
            'partner_ledger_report': 'res.partner',
            'aged_receivable_report': 'res.partner',
        }
        # A receivable booked against a partner, so the partner-keyed reports
        # have something to show.
        receivable = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.company_data['default_account_receivable'].id,
                        'debit': 180.0, 'credit': 0.0, 'partner_id': self.partner_a.id}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': 180.0}),
            ],
        })
        receivable.action_post()
        self._post()
        for xmlid, caret in expected.items():
            report = self.env.ref('jkm_full_accounting.%s' % xmlid)
            with self.subTest(report=xmlid):
                lines = report._get_lines(report._get_options({'unfold_all': True}))
                carets = {l.get('caret_options') for l in lines}
                self.assertIn(
                    caret, carets,
                    "%s exposes no %s line, so no badge can be shown" % (xmlid, caret),
                )

    def test_fold_rows_and_record_rows_are_distinguishable(self):
        """The client shows badges on fold rows and icons on record rows.

        That split only works if the server marks the two kinds apart: a row
        that summarises others is unfoldable, a row standing for one record is
        not.
        """
        receivable = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.company_data['default_account_receivable'].id,
                        'debit': 95.0, 'credit': 0.0, 'partner_id': self.partner_a.id}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': 95.0}),
            ],
        })
        receivable.action_post()

        report = self.env.ref('jkm_full_accounting.partner_ledger_report')
        lines = report._get_lines(report._get_options({'unfold_all': True}))

        partner_line = next(l for l in lines if l['name'] == self.partner_a.display_name)
        self.assertTrue(partner_line['unfoldable'], "Partner row must read as a fold row")
        self.assertEqual(partner_line['caret_options'], 'res.partner')

        item_line = next(l for l in lines if l.get('caret_options') == 'account.move.line')
        self.assertFalse(item_line['unfoldable'], "A journal item is a record row, not a fold row")

    def test_partner_drill_down_is_not_grouped_by_account(self):
        """From a partner, the items are already one partner's; grouping them
        by account only hides what the reader came to see."""
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.company_data['default_account_receivable'].id,
                        'debit': 60.0, 'credit': 0.0, 'partner_id': self.partner_a.id}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': 60.0}),
            ],
        })
        move.action_post()

        report = self.env.ref('jkm_full_accounting.partner_ledger_report')
        options = report._get_options({})
        partner_line = next(
            l for l in report._get_lines(options) if l.get('caret_options') == 'res.partner'
        )

        action = report.action_open_journal_items(partner_line['id'], options)
        self.assertNotIn('search_default_group_by_account', action['context'])

        found = self.env['account.move.line'].search(action['domain'])
        self.assertTrue(found)
        self.assertEqual(found.partner_id, self.partner_a)

    def test_partner_ledger_is_framed_by_its_own_name(self):
        """The report opens on a heading and closes on a matching total."""
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.company_data['default_account_receivable'].id,
                        'debit': 70.0, 'credit': 0.0, 'partner_id': self.partner_a.id}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': 70.0}),
            ],
        })
        move.action_post()

        report = self.env.ref('jkm_full_accounting.partner_ledger_report')
        options = report._get_options({})
        lines = report._get_lines(options)

        self.assertEqual(lines[0]['name'], 'Partner Ledger')
        self.assertNotIn(
            'Total Partner Ledger', [l['name'] for l in lines],
            "The report should not append a grand total",
        )

        # Partners sit under the heading rather than at the root.
        partner_line = next(l for l in lines if l['name'] == self.partner_a.display_name)
        self.assertEqual(partner_line['parent_id'], lines[0]['id'])

        labels = [c['expression_label'] for c in options['columns']]
        values = dict(zip(labels, [c['no_format'] for c in partner_line['columns']]))
        self.assertAlmostEqual(values['debit'], 70.0, places=2)

    def test_only_listing_reports_offer_a_search(self):
        """Reports listing accounts or partners can be searched; the statements
        are a fixed set of sections with nothing to look up."""
        searchable = {
            'general_ledger_report', 'trial_balance_report', 'partner_ledger_report',
            'aged_receivable_report', 'aged_payable_report', 'tax_audit_report',
        }
        not_searchable = {'balance_sheet', 'profit_and_loss', 'cash_flow_report'}

        for xmlid in searchable | not_searchable:
            report = self.env.ref('jkm_full_accounting.%s' % xmlid)
            with self.subTest(report=xmlid):
                payload = self.env['account.report'].get_report_data(report.id, {})
                self.assertEqual(
                    payload['report']['search_bar'], xmlid in searchable,
                    "%s offers the wrong search availability" % xmlid,
                )

    def test_search_keeps_matches_in_context(self):
        """A match is shown with the rows it sits under, not as an orphan."""
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.company_data['default_account_receivable'].id,
                        'debit': 45.0, 'credit': 0.0, 'partner_id': self.partner_a.id}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': 45.0}),
            ],
        })
        move.action_post()

        report = self.env['account.report']
        ledger = self.env.ref('jkm_full_accounting.partner_ledger_report')
        payload = report.get_report_data(ledger.id, {'search': self.partner_a.name})
        names = [l['name'] for l in payload['lines']]

        self.assertIn(self.partner_a.display_name, names)
        # The report heading it sits under survives the filter.
        self.assertIn('Partner Ledger', names)

    def test_search_excludes_non_matching_rows(self):
        other = self.env['res.partner'].create({'name': 'Zzz Excluded Partner'})
        for partner, amount in ((self.partner_a, 40.0), (other, 80.0)):
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'date': fields.Date.context_today(self.env['account.report']),
                'journal_id': self.company_data['default_journal_misc'].id,
                'line_ids': [
                    (0, 0, {'account_id': self.company_data['default_account_receivable'].id,
                            'debit': amount, 'credit': 0.0, 'partner_id': partner.id}),
                    (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                            'debit': 0.0, 'credit': amount}),
                ],
            })
            move.action_post()

        ledger = self.env.ref('jkm_full_accounting.partner_ledger_report')
        payload = self.env['account.report'].get_report_data(
            ledger.id, {'search': 'Zzz Excluded'},
        )
        names = [l['name'] for l in payload['lines']]
        self.assertIn(other.display_name, names)
        self.assertNotIn(self.partner_a.display_name, names)

    def test_empty_search_returns_the_whole_report(self):
        ledger = self.env.ref('jkm_full_accounting.partner_ledger_report')
        full = self.env['account.report'].get_report_data(ledger.id, {})
        blank = self.env['account.report'].get_report_data(ledger.id, {'search': '   '})
        self.assertEqual(len(blank['lines']), len(full['lines']))

    def test_search_returns_the_match_folded(self):
        """A match comes back closed; opening it is the reader's move."""
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.company_data['default_account_receivable'].id,
                        'debit': 55.0, 'credit': 0.0, 'partner_id': self.partner_a.id}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': 55.0}),
            ],
        })
        move.action_post()

        ledger = self.env.ref('jkm_full_accounting.partner_ledger_report')
        payload = self.env['account.report'].get_report_data(
            ledger.id, {'search': self.partner_a.name},
        )

        names = [l['name'] for l in payload['lines']]
        self.assertIn(self.partner_a.display_name, names)

        partner_line = next(l for l in payload['lines'] if l['name'] == self.partner_a.display_name)
        self.assertFalse(partner_line['unfolded'], "The match should come back folded")
        self.assertFalse(
            [l for l in payload['lines'] if l.get('caret_options') == 'account.move.line'],
            "Records should stay hidden until the row is opened",
        )

        # Opening the matched row reveals its records, search still applied.
        opened = self.env['account.report'].get_report_data(ledger.id, {
            'search': self.partner_a.name,
            'unfolded_lines': [partner_line['id']],
        })
        self.assertTrue(
            [l for l in opened['lines'] if l.get('caret_options') == 'account.move.line'],
            "Opening the match did not reveal its records",
        )
        # Other partners are still filtered out.
        self.assertEqual(
            {l['name'] for l in opened['lines'] if l.get('caret_options') == 'res.partner'},
            {self.partner_a.display_name},
        )

    def test_search_folds_matches_on_every_report(self):
        """The narrowing applies to all reports, not just the partner ledger."""
        assets = self.company_data['default_account_assets']
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': assets.id, 'debit': 65.0, 'credit': 0.0}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': 65.0}),
            ],
        })
        move.action_post()

        ledger = self.env.ref('jkm_full_accounting.general_ledger_report')
        payload = self.env['account.report'].get_report_data(ledger.id, {'search': assets.code})
        names = [l['name'] for l in payload['lines']]

        self.assertTrue(any(n.startswith(assets.code) for n in names))
        self.assertFalse(
            [l for l in payload['lines'] if l.get('caret_options') == 'account.move.line'],
            "The matched account should stay folded",
        )
        # Accounts that do not match are left out.
        revenue = self.company_data['default_account_revenue']
        self.assertFalse([n for n in names if n.startswith(revenue.code)])


@tagged('post_install', '-at_install')
class TestAgedBalanceLayout(AccountTestInvoicingCommon):
    """Ageing is only checkable against the invoices behind it."""

    def _invoice(self, days_overdue, amount):
        """Post a receivable entry due ``days_overdue`` days ago.

        The entry itself is dated today - an invoice falling due next week was
        still issued already, and dating the move forward would put it outside
        the report entirely.
        """
        today = fields.Date.context_today(self.env['account.report'])
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': today,
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.company_data['default_account_receivable'].id,
                        'debit': amount, 'credit': 0.0, 'partner_id': self.partner_a.id,
                        'date_maturity': today - timedelta(days=days_overdue)}),
                (0, 0, {'account_id': self.company_data['default_account_revenue'].id,
                        'debit': 0.0, 'credit': amount}),
            ],
        })
        move.action_post()
        return move

    def test_not_yet_due_sits_at_date(self):
        """Outstanding but not late belongs in At Date, not an overdue bucket."""
        self._invoice(-10, 300.0)  # falls due in ten days
        report = self.env.ref('jkm_full_accounting.aged_receivable_report')
        options = report._get_options({})
        labels = [c['expression_label'] for c in options['columns']]

        line = next(
            l for l in report._get_lines(options) if l.get('caret_options') == 'res.partner'
        )
        values = dict(zip(labels, [c['no_format'] for c in line['columns']]))
        self.assertAlmostEqual(values['at_date'], 300.0, places=2)
        self.assertFalse(values.get('period0'))

    def test_partner_expands_into_its_invoices(self):
        self._invoice(45, 600.0)
        self._invoice(-5, 150.0)

        report = self.env.ref('jkm_full_accounting.aged_receivable_report')
        options = report._get_options({'unfold_all': True})
        labels = [c['expression_label'] for c in options['columns']]
        lines = report._get_lines(options)

        items = [l for l in lines if l.get('caret_options') == 'account.move.line']
        self.assertEqual(len(items), 2, "Partner did not expand into its invoices")

        # Each entry shows its invoice date and lands in one bucket only.
        for item in items:
            values = dict(zip(labels, [c['no_format'] for c in item['columns']]))
            self.assertTrue(values['invoice_date'], "Entry is missing its invoice date")
            filled = [
                label for label in ('at_date', 'period0', 'period1', 'period2', 'period3', 'period4')
                if values.get(label)
            ]
            self.assertEqual(len(filled), 1, "An entry should occupy a single ageing bucket")

    def test_partner_row_sums_its_invoices(self):
        self._invoice(45, 600.0)
        self._invoice(-5, 150.0)

        report = self.env.ref('jkm_full_accounting.aged_receivable_report')
        options = report._get_options({})
        labels = [c['expression_label'] for c in options['columns']]
        line = next(
            l for l in report._get_lines(options) if l.get('caret_options') == 'res.partner'
        )
        values = dict(zip(labels, [c['no_format'] for c in line['columns']]))
        self.assertAlmostEqual(values['period1'], 600.0, places=2)
        self.assertAlmostEqual(values['at_date'], 150.0, places=2)
        self.assertAlmostEqual(values['total'], 750.0, places=2)


@tagged('post_install', '-at_install')
class TestCashFlowStatement(AccountTestInvoicingCommon):
    """Opening plus the period's movement must land on the closing balance."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env.ref('jkm_full_accounting.cash_flow_report')
        cls.bank = cls.env['account.account'].search([
            ('account_type', '=', 'asset_cash'),
            ('company_ids', 'in', cls.env.company.ids),
        ], limit=1)

    def _post(self, counterpart, amount, date=None):
        """Move ``amount`` into the bank against ``counterpart``."""
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': date or fields.Date.context_today(self.env['account.report']),
            'journal_id': self.company_data['default_journal_misc'].id,
            'line_ids': [
                (0, 0, {'account_id': self.bank.id, 'debit': max(amount, 0), 'credit': max(-amount, 0)}),
                (0, 0, {'account_id': counterpart.id, 'debit': max(-amount, 0), 'credit': max(amount, 0)}),
            ],
        })
        move.action_post()
        return move

    def _values(self, options=None):
        options = options or self.report._get_options({})
        return {
            l['name']: l['columns'][0]['no_format']
            for l in self.report._get_lines(options)
        }

    def test_statement_reconciles(self):
        """Closing must equal opening plus the net increase, or the statement
        is telling the reader something that is not true."""
        self._post(self.company_data['default_account_revenue'], 900.0)
        self._post(self.company_data['default_account_expense'], -250.0)

        values = self._values()
        opening = values['Cash and cash equivalents, beginning of period']
        net = values['Net increase in cash and cash equivalents']
        closing = values['Cash and cash equivalents, closing balance']
        self.assertAlmostEqual(opening + net, closing, places=2)
        self.assertAlmostEqual(net, 650.0, places=2)

    def test_opening_balance_carries_forward(self):
        today = fields.Date.context_today(self.env['account.report'])
        self._post(self.company_data['default_account_revenue'], 400.0,
                   date=today - timedelta(days=90))
        self._post(self.company_data['default_account_revenue'], 100.0)

        values = self._values(self.report._get_options({'date': {'filter': 'this_month'}}))
        self.assertAlmostEqual(
            values['Cash and cash equivalents, beginning of period'], 400.0, places=2,
        )
        self.assertAlmostEqual(values['Net increase in cash and cash equivalents'], 100.0, places=2)
        self.assertAlmostEqual(
            values['Cash and cash equivalents, closing balance'], 500.0, places=2,
        )

    def test_flows_are_classified_by_their_counterpart(self):
        """Cash never says what it was for; the other side of the entry does."""
        self._post(self.company_data['default_account_revenue'], 900.0)
        self._post(self.company_data['default_account_receivable'], 300.0)

        values = self._values()
        self.assertAlmostEqual(values['Cash received from operating activities'], 900.0, places=2)
        self.assertAlmostEqual(values['Advance Payments received from customers'], 300.0, places=2)

    def test_statement_reads_in_order(self):
        names = list(self._values())
        expected = [
            'Cash and cash equivalents, beginning of period',
            'Net increase in cash and cash equivalents',
            'Cash flows from operating activities',
            'Cash flows from investing & extraordinary activities',
            'Cash flows from financing activities',
            'Cash flows from unclassified activities',
            'Cash and cash equivalents, closing balance',
        ]
        positions = [names.index(n) for n in expected]
        self.assertEqual(positions, sorted(positions), "Cash flow sections are out of order")


@tagged('post_install', '-at_install')
class TestTaxReport(AccountTestInvoicingCommon):
    """A tax return reads sales and purchases as positive amounts."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env.ref('jkm_full_accounting.tax_audit_report')
        # Own taxes rather than the chart's defaults, which a template may not
        # define at all - the report would then be tested against no data.
        # Names must not collide with the chart template's own taxes.
        cls.sale_tax = cls.env['account.tax'].create({
            'name': 'JKM Sale 15%', 'amount': 15.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'company_id': cls.env.company.id,
        })
        cls.purchase_tax = cls.env['account.tax'].create({
            'name': 'JKM Purchase 15%', 'amount': 15.0, 'amount_type': 'percent',
            'type_tax_use': 'purchase', 'company_id': cls.env.company.id,
        })

    def _invoice(self, move_type, tax, amount):
        move = self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': self.partner_a.id,
            'invoice_date': fields.Date.context_today(self.env['account.report']),
            'date': fields.Date.context_today(self.env['account.report']),
            'invoice_line_ids': [(0, 0, {
                'name': 'line',
                'quantity': 1,
                'price_unit': amount,
                'tax_ids': [(6, 0, tax.ids)],
            })],
        })
        move.action_post()
        return move

    def _values(self):
        options = self.report._get_options({})
        labels = [c['expression_label'] for c in options['columns']]
        return options, [
            (l['name'], dict(zip(labels, [c['no_format'] for c in l['columns']])))
            for l in self.report._get_lines(options)
        ]

    def test_columns_are_net_and_tax(self):
        options = self.report._get_options({})
        self.assertEqual(
            [c['expression_label'] for c in options['columns']], ['net', 'tax'],
        )
        self.assertEqual([c['name'] for c in options['columns']], ['Net', 'Tax'])

    def test_sales_tax_is_reported_positive(self):
        """Tax collected sits as a credit; a return states it as an amount owed."""
        self._invoice('out_invoice', self.sale_tax, 1000.0)

        _options, rows = self._values()
        names = [name for name, _v in rows]
        self.assertIn('Sales', names)
        self.assertIn('Total Sales', names)

        totals = dict(rows)['Total Sales']
        self.assertAlmostEqual(totals['tax'], 150.0, places=2)

    def test_purchase_tax_is_reported_positive(self):
        self._invoice('in_invoice', self.purchase_tax, 500.0)

        _options, rows = self._values()
        names = [name for name, _v in rows]
        self.assertIn('Purchases', names)
        self.assertIn('Total Purchases', names)
        self.assertAlmostEqual(dict(rows)['Total Purchases']['tax'], 75.0, places=2)

    def test_net_is_the_amount_the_tax_was_charged_on(self):
        self._invoice('out_invoice', self.sale_tax, 1000.0)
        _options, rows = self._values()
        tax_row = next(v for name, v in rows if name.startswith('JKM Sale'))
        self.assertAlmostEqual(tax_row['net'], 1000.0, places=2)
        self.assertAlmostEqual(tax_row['tax'], 150.0, places=2)

    def test_section_total_sums_its_taxes(self):
        self._invoice('out_invoice', self.sale_tax, 1000.0)
        _options, rows = self._values()

        by_name = dict(rows)
        tax_rows = [
            values for name, values in rows
            if name not in ('Sales', 'Total Sales', 'Purchases', 'Total Purchases')
        ]
        self.assertTrue(tax_rows, "No individual tax rows were produced")
        self.assertAlmostEqual(
            by_name['Total Sales']['tax'],
            sum(v['tax'] or 0.0 for v in tax_rows), places=2,
        )

    def test_audit_opens_the_entries_behind_a_tax(self):
        """Audit must show the tax lines and the lines the tax was charged on."""
        invoice = self._invoice('out_invoice', self.sale_tax, 1000.0)

        options = self.report._get_options({})
        tax_line = next(
            l for l in self.report._get_lines(options)
            if l.get('caret_options') == 'account.tax'
        )
        action = self.report.action_open_tax_audit(tax_line['id'], options)
        self.assertEqual(action['res_model'], 'account.move.line')
        self.assertEqual(action['context'].get('search_default_group_by_account'), 1)

        found = self.env['account.move.line'].search(action['domain'])
        self.assertTrue(found, "Audit returned no journal items")

        # The tax line itself...
        self.assertTrue(
            found.filtered(lambda l: l.tax_line_id == self.sale_tax),
            "Audit is missing the tax lines",
        )
        # ...and the base it was charged on.
        self.assertTrue(
            found.filtered(lambda l: self.sale_tax in l.tax_ids),
            "Audit is missing the lines the tax was charged on",
        )
        self.assertEqual(found.move_id, invoice)

    def test_audit_rejects_non_tax_lines(self):
        self._invoice('out_invoice', self.sale_tax, 1000.0)
        options = self.report._get_options({})
        section = next(l for l in self.report._get_lines(options) if l['name'] == 'Sales')
        self.assertFalse(self.report.action_open_tax_audit(section['id'], options))
