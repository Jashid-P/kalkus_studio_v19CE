# -*- coding: utf-8 -*-
{
    'name': "Community Payroll",
    'summary': "Enterprise-style payroll for Odoo Community: payslips, batches, salary rules",
    'description': """
Community Payroll
=================

Brings a complete payroll application to Odoo Community Edition, modelled on
the Enterprise Payroll app.

Features
--------

* Salary structure types, salary structures and salary rules
  (fixed amount, percentage, other input, Python code; conditions based on
  Python expressions, ranges or other inputs)
* Salary rule categories with parent aggregation (BASIC, ALW, GROSS, DED, NET...)
* Payslips computed from the employee contract (``hr.version``) and the
  work entries, including time off and out-of-contract periods
* Pay schedules: daily, weekly, bi-weekly, semi-monthly, monthly, bi-monthly,
  quarterly, semi-annually, annually
* Fixed or hourly wages
* Payslip batches with a generation wizard
* Other inputs and salary attachments (garnishments, assignments, child support...)
* Rule parameters with dated values, usable in salary rules
* Refunds (credit notes), printable PDF payslip, email sending
* Payroll analysis reporting

Salary rules use the same evaluation context as Enterprise Payroll,
so most rules can be ported unchanged.
""",
    'category': 'Human Resources/Payroll',
    'sequence': 290,
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'depends': ['hr_work_entry_holidays', 'mail'],
    'data': [
        'security/jkm_hr_payroll_security.xml',
        'security/ir.model.access.csv',

        'data/decimal_precision_data.xml',
        'data/hr_payroll_sequence.xml',
        'data/hr_salary_rule_category_data.xml',
        'data/hr_payslip_input_type_data.xml',
        'data/hr_payroll_structure_data.xml',
        'data/report_paperformat_data.xml',

        'report/hr_payslip_report.xml',
        'report/hr_payslip_templates.xml',
        'data/mail_template_data.xml',

        'wizard/hr_payslip_employees_views.xml',
        'views/hr_salary_rule_category_views.xml',
        'views/hr_salary_rule_views.xml',
        'views/hr_payroll_structure_views.xml',
        'views/hr_payroll_structure_type_views.xml',
        'views/hr_payslip_input_type_views.xml',
        'views/hr_rule_parameter_views.xml',
        'views/hr_payslip_line_views.xml',
        'views/hr_payslip_views.xml',
        'views/hr_payslip_run_views.xml',
        'views/hr_salary_attachment_views.xml',
        'views/hr_version_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_payroll_menu.xml',
    ],
    'demo': [
        'data/hr_payroll_demo.xml',
    ],
    'assets': {
        'web.report_assets_common': [
            'jkm_hr_payroll/static/src/scss/payslip_report.scss',
        ],
    },
    'installable': True,
    'application': True,
}
