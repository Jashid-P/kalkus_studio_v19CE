# -*- coding: utf-8 -*-
from odoo import fields, models


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    move_id = fields.Many2one('account.move', 'Accounting Entry', readonly=True, copy=False)
    move_state = fields.Selection(related='move_id.state', string='Entry Status')
    move_count = fields.Integer(compute='_compute_move_count')

    def _compute_move_count(self):
        for run in self:
            run.move_count = len(run.slip_ids.move_id)

    def action_open_moves(self):
        self.ensure_one()
        moves = self.slip_ids.move_id
        action = {
            'name': self.env._('Journal Entries'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
        }
        if len(moves) == 1:
            action.update({'view_mode': 'form', 'res_id': moves.id})
        else:
            action.update({'view_mode': 'list,form', 'domain': [('id', 'in', moves.ids)]})
        return action

    def action_register_payment(self):
        slips = self.slip_ids.filtered('has_net_to_pay')
        return slips.action_register_payment()

    def action_draft(self):
        # Reset the batch entry once, not payslip by payslip.
        self.slip_ids.filtered(lambda s: s.state in ('validated', 'cancel'))._remove_account_moves()
        return super().action_draft()

    def action_cancel(self):
        self.slip_ids.filtered(lambda s: s.state == 'validated')._remove_account_moves()
        return super().action_cancel()
