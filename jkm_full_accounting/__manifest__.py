# -*- coding: utf-8 -*-
{
    'name': "Community Full Accounting",
    'summary': "Enterprise-grade financial reports for Odoo Community",
    'description': """
Full Accounting
===============

Brings the complete financial reporting suite to Odoo Community Edition.

Reports
-------

* Balance Sheet
* Profit and Loss
* General Ledger
* Trial Balance
* Partner Ledger
* Aged Receivable / Aged Payable
* Cash Flow Statement
* Tax Report (works with the tax report definitions shipped by the
  localisation modules)

The report engine implements the ``account.report`` computation engines
(``account_codes``, ``domain``, ``tax_tags``, ``aggregation``, ``external``)
that the Community edition ships the data model for but not the runtime.

""",
    'author': "Kalkus Studio",
    'website': "https://www.kalkus.studio",
    'category': 'Accounting/Accounting',
    'version': '19.0.1.4.0',
    'license': 'LGPL-3',
    'depends': ['account', 'mail'],
    'data': [
        'security/jkm_accounting_security.xml',
        'security/ir.model.access.csv',

        'data/balance_sheet.xml',
        'data/profit_and_loss.xml',
        'data/report_definitions.xml',
        'data/report_actions.xml',

        'views/account_fiscal_year_views.xml',
        'views/account_move_views.xml',
        'wizard/account_change_lock_date.xml',
        'wizard/account_reconcile_wizard.xml',
        'views/res_config_settings_views.xml',
        'data/accounting_menu.xml',
        'views/menus.xml',
    ],
    'uninstall_hook': 'uninstall_hook',
    'assets': {
        'web.assets_backend': [
            'jkm_full_accounting/static/src/components/**/*.js',
            'jkm_full_accounting/static/src/components/**/*.xml',
            'jkm_full_accounting/static/src/components/**/*.scss',
        ],
    },
    'installable': True,
    'application': True,
}
