# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class HrPayrollStructureType(models.Model):
    _inherit = 'hr.payroll.structure.type'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    default_schedule_pay = fields.Selection(
        selection=lambda self: self._get_selection_schedule_pay(),
        string='Scheduled Pay', default='monthly',
        help="Defines the frequency of the wage payment.")
    struct_ids = fields.One2many('hr.payroll.structure', 'type_id', string="Structures")
    default_struct_id = fields.Many2one(
        'hr.payroll.structure', string="Pay Structure",
        domain="[('type_id', '=', id)]",
        help="Structure used by default on the payslips of employees in this category.")
    default_work_entry_type_id = fields.Many2one(
        'hr.work.entry.type', string="Work Entry Type",
        default=lambda self: self.env.ref('hr_work_entry.work_entry_type_attendance', raise_if_not_found=False),
        help="Work entry type for regular attendances.")
    wage_type = fields.Selection([
        ('monthly', 'Fixed Wage'),
        ('hourly', 'Hourly Wage'),
    ], string="Wage Type", default='monthly', required=True)
    struct_count = fields.Integer(compute='_compute_struct_count', string='Structures Count')

    @api.model
    def _get_selection_schedule_pay(self):
        return [
            ('annually', 'Annually'),
            ('semi-annually', 'Semi-annually'),
            ('quarterly', 'Quarterly'),
            ('bi-monthly', 'Bi-monthly'),
            ('monthly', 'Monthly'),
            ('semi-monthly', 'Semi-monthly'),
            ('bi-weekly', 'Bi-weekly'),
            ('weekly', 'Weekly'),
            ('daily', 'Daily'),
        ]

    @api.model
    def _get_schedule_period_end(self, schedule, date_from):
        """Return the last day of the pay period starting on ``date_from``."""
        if schedule == 'semi-monthly':
            if date_from.day <= 15:
                return date_from.replace(day=15)
            return date_from + relativedelta(day=31)
        deltas = {
            'annually': relativedelta(years=1, days=-1),
            'semi-annually': relativedelta(months=6, days=-1),
            'quarterly': relativedelta(months=3, days=-1),
            'bi-monthly': relativedelta(months=2, days=-1),
            'monthly': relativedelta(months=1, days=-1),
            'bi-weekly': relativedelta(days=13),
            'weekly': relativedelta(days=6),
            'daily': relativedelta(days=0),
        }
        return date_from + deltas.get(schedule or 'monthly', deltas['monthly'])

    @api.depends('struct_ids')
    def _compute_struct_count(self):
        for structure_type in self:
            structure_type.struct_count = len(structure_type.struct_ids)

    def action_open_structures(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('jkm_hr_payroll.action_hr_payroll_structure')
        action['domain'] = [('type_id', '=', self.id)]
        action['context'] = {'default_type_id': self.id}
        return action
