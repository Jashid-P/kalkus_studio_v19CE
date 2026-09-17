# -*- coding: utf-8 -*-
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Community leaves an empty placeholder for these in the settings view; the
    # fields themselves only exist once an accounting app is installed.
    fiscalyear_last_day = fields.Integer(
        related='company_id.fiscalyear_last_day', required=True, readonly=False,
    )
    fiscalyear_last_month = fields.Selection(
        related='company_id.fiscalyear_last_month', required=True, readonly=False,
    )
    group_fiscal_year = fields.Boolean(
        string="Fiscal Years",
        implied_group='jkm_full_accounting.group_fiscal_year',
        help="Define fiscal years of more or less than twelve months.",
    )

    @api.constrains('fiscalyear_last_day', 'fiscalyear_last_month')
    def _check_fiscalyear(self):
        """Reject a closing day the chosen month cannot have, e.g. 31 February."""
        for record in self:
            if not record.fiscalyear_last_day or not record.fiscalyear_last_month:
                continue
            try:
                date(2020, int(record.fiscalyear_last_month), record.fiscalyear_last_day)
            except ValueError:
                raise ValidationError(_(
                    "Incorrect fiscal year date: day is out of range for month. "
                    "Month: %(month)s; Day: %(day)s",
                    month=record.fiscalyear_last_month, day=record.fiscalyear_last_day,
                ))
