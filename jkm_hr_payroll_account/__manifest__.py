# -*- coding: utf-8 -*-
{
    'name': "Community Payroll Accounting",
    'summary': "Journal entries and payments for Community Payroll payslips",
    'description': """
Community Payroll Accounting
============================

Links Community Payroll to Accounting, like the Enterprise *Payroll Accounting* app:

* Debit / credit accounts, analytic distribution and tax grids on salary rules
* Salary journal on salary structures
* A draft journal entry is created when a payslip is validated (one per payslip,
  or one per batch and period when *Batch Payroll Move Lines* is enabled)
* Refunds create the reverse entry; cancelling or resetting a payslip removes or
  reverses its entry
* Register Payment on the net salary; the payslip is marked as paid once the net
  salary is fully reconciled
* A "Salaries" journal and default accounts are configured on install
""",
    'author': "Kalkus Studio",
    'website': "https://www.kalkus.studio",
    'category': 'Human Resources/Payroll',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'depends': ['jkm_hr_payroll', 'account'],
    'data': [
        'views/hr_salary_rule_views.xml',
        'views/hr_payroll_structure_views.xml',
        'views/hr_payslip_views.xml',
        'views/hr_payslip_run_views.xml',
        'views/hr_version_views.xml',
        'views/account_move_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'post_init_hook': '_jkm_hr_payroll_account_post_init',
    'installable': True,
    'auto_install': True,
}
