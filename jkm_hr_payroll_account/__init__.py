# -*- coding: utf-8 -*-
from . import models


def _jkm_hr_payroll_account_post_init(env):
    for company in env['res.company'].search([('chart_template', '!=', False)], order='parent_path'):
        env['account.chart.template'].with_company(company)._jkm_configure_payroll_accounting(company)
