# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    batch_payroll_move_lines = fields.Boolean(
        string="Batch Payroll Move Lines",
        help="Merge the accounting entries of all the payslips of the same journal and period "
             "into a single journal entry. Journal items are then no longer per employee.")
