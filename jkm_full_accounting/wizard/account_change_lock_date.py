# -*- coding: utf-8 -*-
"""Wizard to review and change every accounting lock date in one place.

Community stores the lock dates on ``res.company`` but only exposes them
through Settings. Collecting them in a dedicated wizard mirrors the Accounting
app, and keeps the irreversible one (the hard lock) clearly separated.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.account.models.company import SOFT_LOCK_DATE_FIELDS


class AccountChangeLockDate(models.TransientModel):
    _name = 'account.change.lock.date'
    _description = "Change Lock Date"

    company_id = fields.Many2one(
        comodel_name='res.company', required=True, readonly=True,
        default=lambda self: self.env.company,
    )

    fiscalyear_lock_date = fields.Date(
        string="Lock Everything",
        default=lambda self: self.env.company.fiscalyear_lock_date,
        help="No entry can be created or modified up to and including this date.",
    )
    tax_lock_date = fields.Date(
        string="Lock Tax Return",
        default=lambda self: self.env.company.tax_lock_date,
        help="No entry affecting taxes can be created or modified up to and including this date.",
    )
    sale_lock_date = fields.Date(
        string="Lock Sales",
        default=lambda self: self.env.company.sale_lock_date,
        help="No customer invoice can be created or modified up to and including this date.",
    )
    purchase_lock_date = fields.Date(
        string="Lock Purchases",
        default=lambda self: self.env.company.purchase_lock_date,
        help="No vendor bill can be created or modified up to and including this date.",
    )
    hard_lock_date = fields.Date(
        string="Hard Lock",
        default=lambda self: self.env.company.hard_lock_date,
        help="Irreversible. No entry can be created or modified up to and including this date, "
             "and the date itself can never be moved back.",
    )
    current_hard_lock_date = fields.Date(
        string="Current Hard Lock",
        related='company_id.hard_lock_date',
        readonly=True,
    )

    @api.constrains('hard_lock_date')
    def _check_hard_lock_date_not_moved_back(self):
        """The hard lock is one-way; refuse to weaken it before anything is written."""
        for wizard in self:
            current = wizard.company_id.hard_lock_date
            if current and (not wizard.hard_lock_date or wizard.hard_lock_date < current):
                raise UserError(_(
                    "The hard lock date cannot be moved back. It is currently set to %(date)s.",
                    date=current,
                ))

    def action_apply(self):
        self.ensure_one()
        values = {field: self[field] for field in SOFT_LOCK_DATE_FIELDS}
        if self.hard_lock_date:
            values['hard_lock_date'] = self.hard_lock_date
        # Written as the company's own record so the standard lock-date checks
        # and the chatter tracking on res.company both apply.
        self.company_id.sudo().write(values)
        return {'type': 'ir.actions.act_window_close'}
