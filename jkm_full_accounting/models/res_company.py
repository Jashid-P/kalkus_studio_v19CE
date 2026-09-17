# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import models
from odoo.tools import date_utils


class ResCompany(models.Model):
    _inherit = 'res.company'

    def compute_fiscalyear_dates(self, current_date):
        """Resolve the fiscal year containing ``current_date``.

        Community computes this purely from the company's closing day/month.
        An explicit ``account.fiscal.year`` record wins over that calculation,
        and where records only partially cover the computed range, the range is
        shortened so it never straddles a recorded year's boundary.
        """
        self.ensure_one()
        FiscalYear = self.env['account.fiscal.year']

        fiscal_year = FiscalYear.search([
            ('company_id', '=', self.id),
            ('date_from', '<=', current_date),
            ('date_to', '>=', current_date),
        ], limit=1)
        if fiscal_year:
            return {
                'date_from': fiscal_year.date_from,
                'date_to': fiscal_year.date_to,
                'record': fiscal_year,
            }

        date_from, date_to = date_utils.get_fiscal_year(
            current_date, day=self.fiscalyear_last_day, month=int(self.fiscalyear_last_month),
        )

        # A recorded year may cover part of the computed range, leaving a gap
        # (e.g. a short first year). Trim the range back to that gap.
        preceding = FiscalYear.search([
            ('company_id', '=', self.id),
            ('date_from', '<=', date_from),
            ('date_to', '>=', date_from),
        ], limit=1)
        if preceding:
            date_from = preceding.date_to + timedelta(days=1)

        following = FiscalYear.search([
            ('company_id', '=', self.id),
            ('date_from', '<=', date_to),
            ('date_to', '>=', date_to),
        ], limit=1)
        if following:
            date_to = following.date_from - timedelta(days=1)

        return {'date_from': date_from, 'date_to': date_to}
