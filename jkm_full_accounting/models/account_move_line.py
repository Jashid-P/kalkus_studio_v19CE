# -*- coding: utf-8 -*-
"""Reconciliation entry point for the Journal Items list.

Community can reconcile journal items (``account.move.line.reconcile``) but
offers no way to trigger it from the list view, which is how accountants
actually work. This adds the button's server side: reconcile silently when the
selection balances, and ask for a write-off when it does not.
"""

from odoo import _, models
from odoo.exceptions import UserError


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def action_reconcile(self):
        """Reconcile the selected journal items.

        Called by the Reconcile button of the Journal Items list. When the
        selection leaves a residual, a wizard collects the write-off details
        instead of reconciling straight away.
        """
        lines = self.filtered(lambda line: line.balance or line.amount_currency)
        if not lines:
            return False

        # Built in memory purely to run the wizard's validation and work out
        # whether a residual is left; only the write-off path needs a real record.
        wizard = self.env['account.reconcile.wizard'].with_context(
            active_model='account.move.line',
            active_ids=lines.ids,
        ).new({})

        if wizard.is_write_off_required:
            return wizard._action_open_wizard()

        lines.reconcile()
        return False
