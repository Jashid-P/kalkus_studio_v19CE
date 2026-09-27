# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    batch_payroll_move_lines = fields.Boolean(
        related='company_id.batch_payroll_move_lines', readonly=False)
