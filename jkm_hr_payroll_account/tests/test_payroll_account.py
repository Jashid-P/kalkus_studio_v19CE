# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestPayrollAccount(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data['company']
        cls.env.user.group_ids = [(4, cls.env.ref('jkm_hr_payroll.group_hr_payroll_manager').id)]
        cls.env.user.tz = 'UTC'
        cls.calendar = cls.company.resource_calendar_id
        cls.calendar.tz = 'UTC'
        cls.structure = cls.env.ref('jkm_hr_payroll.structure_regular_pay').with_company(cls.company)
        cls.journal = cls.structure.journal_id
        cls.net_rule = cls.structure.rule_ids.filtered(lambda r: r.code == 'NET')
        cls.basic_rule = cls.structure.rule_ids.filtered(lambda r: r.code == 'BASIC')
        cls.employee = cls._create_employee('Alice Ledger', 3000.0)
        cls.date_from = date(2026, 3, 1)
        cls.date_to = date(2026, 3, 31)

    @classmethod
    def _create_employee(cls, name, wage):
        return cls.env['hr.employee'].create({
            'name': name,
            'company_id': cls.company.id,
            'resource_calendar_id': cls.calendar.id,
            'tz': 'UTC',
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
            'structure_type_id': cls.env.ref('hr.structure_type_employee').id,
            'wage': wage,
        })

    def _create_payslip(self, employee=None, **vals):
        return self.env['hr.payslip'].create({
            'employee_id': (employee or self.employee).id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            **vals,
        })

    def _validate(self, payslips):
        payslips.with_context(payslip_generate_pdf=False).action_payslip_done()

    def _move_balances(self, move):
        return {
            (line.account_id, line.partner_id): line.balance
            for line in move.line_ids
        }

    # ------------------------------------------------------------------

    def test_install_configuration(self):
        self.assertTrue(self.journal)
        self.assertEqual(self.journal.code, 'SLR')
        self.assertEqual(self.journal.type, 'general')
        self.assertTrue(self.basic_rule.account_debit)
        self.assertEqual(self.basic_rule.account_debit.account_type, 'expense')
        self.assertTrue(self.net_rule.account_credit.reconcile)
        self.assertTrue(self.net_rule.employee_move_line)

    def test_validate_creates_draft_entry(self):
        payslip = self._create_payslip()
        self._validate(payslip)
        move = payslip.move_id
        self.assertTrue(move)
        self.assertEqual(move.state, 'draft')
        self.assertEqual(move.journal_id, self.journal)
        self.assertEqual(move.date, date(2026, 3, 31))
        self.assertEqual(payslip.date, date(2026, 3, 31))
        self.assertEqual(move.payslip_ids, payslip)
        partner = self.employee.work_contact_id
        self.assertEqual(self._move_balances(move), {
            (self.basic_rule.account_debit, self.env['res.partner']): 3000.0,
            (self.net_rule.account_credit, partner): -3000.0,
        })

    def test_deduction_and_bonus(self):
        payslip = self._create_payslip()
        payslip.input_line_ids = [
            (0, 0, {'input_type_id': self.env.ref('jkm_hr_payroll.input_bonus').id, 'amount': 500.0}),
            (0, 0, {'input_type_id': self.env.ref('jkm_hr_payroll.input_deduction').id, 'amount': 200.0}),
        ]
        payslip.compute_sheet()
        self._validate(payslip)
        move = payslip.move_id
        self.assertAlmostEqual(sum(move.line_ids.mapped('debit')), 3500.0)
        self.assertAlmostEqual(sum(move.line_ids.mapped('credit')), 3500.0)
        net_line = move.line_ids.filtered(lambda l: l.partner_id == self.employee.work_contact_id)
        self.assertAlmostEqual(net_line.credit, 3300.0)
        deduction = move.line_ids.filtered(lambda l: l.name == 'Deduction')
        self.assertAlmostEqual(deduction.credit, 200.0)

    def test_unbalanced_entry_uses_journal_account(self):
        self.basic_rule.account_debit = False
        payslip = self._create_payslip()
        self._validate(payslip)
        adjustment = payslip.move_id.line_ids.filtered(lambda l: l.name == 'Adjustment Entry')
        self.assertEqual(adjustment.account_id, self.journal.default_account_id)
        self.assertAlmostEqual(adjustment.debit, 3000.0)

    def test_no_journal_no_entry(self):
        self.structure.journal_id = False
        payslip = self._create_payslip()
        self._validate(payslip)
        self.assertEqual(payslip.state, 'validated')
        self.assertFalse(payslip.move_id)

    def test_cancel_and_draft_remove_entry(self):
        payslip = self._create_payslip()
        self._validate(payslip)
        move = payslip.move_id
        payslip.action_payslip_draft()
        self.assertFalse(payslip.move_id)
        self.assertFalse(move.exists())

        self._validate(payslip)
        posted = payslip.move_id
        posted.action_post()
        payslip.action_payslip_cancel()
        self.assertFalse(payslip.move_id)
        # Odoo deletes an unprotected posted entry, and reverses it otherwise
        # (lock date, audit trail...): either way nothing stays booked.
        if posted.exists():
            self.assertEqual(posted.payment_state, 'reversed')

    def test_refund_reverses_entry(self):
        payslip = self._create_payslip()
        self._validate(payslip)
        refund = self.env['hr.payslip'].search(payslip.refund_sheet()['domain'])
        self._validate(refund)
        self.assertEqual(self._move_balances(refund.move_id), {
            key: -balance for key, balance in self._move_balances(payslip.move_id).items()
        })

    def test_batch_single_entry(self):
        self.company.batch_payroll_move_lines = True
        second = self._create_employee('Bruno Ledger', 2000.0)
        run = self.env['hr.payslip.run'].create({
            'name': 'March', 'date_start': self.date_from, 'date_end': self.date_to,
            'company_id': self.company.id,
        })
        slips = self._create_payslip(payslip_run_id=run.id) | self._create_payslip(second, payslip_run_id=run.id)
        slips.compute_sheet()
        # validating only one payslip of the batch does not create the entry yet
        self._validate(slips[0])
        self.assertFalse(slips[0].move_id)
        self._validate(slips[1])
        self.assertEqual(len(slips.move_id), 1)
        self.assertEqual(run.move_id, slips.move_id)
        move = run.move_id
        self.assertEqual(len(move.line_ids), 2)  # merged, no employee partner
        self.assertAlmostEqual(sum(move.line_ids.mapped('debit')), 5000.0)
        with self.assertRaises(UserError):
            slips[0].action_payslip_draft()
        run.action_draft()
        self.assertFalse(move.exists())
        self.assertTrue(all(slip.state == 'draft' for slip in slips))

    def test_register_payment_marks_paid(self):
        payslip = self._create_payslip()
        self._validate(payslip)
        self.assertFalse(payslip.has_net_to_pay)  # draft entry: nothing to pay yet
        payslip.move_id.action_post()
        self.assertTrue(payslip.has_net_to_pay)
        action = payslip.action_register_payment()
        wizard = self.env['account.payment.register'].with_context(action['context']).create({
            'journal_id': self.company_data['default_journal_bank'].id,
        })
        self.assertAlmostEqual(wizard.amount, 3000.0)
        wizard.action_create_payments()
        self.assertEqual(payslip.state, 'paid')
        self.assertFalse(payslip.has_net_to_pay)
