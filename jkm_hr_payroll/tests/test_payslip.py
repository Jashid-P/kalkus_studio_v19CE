# -*- coding: utf-8 -*-
from datetime import date, datetime

from odoo.exceptions import UserError
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPayslip(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.calendar = cls.env.ref('resource.resource_calendar_std')
        cls.calendar.tz = 'UTC'
        cls.env.user.tz = 'UTC'
        cls.structure_type = cls.env.ref('hr.structure_type_employee')
        cls.structure = cls.env.ref('jkm_hr_payroll.structure_regular_pay')
        cls.unpaid_type = cls.env.ref('hr_work_entry.work_entry_type_unpaid_leave')

        cls.employee = cls._create_employee('Alice Payroll', 3000.0, date(2025, 1, 1))
        # March 2026: 22 working days, 176 hours on the standard 40h calendar.
        cls.date_from = date(2026, 3, 1)
        cls.date_to = date(2026, 3, 31)

    @classmethod
    def _create_employee(cls, name, wage, contract_start, contract_end=False, structure_type=None, **extra):
        return cls.env['hr.employee'].create({
            'name': name,
            'company_id': cls.company.id,
            'resource_calendar_id': cls.calendar.id,
            'tz': 'UTC',
            'date_version': contract_start,
            'contract_date_start': contract_start,
            'contract_date_end': contract_end,
            'structure_type_id': (structure_type or cls.structure_type).id,
            'wage': wage,
            **extra,
        })

    def _create_payslip(self, employee=None, **vals):
        return self.env['hr.payslip'].create({
            'employee_id': (employee or self.employee).id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            **vals,
        })

    def _line(self, payslip, code):
        return payslip.line_ids.filtered(lambda line: line.code == code)

    # ------------------------------------------------------------------

    def test_defaults(self):
        payslip = self._create_payslip()
        self.assertEqual(payslip.version_id, self.employee.version_id)
        self.assertEqual(payslip.struct_id, self.structure)
        self.assertEqual(payslip.date_to, self.date_to)
        self.assertIn('March 2026', payslip.name)

    def test_full_month(self):
        payslip = self._create_payslip()
        attendance = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == 'WORK100')
        self.assertAlmostEqual(attendance.number_of_hours, 176.0)
        self.assertAlmostEqual(attendance.number_of_days, 22.0)
        self.assertAlmostEqual(attendance.amount, 3000.0)
        payslip.compute_sheet()
        self.assertAlmostEqual(payslip.basic_wage, 3000.0)
        self.assertAlmostEqual(payslip.gross_wage, 3000.0)
        self.assertAlmostEqual(payslip.net_wage, 3000.0)
        self.assertTrue(payslip.number)

    def test_worked_days_filled_when_form_sent_none(self):
        # The form computes worked days before the work entries exist and sends
        # an empty list on save: the payslip must still get its worked days.
        employee = self._create_employee('Nina Form', 5000.0, date(2026, 3, 1))
        payslip = self._create_payslip(employee, worked_days_line_ids=[(5, 0, 0)])
        self.assertTrue(payslip.worked_days_line_ids)
        payslip.worked_days_line_ids.unlink()
        payslip.compute_sheet()
        self.assertAlmostEqual(payslip.basic_wage, 5000.0)
        self.assertAlmostEqual(payslip.net_wage, 5000.0)

    def test_form_save_with_existing_work_entries(self):
        # Work entries already exist: the form builds the worked days before saving
        # and must send their (read-only) type back to the server.
        self.employee.version_id.schedule_pay = 'daily'
        self.employee.version_id.generate_work_entries(date(2026, 3, 2), date(2026, 3, 2))
        form = Form(self.env['hr.payslip'])
        form.employee_id = self.employee
        form.date_from = date(2026, 3, 2)
        self.assertEqual(form.date_to, date(2026, 3, 2))
        payslip = form.save()
        self.assertEqual(payslip.worked_days_line_ids.work_entry_type_id.code, 'WORK100')
        self.assertAlmostEqual(payslip.worked_days_line_ids.number_of_hours, 8.0)

    def test_contract_starts_mid_month(self):
        self.structure.proration_method = 'working_days'
        # Starts Monday 16 March: 12 working days in contract, 10 out of contract.
        employee = self._create_employee('Bob Newcomer', 2200.0, date(2026, 3, 16))
        payslip = self._create_payslip(employee)
        out = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == 'OUT')
        self.assertAlmostEqual(out.number_of_days, 10.0)
        self.assertFalse(out.is_paid)
        payslip.compute_sheet()
        self.assertAlmostEqual(payslip.basic_wage, 2200.0 * 12 / 22, places=2)

    def _create_unpaid_leave(self, employee, day_from, day_to):
        return self.env['resource.calendar.leaves'].create({
            'name': 'Unpaid leave',
            'calendar_id': self.calendar.id,
            'resource_id': employee.resource_id.id,
            'date_from': datetime.combine(day_from, datetime.min.time()),
            'date_to': datetime.combine(day_to, datetime.max.time()).replace(microsecond=0),
            'work_entry_type_id': self.unpaid_type.id,
        })

    def test_unpaid_leave_30_days_basis(self):
        self.assertEqual(self.structure.proration_method, 'fixed_30')
        self._create_unpaid_leave(self.employee, date(2026, 3, 2), date(2026, 3, 3))
        payslip = self._create_payslip()
        payslip.compute_sheet()
        # 2 unpaid days = 2 x 3000 / 30, whatever the number of working days
        self.assertAlmostEqual(payslip.basic_wage, 2800.0)
        attendance = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == 'WORK100')
        self.assertAlmostEqual(attendance.amount, 2800.0)

    def test_compute_sheet_applies_new_proration(self):
        self.structure.proration_method = 'working_days'
        self._create_unpaid_leave(self.employee, date(2026, 3, 2), date(2026, 3, 2))
        payslip = self._create_payslip()
        payslip.compute_sheet()
        self.assertAlmostEqual(payslip.basic_wage, 3000.0 * 21 / 22, places=2)
        self.structure.proration_method = 'fixed_30'
        payslip.compute_sheet()
        self.assertAlmostEqual(payslip.basic_wage, 2900.0)

    def test_full_month_30_days_basis_february(self):
        payslip = self._create_payslip(date_from=date(2026, 2, 1), date_to=date(2026, 2, 28))
        payslip.compute_sheet()
        self.assertAlmostEqual(payslip.basic_wage, 3000.0)

    def test_contract_starts_mid_month_30_days_basis(self):
        # Starts 16 March: 15 calendar days out of contract = 15 x 3000 / 30.
        employee = self._create_employee('Olga Newcomer', 3000.0, date(2026, 3, 16))
        payslip = self._create_payslip(employee)
        out = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == 'OUT')
        self.assertAlmostEqual(out.number_of_days, 15.0)
        payslip.compute_sheet()
        self.assertAlmostEqual(payslip.basic_wage, 1500.0)

    def test_unpaid_leave(self):
        self.structure.proration_method = 'working_days'
        self.env['resource.calendar.leaves'].create({
            'name': 'Unpaid leave',
            'calendar_id': self.calendar.id,
            'resource_id': self.employee.resource_id.id,
            'date_from': datetime(2026, 3, 2, 0, 0),
            'date_to': datetime(2026, 3, 3, 23, 59),
            'work_entry_type_id': self.unpaid_type.id,
        })
        payslip = self._create_payslip()
        unpaid = payslip.worked_days_line_ids.filtered(lambda wd: wd.work_entry_type_id == self.unpaid_type)
        self.assertAlmostEqual(unpaid.number_of_days, 2.0)
        self.assertFalse(unpaid.is_paid)
        payslip.compute_sheet()
        self.assertAlmostEqual(payslip.basic_wage, 3000.0 * 20 / 22, places=2)

    def test_inputs(self):
        payslip = self._create_payslip()
        payslip.input_line_ids = [
            (0, 0, {'input_type_id': self.env.ref('jkm_hr_payroll.input_bonus').id, 'amount': 500.0}),
            (0, 0, {'input_type_id': self.env.ref('jkm_hr_payroll.input_deduction').id, 'amount': 200.0}),
            (0, 0, {'input_type_id': self.env.ref('jkm_hr_payroll.input_deduction').id, 'amount': 50.0}),
        ]
        payslip.compute_sheet()
        self.assertAlmostEqual(payslip.gross_wage, 3500.0)
        self.assertAlmostEqual(self._line(payslip, 'DEDUCTION').total, -250.0)
        self.assertAlmostEqual(payslip.net_wage, 3250.0)

    def test_python_rule_with_parameter_and_legacy_syntax(self):
        self.env['hr.rule.parameter'].create({
            'name': 'Test tax',
            'code': 'jkm_test_tax',
            'parameter_version_ids': [(0, 0, {'date_from': date(2026, 1, 1), 'parameter_value': '0.2'})],
        })
        self.env['hr.salary.rule'].create({
            'name': 'Income Tax',
            'code': 'TAX',
            'sequence': 170,
            'struct_id': self.structure.id,
            'category_id': self.env.ref('jkm_hr_payroll.DED').id,
            'amount_select': 'code',
            # legacy attribute access on categories must keep working
            'amount_python_compute': "result = -categories.GROSS * payslip._rule_parameter('jkm_test_tax')",
        })
        payslip = self._create_payslip()
        payslip.compute_sheet()
        self.assertAlmostEqual(self._line(payslip, 'TAX').total, -600.0)
        self.assertAlmostEqual(payslip.net_wage, 2400.0)

    def test_percentage_and_range_rules(self):
        self.env['hr.salary.rule'].create({
            'name': 'Housing Allowance',
            'code': 'HRA',
            'sequence': 10,
            'struct_id': self.structure.id,
            'category_id': self.env.ref('jkm_hr_payroll.ALW').id,
            'amount_select': 'percentage',
            'amount_percentage_base': 'BASIC',
            'amount_percentage': 25.0,
            'condition_select': 'range',
            'condition_range': 'version.wage',
            'condition_range_min': 1000,
            'condition_range_max': 5000,
        })
        payslip = self._create_payslip()
        payslip.compute_sheet()
        self.assertAlmostEqual(self._line(payslip, 'HRA').total, 750.0)
        self.assertAlmostEqual(payslip.gross_wage, 3750.0)

    def test_validate_and_pay(self):
        payslip = self._create_payslip()
        payslip.with_context(payslip_generate_pdf=False).action_payslip_done()
        self.assertEqual(payslip.state, 'validated')
        self.assertTrue(payslip.line_ids)
        work_entries = self.env['hr.work.entry'].search([
            ('employee_id', '=', self.employee.id),
            ('date', '>=', self.date_from), ('date', '<=', self.date_to)])
        self.assertTrue(work_entries)
        self.assertTrue(all(we.state == 'validated' for we in work_entries))
        with self.assertRaises(UserError):
            payslip.unlink()

        payslip.action_payslip_paid()
        self.assertEqual(payslip.state, 'paid')
        self.assertTrue(payslip.paid_date)

        payslip.action_payslip_unpaid()
        payslip.action_payslip_draft()
        self.assertEqual(payslip.state, 'draft')
        self.assertTrue(all(we.state == 'draft' for we in work_entries))

    def test_refund(self):
        payslip = self._create_payslip()
        payslip.with_context(payslip_generate_pdf=False).action_payslip_done()
        action = payslip.refund_sheet()
        refund = self.env['hr.payslip'].search(action['domain'])
        self.assertTrue(refund.credit_note)
        self.assertEqual(refund.origin_payslip_id, payslip)
        self.assertAlmostEqual(refund.net_wage, -3000.0)
        self.assertEqual(payslip.refund_count, 1)
        # recomputing a refund keeps it negative
        refund.compute_sheet()
        self.assertAlmostEqual(refund.net_wage, -3000.0)

    def test_salary_attachment(self):
        attachment = self.env['hr.salary.attachment'].create({
            'employee_id': self.employee.id,
            'description': 'Court order',
            'other_input_type_id': self.env.ref('jkm_hr_payroll.input_attachment_salary').id,
            'date_start': date(2026, 1, 1),
            'monthly_amount': 400.0,
            'total_amount': 600.0,
        })
        march = self._create_payslip()
        march.compute_sheet()
        self.assertAlmostEqual(self._line(march, 'ATTACH_SALARY').total, -400.0)
        self.assertAlmostEqual(march.net_wage, 2600.0)
        march.with_context(payslip_generate_pdf=False).action_payslip_done()
        self.assertAlmostEqual(attachment.paid_amount, 400.0)
        self.assertAlmostEqual(attachment.remaining_amount, 200.0)
        self.assertEqual(attachment.state, 'open')

        april = self._create_payslip(date_from=date(2026, 4, 1), date_to=date(2026, 4, 30))
        april.compute_sheet()
        self.assertAlmostEqual(self._line(april, 'ATTACH_SALARY').total, -200.0)
        april.with_context(payslip_generate_pdf=False).action_payslip_done()
        self.assertEqual(attachment.state, 'close')

        # resetting the payslip reopens the attachment
        april.action_payslip_draft()
        self.assertEqual(attachment.state, 'open')

    def test_hourly_wage(self):
        worker_type = self.env.ref('hr.structure_type_worker')
        worker = self._create_employee('Walter Hourly', 0.0, date(2025, 1, 1), structure_type=worker_type)
        worker.version_id.write({'hourly_wage': 20.0})
        self.assertEqual(worker.version_id.wage_type, 'hourly')
        payslip = self._create_payslip(worker)
        self.assertEqual(payslip.struct_id, self.env.ref('jkm_hr_payroll.structure_worker_pay'))
        payslip.compute_sheet()
        self.assertAlmostEqual(payslip.basic_wage, 176 * 20.0)

    def test_no_contract(self):
        employee = self._create_employee('Carl Future', 1000.0, date(2027, 1, 1))
        payslip = self._create_payslip(employee)
        self.assertFalse(payslip.version_id)
        self.assertTrue(payslip.warning_message)
        with self.assertRaises(UserError):
            payslip.compute_sheet()

    def test_batch_generation(self):
        second = self._create_employee('Dora Batch', 4000.0, date(2025, 6, 1))
        run = self.env['hr.payslip.run'].create({
            'name': 'March 2026',
            'date_start': self.date_from,
            'date_end': self.date_to,
        })
        wizard = self.env['hr.payslip.employees'].with_context(
            active_id=run.id, active_model='hr.payslip.run').create({})
        wizard.employee_ids = self.employee | second
        wizard.compute_sheet()
        self.assertEqual(run.payslip_count, 2)
        self.assertEqual(run.state, '01_ready')
        self.assertAlmostEqual(run.net_sum, 7000.0)

        run.with_context(payslip_generate_pdf=False).action_validate()
        self.assertEqual(run.state, '02_close')
        run.action_paid()
        self.assertEqual(run.state, '03_paid')

    def test_schedule_pay(self):
        StructureType = self.env['hr.payroll.structure.type']
        self.assertEqual(StructureType._get_schedule_period_end('weekly', date(2026, 3, 2)), date(2026, 3, 8))
        self.assertEqual(StructureType._get_schedule_period_end('semi-monthly', date(2026, 2, 16)), date(2026, 2, 28))
        self.assertEqual(StructureType._get_schedule_period_end('quarterly', date(2026, 1, 1)), date(2026, 3, 31))
        self.employee.version_id.schedule_pay = 'weekly'
        payslip = self.env['hr.payslip'].create({'employee_id': self.employee.id, 'date_from': date(2026, 3, 2)})
        self.assertEqual(payslip.date_to, date(2026, 3, 8))

    def test_period_start_follows_schedule(self):
        StructureType = self.env['hr.payroll.structure.type']
        day = date(2026, 8, 20)  # a Thursday
        expected = {
            'daily': (date(2026, 8, 20), date(2026, 8, 20)),
            'weekly': (date(2026, 8, 17), date(2026, 8, 23)),
            'bi-weekly': (date(2026, 8, 17), date(2026, 8, 30)),
            'semi-monthly': (date(2026, 8, 16), date(2026, 8, 31)),
            'monthly': (date(2026, 8, 1), date(2026, 8, 31)),
            'bi-monthly': (date(2026, 7, 1), date(2026, 8, 31)),
            'quarterly': (date(2026, 7, 1), date(2026, 9, 30)),
            'semi-annually': (date(2026, 7, 1), date(2026, 12, 31)),
            'annually': (date(2026, 1, 1), date(2026, 12, 31)),
        }
        for schedule, (start, stop) in expected.items():
            period_start = StructureType._get_schedule_period_start(schedule, day)
            self.assertEqual(period_start, start, schedule)
            self.assertEqual(StructureType._get_schedule_period_end(schedule, period_start), stop, schedule)

    def test_payslip_period_defaults_to_schedule(self):
        self.employee.version_id.schedule_pay = 'weekly'
        payslip = self.env['hr.payslip'].create({'employee_id': self.employee.id})
        self.assertEqual(payslip.date_from.weekday(), 0)
        self.assertEqual((payslip.date_to - payslip.date_from).days, 6)
        self.assertEqual(len(payslip.worked_days_line_ids), 1)
        self.assertAlmostEqual(payslip.worked_days_line_ids.number_of_days, 5.0)

    def test_quarterly_30_days_basis(self):
        # Joins 16 March: 74 calendar days of the quarter out of contract = 74 x 9000 / 90.
        employee = self._create_employee('Quinn Quarterly', 9000.0, date(2026, 3, 16))
        employee.version_id.schedule_pay = 'quarterly'
        payslip = self._create_payslip(employee, date_from=date(2026, 1, 1), date_to=date(2026, 3, 31))
        out = payslip.worked_days_line_ids.filtered(lambda wd: wd.code == 'OUT')
        self.assertAlmostEqual(out.number_of_days, 74.0)
        payslip.compute_sheet()
        self.assertAlmostEqual(payslip.basic_wage, 1600.0)

    def test_annual_unpaid_leave_30_days_basis(self):
        self.employee.version_id.schedule_pay = 'annually'
        self._create_unpaid_leave(self.employee, date(2026, 3, 2), date(2026, 3, 4))
        payslip = self._create_payslip(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31))
        payslip.compute_sheet()
        # 3 unpaid days on a 360-day year
        self.assertAlmostEqual(payslip.basic_wage, 3000.0 - 3 * 3000.0 / 360, places=2)

    def test_weekly_prorated_on_working_days(self):
        self.employee.version_id.schedule_pay = 'weekly'
        self._create_unpaid_leave(self.employee, date(2026, 3, 3), date(2026, 3, 3))
        payslip = self._create_payslip(date_from=date(2026, 3, 2), date_to=date(2026, 3, 8))
        payslip.compute_sheet()
        # weekly wage 3000 over 5 working days, 1 unpaid
        self.assertAlmostEqual(payslip.basic_wage, 2400.0)

    def test_new_structure_default_rules(self):
        structure = self.env['hr.payroll.structure'].create({
            'name': 'Bonus Pay', 'type_id': self.structure_type.id})
        self.assertEqual(set(structure.rule_ids.mapped('code')), {'BASIC', 'GROSS', 'NET'})
        copy = structure.copy()
        self.assertEqual(set(copy.rule_ids.mapped('code')), {'BASIC', 'GROSS', 'NET'})
        self.assertIn('Basic Salary', copy.rule_ids.mapped('name'))

    def test_print_report(self):
        payslip = self._create_payslip()
        payslip.with_context(payslip_generate_pdf=False).action_payslip_done()
        html = self.env['ir.actions.report']._render_qweb_html(
            'jkm_hr_payroll.report_payslip', payslip.ids)[0].decode()
        self.assertIn('Net to Pay', html)
        self.assertIn(payslip.number, html)
