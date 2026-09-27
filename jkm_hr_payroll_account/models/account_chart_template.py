# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# Default accounting of the salary rules shipped by jkm_hr_payroll:
# rule code -> (field, account role). Deductions carry negative amounts, so their
# *debit* account ends up credited.
DEFAULT_RULE_ACCOUNTS = {
    'BASIC': ('account_debit', 'expense'),
    'BONUS': ('account_debit', 'bonus'),
    'REIMBURSEMENT': ('account_debit', 'expense'),
    'ATTACH_SALARY': ('account_debit', 'deduction'),
    'ASSIG_SALARY': ('account_debit', 'deduction'),
    'CHILD_SUPPORT': ('account_debit', 'deduction'),
    'DEDUCTION': ('account_debit', 'deduction'),
    'ADVANCE': ('account_debit', 'advance'),
    'NET': ('account_credit', 'payable'),
}
SPLIT_RULES = ('ATTACH_SALARY', 'ASSIG_SALARY', 'CHILD_SUPPORT', 'DEDUCTION', 'REIMBURSEMENT', 'ADVANCE')


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    def _post_load_data(self, template_code, company, template_data):
        super()._post_load_data(template_code, company, template_data)
        self.with_company(company)._jkm_configure_payroll_accounting(company)

    @api.model
    def _jkm_find_account(self, company, account_types, names, reconcile=None):
        Account = self.env['account.account'].with_company(company)
        base = [*Account._check_company_domain(company), ('account_type', 'in', account_types), ('active', '=', True)]
        if reconcile is not None:
            base.append(('reconcile', '=', reconcile))
        for name in names:
            account = Account.search(base + [('name', 'ilike', name)], limit=1)
            if account:
                return account
        return Account

    @api.model
    def _jkm_create_account(self, company, name, account_type, reconcile, reference):
        Account = self.env['account.account'].with_company(company)
        start = reference.code if reference else '999000'
        return Account.create({
            'name': name,
            'code': Account._search_new_account_code(start),
            'account_type': account_type,
            'reconcile': reconcile,
            'company_ids': [(6, 0, company.root_id.ids)],
        })

    @api.model
    def _jkm_get_payroll_accounts(self, company):
        find = self._jkm_find_account
        expense = find(company, ['expense'], ['salary expense', 'salaries', 'salary', 'wage'])
        if not expense:
            reference = find(company, ['expense'], [''])
            expense = self._jkm_create_account(company, self.env._('Salary Expenses'), 'expense', False, reference)
        payable = find(company, ['liability_current', 'liability_payable'],
                       ['salary exp payable', 'salaries payable', 'salary payable', 'salar', 'wages payable'],
                       reconcile=True)
        if not payable:
            reference = find(company, ['liability_current'], [''])
            payable = self._jkm_create_account(
                company, self.env._('Salaries Payable'), 'liability_current', True, reference)
        return {
            'expense': expense,
            'bonus': find(company, ['expense'], ['bonus to employee', 'employee bonus', 'bonus']) or expense,
            'payable': payable,
            'deduction': find(company, ['liability_current'], ['salary deduction', 'deductions payable']) or payable,
            'advance': find(company, ['asset_current', 'liability_current'], ['advance to employee', 'employee advance',
                                                                             'salary advance']) or payable,
        }

    @api.model
    def _jkm_configure_payroll_accounting(self, company):
        """Create the Salaries journal and map the default salary rules to accounts."""
        Journal = self.env['account.journal'].with_company(company)
        structures = self.env['hr.payroll.structure'].search([
            '|', ('country_id', '=', False), ('country_id', '=', company.account_fiscal_country_id.id)])
        if not structures:
            return
        try:
            accounts = self._jkm_get_payroll_accounts(company)
        except Exception:  # noqa: BLE001 - never block a chart installation
            _logger.exception("Payroll accounting: could not configure the accounts of %s", company.name)
            return

        journal = Journal.search([*Journal._check_company_domain(company), ('code', '=', 'SLR')], limit=1)
        if not journal:
            journal = Journal.create({
                'name': self.env._('Salaries'),
                'code': 'SLR',
                'type': 'general',
                'sequence': 99,
                'company_id': company.id,
                'default_account_id': accounts['payable'].id,
            })

        for structure in structures.with_company(company):
            if not structure.journal_id:
                structure.journal_id = journal
            for rule in structure.rule_ids:
                mapping = DEFAULT_RULE_ACCOUNTS.get(rule.code)
                if not mapping:
                    continue
                field, role = mapping
                vals = {}
                if not rule[field]:
                    vals[field] = accounts[role].id
                if rule.code == 'NET':
                    vals['employee_move_line'] = True
                if rule.code in SPLIT_RULES:
                    vals['split_move_lines'] = True
                if vals:
                    rule.write(vals)
