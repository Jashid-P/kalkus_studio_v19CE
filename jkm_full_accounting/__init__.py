# -*- coding: utf-8 -*-
import logging

from . import models
from . import wizard

_logger = logging.getLogger(__name__)

# Sections moved under the "Accounting" root menu at install time.
_MOVED_MENU_XMLIDS = (
    'account.menu_board_journal_1',
    'account.menu_finance_receivables',
    'account.menu_finance_payables',
    'account.menu_finance_entries',
    'account.account_audit_menu',
    'account.menu_finance_reports',
    'account.menu_finance_configuration',
)


def uninstall_hook(env):
    """Hand the accounting sections back to the "Invoicing" root menu.

    Without this the sections would be deleted along with the "Accounting"
    menu this module creates, leaving the database with no way into accounting.
    """
    invoicing_menu = env.ref('account.menu_finance', raise_if_not_found=False)
    if not invoicing_menu:
        _logger.warning("account.menu_finance is missing; cannot restore the Invoicing menu.")
        return

    for xmlid in _MOVED_MENU_XMLIDS:
        menu = env.ref(xmlid, raise_if_not_found=False)
        if menu:
            menu.sudo().parent_id = invoicing_menu

    _restore_billing_groups(env)


def _restore_billing_groups(env):
    """Put the accounting groups back the way Community ships them.

    The module promotes managers to full accounting users; leaving that in
    place after uninstall would grant rights the remaining modules never
    intended to hand out.
    """
    group_user = env.ref('account.group_account_user', raise_if_not_found=False)
    group_readonly = env.ref('account.group_account_readonly', raise_if_not_found=False)
    group_manager = env.ref('account.group_account_manager', raise_if_not_found=False)
    group_invoice = env.ref('account.group_account_invoice', raise_if_not_found=False)

    if group_user:
        group_user.sudo().write({'name': "Show Full Accounting Features", 'user_ids': [(5, 0, 0)]})
    if group_readonly:
        group_readonly.sudo().name = "Show Full Accounting Features - Readonly"
    if group_manager and group_user:
        commands = [(3, group_user.id)]
        if group_invoice:
            commands.append((4, group_invoice.id))
        group_manager.sudo().write({'implied_ids': commands})
