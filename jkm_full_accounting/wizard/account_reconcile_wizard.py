# -*- coding: utf-8 -*-
"""Reconcile selected journal items, creating a write-off when needed."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import formatLang


class AccountReconcileWizard(models.TransientModel):
    _name = 'account.reconcile.wizard'
    _description = "Reconcile Journal Items"
    _check_company_auto = True

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'move_line_ids' not in fields_list:
            return res

        if self.env.context.get('active_model') != 'account.move.line' or not self.env.context.get('active_ids'):
            raise UserError(_("This can only be used on journal items."))

        lines = self.env['account.move.line'].browse(self.env.context['active_ids']).exists()
        accounts = lines.account_id
        if len(accounts) > 2:
            raise UserError(_(
                "You can only reconcile entries with up to two different accounts: %(accounts)s",
                accounts=', '.join(accounts.mapped('display_name')),
            ))
        # With two accounts, the second is reconciled as if it were the first;
        # the exigibility check has to be told about that substitution.
        shadowed_aml_values = None
        if len(accounts) == 2:
            shadowed_aml_values = {
                line: {'account_id': lines[0].account_id}
                for line in lines.filtered(lambda x: x.account_id != lines[0].account_id)
            }
        lines._check_amls_exigibility_for_reconciliation(shadowed_aml_values=shadowed_aml_values)

        res['move_line_ids'] = [fields.Command.set(lines.ids)]
        return res

    move_line_ids = fields.Many2many(
        comodel_name='account.move.line', string="Journal Items", required=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company', compute='_compute_company_id', required=True, readonly=True,
    )
    company_currency_id = fields.Many2one(related='company_id.currency_id')
    reco_account_id = fields.Many2one(
        comodel_name='account.account', string="Reconcile Account", compute='_compute_reco_data',
    )
    amount = fields.Monetary(
        string="Write-Off Amount", currency_field='company_currency_id', compute='_compute_reco_data',
        help="Residual left by the selected items; this is what the write-off will absorb.",
    )
    is_write_off_required = fields.Boolean(compute='_compute_reco_data')
    allow_partials = fields.Boolean(
        string="Keep Open",
        help="Reconcile partially and leave the residual open, instead of writing it off.",
    )

    date = fields.Date(string="Date", default=fields.Date.context_today, required=True)
    journal_id = fields.Many2one(
        comodel_name='account.journal', string="Journal", check_company=True,
        domain="[('type', '=', 'general')]",
        compute='_compute_journal_id', store=True, readonly=False, precompute=True,
    )
    account_id = fields.Many2one(
        comodel_name='account.account', string="Write-Off Account", check_company=True,
    )
    label = fields.Char(string="Label", default=lambda self: _("Write-Off"))

    @api.depends('move_line_ids')
    def _compute_company_id(self):
        for wizard in self:
            wizard.company_id = wizard.move_line_ids.company_id[:1] or self.env.company

    @api.depends('move_line_ids')
    def _compute_reco_data(self):
        for wizard in self:
            lines = wizard.move_line_ids
            wizard.reco_account_id = lines.account_id[:1]
            # amount_residual is what is still open on each line, so its sum is
            # the amount a write-off would have to absorb.
            residual = sum(lines.mapped('amount_residual'))
            wizard.amount = residual
            currency = wizard.company_id.currency_id
            wizard.is_write_off_required = not currency.is_zero(residual)

    @api.depends('company_id')
    def _compute_journal_id(self):
        for wizard in self:
            if wizard.journal_id.company_id == wizard.company_id:
                continue
            wizard.journal_id = self.env['account.journal'].search([
                ('type', '=', 'general'),
                ('company_id', '=', wizard.company_id.id),
            ], limit=1)

    def _action_open_wizard(self):
        self.ensure_one()
        # The record is a NewId at this point; persist it so the dialog can load it.
        wizard = self.create(self._convert_to_write(self._cache))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reconcile"),
            'res_model': 'account.reconcile.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def _create_write_off_line(self):
        """Post a balancing entry and return its line on the reconciled account."""
        self.ensure_one()
        if not self.account_id:
            raise UserError(_("Please set a write-off account."))
        if not self.journal_id:
            raise UserError(_("Please set a journal for the write-off entry."))

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal_id.id,
            'date': self.date,
            'ref': self.label,
            'company_id': self.company_id.id,
            'line_ids': [
                fields.Command.create({
                    'name': self.label,
                    'account_id': self.reco_account_id.id,
                    'debit': -self.amount if self.amount < 0 else 0.0,
                    'credit': self.amount if self.amount > 0 else 0.0,
                }),
                fields.Command.create({
                    'name': self.label,
                    'account_id': self.account_id.id,
                    'debit': self.amount if self.amount > 0 else 0.0,
                    'credit': -self.amount if self.amount < 0 else 0.0,
                }),
            ],
        })
        move.action_post()
        return move.line_ids.filtered(lambda line: line.account_id == self.reco_account_id)

    def reconcile(self):
        self.ensure_one()
        # _origin resolves the real rows when the wizard itself is only in memory.
        lines = self.move_line_ids._origin
        if self.is_write_off_required and not self.allow_partials:
            lines |= self._create_write_off_line()
        lines.reconcile()
        return {'type': 'ir.actions.act_window_close'}
