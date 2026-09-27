# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    payslip_ids = fields.One2many('hr.payslip', 'move_id', string='Payslips', readonly=True, copy=False)
    payslip_count = fields.Integer(compute='_compute_payslip_count', compute_sudo=True)

    @api.depends('payslip_ids')
    def _compute_payslip_count(self):
        for move in self:
            move.payslip_count = len(move.payslip_ids)

    def action_open_payslips(self):
        self.ensure_one()
        action = {
            'name': self.env._('Payslips'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip',
        }
        if len(self.payslip_ids) == 1:
            action.update({'view_mode': 'form', 'res_id': self.payslip_ids.id})
        else:
            action.update({'view_mode': 'list,form', 'domain': [('id', 'in', self.payslip_ids.ids)]})
        return action
