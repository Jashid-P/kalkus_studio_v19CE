# -*- coding: utf-8 -*-
from odoo import api, models


class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    @api.model_create_multi
    def create(self, vals_list):
        partials = super().create(vals_list)
        moves = (partials.debit_move_id | partials.credit_move_id).move_id
        moves.payslip_ids._update_paid_state_from_accounting()
        return partials

    def unlink(self):
        payslips = (self.debit_move_id | self.credit_move_id).move_id.payslip_ids
        res = super().unlink()
        payslips.exists()._update_paid_state_from_accounting()
        return res
