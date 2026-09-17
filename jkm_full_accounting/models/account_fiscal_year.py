# -*- coding: utf-8 -*-
"""Explicit fiscal years.

Community derives the fiscal year from the company's ``fiscalyear_last_day`` /
``fiscalyear_last_month`` only, which cannot express a short or irregular year
(a company's first year, or a change of closing date). Recording fiscal years
as real records makes those cases representable, and the report engine's
``from_fiscalyear`` / ``to_beginning_of_fiscalyear`` date scopes follow them.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AccountFiscalYear(models.Model):
    _name = 'account.fiscal.year'
    _description = "Fiscal Year"
    _order = 'date_from desc, id desc'

    name = fields.Char(string="Name", required=True)
    date_from = fields.Date(
        string="Start Date", required=True,
        help="Start Date, included in the fiscal year.",
    )
    date_to = fields.Date(
        string="End Date", required=True,
        help="Ending Date, included in the fiscal year.",
    )
    company_id = fields.Many2one(
        comodel_name='res.company', string="Company", required=True,
        default=lambda self: self.env.company,
    )

    @api.constrains('date_from', 'date_to', 'company_id')
    def _check_dates(self):
        """Fiscal years must be ordered and must not overlap one another."""
        for fiscal_year in self:
            if fiscal_year.date_to < fiscal_year.date_from:
                raise ValidationError(_("The ending date must not be prior to the starting date."))
            if fiscal_year.company_id.parent_id:
                raise ValidationError(_("You cannot have a fiscal year on a child company."))

            # Three ways two ranges can overlap: the new one starts inside an
            # existing year, ends inside one, or completely contains one.
            overlapping = self.search_count([
                ('id', '!=', fiscal_year.id),
                ('company_id', '=', fiscal_year.company_id.id),
                '|', '|',
                '&', ('date_from', '<=', fiscal_year.date_from), ('date_to', '>=', fiscal_year.date_from),
                '&', ('date_from', '<=', fiscal_year.date_to), ('date_to', '>=', fiscal_year.date_to),
                '&', ('date_from', '>=', fiscal_year.date_from), ('date_to', '<=', fiscal_year.date_to),
            ])
            if overlapping:
                raise ValidationError(_(
                    "You cannot have an overlap between two fiscal years, please correct the start "
                    "and/or end dates of your fiscal years."
                ))
