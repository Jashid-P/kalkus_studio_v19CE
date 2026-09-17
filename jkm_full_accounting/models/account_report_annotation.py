# -*- coding: utf-8 -*-
"""Notes attached to a line of a rendered report.

Report lines are computed, not stored, so an annotation is keyed by the line's
generated identifier rather than by a foreign key. That identifier encodes the
path from the report root down to the line, so it stays stable as long as the
line still exists in the report.
"""

from odoo import api, fields, models


class JkmReportAnnotation(models.Model):
    _name = 'jkm.report.annotation'
    _description = "Accounting Report Annotation"
    _order = 'create_date desc, id desc'

    report_id = fields.Many2one(
        comodel_name='account.report', string="Report", required=True, ondelete='cascade', index=True,
    )
    line_id = fields.Char(string="Line", required=True, index=True)
    text = fields.Text(string="Note", required=True)
    date = fields.Date(
        string="Date", default=fields.Date.context_today,
        help="Period the note refers to.",
    )
    company_id = fields.Many2one(
        comodel_name='res.company', string="Company", required=True,
        default=lambda self: self.env.company,
    )

    _line_uniq = models.Constraint(
        'unique (report_id, line_id, company_id)',
        "A line can only carry one annotation per company.",
    )

    @api.model
    def _get_for_report(self, report_id):
        """Return ``{line_id: {...}}`` for every annotation on a report."""
        annotations = self.search([
            ('report_id', '=', report_id),
            ('company_id', 'in', self.env.companies.ids),
        ])
        return {
            annotation.line_id: {
                'id': annotation.id,
                'text': annotation.text,
                'date': fields.Date.to_string(annotation.date),
            }
            for annotation in annotations
        }
