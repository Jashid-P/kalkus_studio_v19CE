# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrPayrollStructure(models.Model):
    _inherit = 'hr.payroll.structure'

    journal_id = fields.Many2one(
        'account.journal', 'Salary Journal', company_dependent=True,
        domain="[('type', '=', 'general')]",
        help="Journal of the entries created when the payslips of this structure are validated. "
             "Leave empty to validate payslips without accounting entries.")

    @api.constrains('journal_id')
    def _check_journal_id(self):
        for structure in self.sudo():
            journal = structure.journal_id
            if journal.currency_id and journal.currency_id != journal.company_id.currency_id:
                raise ValidationError(self.env._(
                    "Incorrect journal: the salary journal must use the currency of its company."))
