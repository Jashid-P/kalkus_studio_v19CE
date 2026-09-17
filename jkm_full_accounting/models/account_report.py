# -*- coding: utf-8 -*-
"""Runtime engine for ``account.report``.

Odoo Community ships the ``account.report`` data model (definitions, lines,
expressions, columns) but not the code that turns a definition into figures.
This module supplies that runtime: an options framework, a line builder and
the five computation engines referenced by ``account.report.expression.engine``.
"""

import ast
import re
from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools import date_utils, float_is_zero, format_date
from odoo.tools.misc import formatLang

# Formula syntax is the one the Community data model documents, so report
# definitions shipped by the localisation modules parse unchanged.
ACCOUNT_CODES_SPLIT_REGEX = re.compile(r"(?=[+-])")
ACCOUNT_CODES_TERM_REGEX = re.compile(
    r"^(?P<sign>[+-]?)"
    r"(?P<prefix>([A-Za-z\d.]*|tag\([\w.]+\))((?=\\)|(?<=[^CD])))"
    r"(\\\((?P<excluded_prefixes>([A-Za-z\d.]+,)*[A-Za-z\d.]*)\))?"
    r"(?P<balance_character>[DC]?)$"
)
AGGREGATION_TERM_REGEX = re.compile(r"(?P<line_code>[^().\s*/+\-]+)\.(?P<expr_label>[^().\s*/+\-]+)")
CROSS_REPORT_REGEX = re.compile(r"^cross_report\((.+)\)$")

LINE_ID_SEP = '|'


class AccountReportColumn(models.Model):
    _inherit = 'account.report.column'

    group_label = fields.Char(
        string="Column Group",
        help="Heading this column sits under. Columns sharing a heading are "
             "spanned together. Left empty, the column sits under the period.",
    )


class AccountReport(models.Model):
    _inherit = 'account.report'

    # Reports whose lines cannot be expressed as static definitions (general
    # ledger, aged balance, ...) delegate their line generation to a handler
    # model. Community ships no such hook, so it is declared here.
    custom_handler_model_id = fields.Many2one(
        string="Custom Handler Model",
        comodel_name='ir.model',
        help="Model generating this report's lines dynamically, instead of using its line definitions.",
    )
    custom_handler_model_name = fields.Char(
        string="Custom Handler Model Name",
        related='custom_handler_model_id.model',
    )
    show_section_totals = fields.Boolean(
        string="Show Section Totals",
        help="Close every expanded section with a 'Total <section>' line. "
             "Suited to statement reports whose sections accumulate, such as a balance sheet.",
    )

    # ------------------------------------------------------------------
    # Line identifiers
    # ------------------------------------------------------------------
    # A line id encodes the full path from the root of the report down to the
    # line, so that any line can be re-expanded without keeping server state.
    # Each segment is ``markup~model~value``.

    @api.model
    def _build_line_id(self, path):
        return LINE_ID_SEP.join(
            '%s~%s~%s' % (markup or '', model or '', value if value is not None else '')
            for markup, model, value in path
        )

    @api.model
    def _parse_line_id(self, line_id):
        if not line_id:
            return []
        path = []
        for segment in line_id.split(LINE_ID_SEP):
            markup, model, value = segment.split('~')
            path.append((markup or None, model or None, int(value) if value.lstrip('-').isdigit() else (value or None)))
        return path

    @api.model
    def _get_parent_line_id(self, line_id):
        path = self._parse_line_id(line_id)
        return self._build_line_id(path[:-1]) if len(path) > 1 else None

    @api.model
    def _get_model_info_from_id(self, line_id):
        """Return the ``(model, res_id)`` the deepest segment of ``line_id`` points to."""
        path = self._parse_line_id(line_id)
        if not path:
            return None, None
        return path[-1][1], path[-1][2]

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------

    def _get_options(self, previous_options=None):
        """Build the options dictionary driving a report rendering."""
        self.ensure_one()
        previous_options = previous_options or {}
        options = {
            'report_id': self.id,
            'name': self.name,
            'unfold_all': previous_options.get('unfold_all', False),
            'unfolded_lines': previous_options.get('unfolded_lines', []),
        }

        self._init_options_date(options, previous_options)
        self._init_options_comparison(options, previous_options)
        self._init_options_journals(options, previous_options)
        self._init_options_all_entries(options, previous_options)
        self._init_options_hierarchy(options, previous_options)
        self._init_options_partner(options, previous_options)
        self._init_options_analytic(options, previous_options)
        self._init_options_columns(options, previous_options)
        self._init_options_search(options, previous_options)

        # A custom handler may add filters of its own.
        handler = self._get_custom_handler_model()
        if handler is not None and hasattr(handler, '_custom_options_initializer'):
            handler._custom_options_initializer(self, options, previous_options)

        return options

    @api.model
    def get_report_data(self, report_id, previous_options=None):
        """Return the safe, render-ready payload used by the Community UI.

        The Enterprise report client is not available in Community.  Keeping
        this entry point on ``account.report`` means the report engine remains
        reusable by XML actions, integrations, and a future richer client.
        Access is deliberately checked on the report record before any journal
        item is queried; the underlying accounting record rules then continue
        to enforce company and accounting-group boundaries.
        """
        report = self.browse(report_id).exists()
        if not report:
            raise UserError(_("The requested accounting report does not exist."))
        report.ensure_one()
        report.check_access('read')

        options = report._get_options(previous_options or {})
        return {
            'report': {
                'id': report.id,
                'name': report.name,
                # Statement-style reports nest into sections and totals; ledger
                # style ones are a flat list of accounts or partners. They want
                # different presentation, so the client is told which it is.
                'layout': 'list' if report._get_custom_handler_model() is not None else 'hierarchy',
                'column_count': len(options['columns']),
                # Searching suits reports listing many accounts or partners; a
                # statement of fixed sections has nothing to search for.
                'search_bar': report.search_bar,
            },
            'options': options,
            'lines': report._search_lines(options),
            'warnings': report._get_warnings(options),
            'annotations': self.env['jkm.report.annotation']._get_for_report(report.id),
        }

    def action_open_line_record(self, line_id):
        """Open the record a rendered line stands for.

        The line id carries the model and id of whatever the line was built
        from, so a journal item, account or partner can be opened without the
        report having to keep any state.
        """
        self.ensure_one()
        model, res_id = self._get_model_info_from_id(line_id)
        if not model or not isinstance(res_id, int) or model not in self.env:
            return False
        # A section line points at the report's own definition record, which is
        # configuration rather than accounting data; opening it would only
        # confuse the reader.
        if model not in self._get_drillable_models():
            return False

        record = self.env[model].browse(res_id).exists()
        if not record:
            return False

        # A journal item is most useful opened as its entry, which is what an
        # accountant is actually looking for when drilling into the ledger.
        if model == 'account.move.line':
            record = record.move_id
            model = 'account.move'

        return {
            'type': 'ir.actions.act_window',
            'name': record.display_name,
            'res_model': model,
            'res_id': record.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def get_line_thread(self, line_id):
        """Resolve a report line to a record whose chatter can be shown.

        Only models tracking messages qualify, and a journal item defers to its
        entry, which is where the conversation about it actually lives.
        """
        self.ensure_one()
        model, res_id = self._get_model_info_from_id(line_id)
        if not model or not isinstance(res_id, int) or model not in self.env:
            return False
        if model not in self._get_drillable_models():
            return False

        record = self.env[model].browse(res_id).exists()
        if not record:
            return False

        if model == 'account.move.line':
            record = record.move_id

        # A chatter needs a thread; res.currency and friends have none.
        if not isinstance(record, type(self.env['mail.thread'])) and not hasattr(record, 'message_ids'):
            return False

        record.check_access('read')
        return {
            'model': record._name,
            'id': record.id,
            'name': record.display_name,
        }

    def action_open_journal_items(self, line_id, options):
        """Open the journal items making up a report line.

        The list is scoped the same way the report is - same dates, same
        posted/draft choice, same journals - so the figures on screen and the
        items behind them agree.
        """
        self.ensure_one()
        model, res_id = self._get_model_info_from_id(line_id)
        if not model or not isinstance(res_id, int) or model not in ('account.account', 'res.partner'):
            return False

        options = options or self._get_options({})
        column_group_key = options['columns'][0]['column_group_key']
        domain = list(self._get_base_domain(options, 'strict_range', column_group_key))

        if model == 'account.account':
            domain.append(('account_id', '=', res_id))
            name = self.env['account.account'].browse(res_id).display_name
            # Coming from an account, the grouping restates the line clicked.
            context = {'search_default_group_by_account': 1, 'expand': 1}
        else:
            domain.append(('partner_id', '=', res_id))
            name = self.env['res.partner'].browse(res_id).display_name
            # Coming from a partner, the items are already about one partner;
            # splitting them by account would bury the entries being looked for.
            context = {'expand': 1}

        return {
            'type': 'ir.actions.act_window',
            'name': _("Journal Items: %(name)s", name=name),
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'views': [(self.env.ref('account.view_move_line_tree').id, 'list'), (False, 'form')],
            'domain': domain,
            'context': context,
            'target': 'current',
        }

    def action_open_general_ledger(self, line_id, options):
        """Open the General Ledger focused on the account behind a line.

        Reading a balance sheet figure usually ends in the same question - what
        makes this up - and the ledger is where that is answered.
        """
        self.ensure_one()
        model, res_id = self._get_model_info_from_id(line_id)
        if model != 'account.account' or not isinstance(res_id, int):
            return False

        ledger = self.env.ref('jkm_full_accounting.general_ledger_report', raise_if_not_found=False)
        action = self.env.ref('jkm_full_accounting.action_general_ledger', raise_if_not_found=False)
        if not ledger or not action:
            return False

        # Carry the period across, and open the account already unfolded.
        ledger_options = ledger._get_options({
            'date': dict(options.get('date') or {}),
            'all_entries': options.get('all_entries', False),
            'selected_journal_ids': options.get('selected_journal_ids', []),
        })
        account_line_id = ledger._build_line_id([(None, 'account.account', res_id)])

        return {
            'type': 'ir.actions.client',
            'tag': 'account_report',
            'name': ledger.name,
            'context': {
                'report_id': ledger.id,
                'default_options': dict(ledger_options, unfolded_lines=[account_line_id]),
            },
        }

    def action_open_tax_audit(self, line_id, options):
        """Open the journal items a tax figure was built from.

        Both sides are shown: the tax lines themselves and the lines the tax was
        charged on. A tax amount cannot be checked without the base it came
        from, so showing one without the other would only prompt a second click.
        """
        self.ensure_one()
        model, res_id = self._get_model_info_from_id(line_id)
        if model != 'account.tax' or not isinstance(res_id, int):
            return False

        tax = self.env['account.tax'].browse(res_id).exists()
        if not tax:
            return False

        options = options or self._get_options({})
        column_group_key = options['columns'][0]['column_group_key']
        domain = list(
            self._get_base_domain(options, 'strict_range', column_group_key)
            & Domain('tax_line_id', '=', tax.id).__or__(Domain('tax_ids', 'in', tax.ids))
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _("Journal Items for Tax Audit: %(tax)s", tax=tax.display_name),
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'views': [(self.env.ref('account.view_move_line_tree').id, 'list'), (False, 'form')],
            'domain': domain,
            'context': {'search_default_group_by_account': 1, 'expand': 1},
            'target': 'current',
        }

    @api.model
    def _get_drillable_models(self):
        """Models a report line may open, keyed off what the handlers emit."""
        return {
            'account.move.line',
            'account.move',
            'account.account',
            'account.journal',
            'account.tax',
            'res.partner',
        }

    @api.model
    def set_line_annotation(self, report_id, line_id, text):
        """Create, update or clear the note on a report line."""
        Annotation = self.env['jkm.report.annotation']
        existing = Annotation.search([
            ('report_id', '=', report_id),
            ('line_id', '=', line_id),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

        if not (text or '').strip():
            existing.unlink()
            return False

        if existing:
            existing.text = text
        else:
            existing = Annotation.create({
                'report_id': report_id,
                'line_id': line_id,
                'text': text,
            })
        return {'id': existing.id, 'text': existing.text}

    def _search_lines(self, options):
        """Render the report, narrowed to the search term when one is given.

        Searching expands the report internally so a match can be found wherever
        it lives, then returns the matches folded, exactly as the report would
        show them. Opening one is left to the reader: a search that dumped every
        underlying record on screen would bury the answer it just found.
        """
        search = (options.get('search') or '').strip().lower()
        if not search:
            return self._get_lines(options)

        lines = self._get_lines(dict(options, unfold_all=True))

        by_id = {line['id']: line for line in lines}
        children = defaultdict(list)
        for line in lines:
            if line.get('parent_id'):
                children[line['parent_id']].append(line['id'])

        unfolded_lines = set(options.get('unfolded_lines') or [])

        keep = set()
        for line in lines:
            if search not in (line.get('name') or '').lower():
                continue
            keep.add(line['id'])
            # Upwards, so the match keeps its place in the report.
            parent_id = line.get('parent_id')
            while parent_id and parent_id not in keep:
                keep.add(parent_id)
                parent_id = by_id.get(parent_id, {}).get('parent_id')

        # Downwards only through rows the reader has opened, so the result
        # honours the fold state rather than overriding it.
        stack = [line_id for line_id in keep if line_id in unfolded_lines]
        while stack:
            for child_id in children.get(stack.pop(), []):
                if child_id in keep:
                    continue
                keep.add(child_id)
                child = by_id[child_id]
                if not child.get('unfoldable') or child_id in unfolded_lines:
                    stack.append(child_id)

        result = []
        for line in lines:
            if line['id'] not in keep:
                continue
            if line.get('unfoldable'):
                line['unfolded'] = line['id'] in unfolded_lines
            result.append(line)
        return result

    def _get_warnings(self, options):
        """Conditions the reader should know about before trusting the figures.

        Draft entries are the important one: they are excluded from a posted-only
        report, so a balance can look wrong for reasons the numbers cannot show.
        """
        self.ensure_one()
        warnings = []

        if not options.get('all_entries'):
            group = options['column_groups'][options['columns'][0]['column_group_key']]
            draft_domain = [
                ('company_id', 'in', self.env.companies.ids),
                ('parent_state', '=', 'draft'),
                ('date', '<=', group['date_to']),
            ]
            if options.get('selected_journal_ids'):
                draft_domain.append(('journal_id', 'in', options['selected_journal_ids']))
            if self.env['account.move.line'].search_count(draft_domain, limit=1):
                warnings.append({
                    'type': 'info',
                    'message': _("There are unposted Journal Entries prior or included in this period."),
                    'action': 'toggle_all_entries',
                })

        return warnings

    def _init_options_date(self, options, previous_options):
        period_type = previous_options.get('date', {}).get('filter') or self.default_opening_date_filter or 'this_year'
        today = fields.Date.context_today(self)

        if previous_options.get('date', {}).get('date_from') and period_type == 'custom':
            date_from = fields.Date.to_date(previous_options['date']['date_from'])
            date_to = fields.Date.to_date(previous_options['date']['date_to'])
        else:
            date_from, date_to = self._get_dates_for_filter(period_type, today)

        options['date'] = {
            'mode': 'single' if self.filter_date_range is False else 'range',
            'filter': period_type,
            'date_from': fields.Date.to_string(date_from),
            'date_to': fields.Date.to_string(date_to),
            'string': self._get_date_period_string(date_from, date_to, period_type),
        }

    @api.model
    def _get_dates_for_filter(self, period_type, anchor):
        """Resolve a named period filter into a ``(date_from, date_to)`` pair."""
        company = self.env.company
        if period_type == 'today':
            return anchor, anchor
        if period_type in ('this_month', 'previous_month'):
            base = anchor if period_type == 'this_month' else anchor - relativedelta(months=1)
            return date_utils.start_of(base, 'month'), date_utils.end_of(base, 'month')
        if period_type in ('this_quarter', 'previous_quarter'):
            base = anchor if period_type == 'this_quarter' else anchor - relativedelta(months=3)
            return date_utils.start_of(base, 'quarter'), date_utils.end_of(base, 'quarter')
        # Fiscal-year aware, so a company closing in June reports on its own year.
        base = anchor if period_type != 'previous_year' else anchor - relativedelta(years=1)
        fy = company.compute_fiscalyear_dates(base)
        return fy['date_from'], fy['date_to']

    @api.model
    def _get_date_period_string(self, date_from, date_to, period_type):
        fy = self.env.company.compute_fiscalyear_dates(date_to)
        if fy['date_from'] == date_from and fy['date_to'] == date_to:
            # Only call it a year when the fiscal year is a calendar year.
            if date_from.month == 1 and date_from.day == 1:
                return str(date_to.year)
            return _("FY %(year)s", year=date_to.year)
        if date_utils.start_of(date_to, 'month') == date_from and date_utils.end_of(date_to, 'month') == date_to:
            return format_date(self.env, date_to, date_format='MMM yyyy')
        if date_utils.start_of(date_to, 'quarter') == date_from and date_utils.end_of(date_to, 'quarter') == date_to:
            return _("Q%(quarter)s %(year)s", quarter=(date_to.month - 1) // 3 + 1, year=date_to.year)
        if date_from == date_to:
            return format_date(self.env, date_to)
        return _("%(from)s to %(to)s", from_=format_date(self.env, date_from), to=format_date(self.env, date_to))

    def _init_options_comparison(self, options, previous_options):
        if not self.filter_period_comparison:
            options['comparison'] = {'filter': 'no_comparison', 'periods': []}
            return

        previous = previous_options.get('comparison', {})
        comparison_filter = previous.get('filter', 'no_comparison')
        number_period = int(previous.get('number_period', 1) or 1)

        periods = []
        if comparison_filter in ('previous_period', 'same_last_year'):
            date_from = fields.Date.to_date(options['date']['date_from'])
            date_to = fields.Date.to_date(options['date']['date_to'])
            for i in range(1, number_period + 1):
                if comparison_filter == 'same_last_year':
                    period_from = date_from - relativedelta(years=i)
                    period_to = date_to - relativedelta(years=i)
                else:
                    period_from, period_to = self._get_previous_period(date_from, date_to, i)
                periods.append({
                    'date_from': fields.Date.to_string(period_from),
                    'date_to': fields.Date.to_string(period_to),
                    'string': self._get_date_period_string(period_from, period_to, options['date']['filter']),
                    'mode': options['date']['mode'],
                })
        elif comparison_filter == 'custom' and previous.get('date_from'):
            period_from = fields.Date.to_date(previous['date_from'])
            period_to = fields.Date.to_date(previous['date_to'])
            periods.append({
                'date_from': previous['date_from'],
                'date_to': previous['date_to'],
                'string': self._get_date_period_string(period_from, period_to, 'custom'),
                'mode': options['date']['mode'],
            })

        options['comparison'] = {
            'filter': comparison_filter,
            'number_period': number_period,
            'periods': periods,
        }

    @api.model
    def _get_previous_period(self, date_from, date_to, offset):
        """Shift a period backwards, keeping whole months whole."""
        is_whole_months = (
            date_from == date_utils.start_of(date_from, 'month')
            and date_to == date_utils.end_of(date_to, 'month')
        )
        if is_whole_months:
            months = (date_to.year - date_from.year) * 12 + (date_to.month - date_from.month) + 1
            shifted_from = date_from - relativedelta(months=months * offset)
            shifted_to = date_utils.end_of(date_to - relativedelta(months=months * offset), 'month')
            return shifted_from, shifted_to
        delta = (date_to - date_from) + relativedelta(days=1)
        return date_from - delta * offset, date_to - delta * offset

    def _init_options_journals(self, options, previous_options):
        if not self.filter_journals:
            options['journals'] = []
            return
        selected = set(previous_options.get('selected_journal_ids', []))
        journals = self.env['account.journal'].search([('company_id', 'in', self.env.companies.ids)])
        options['journals'] = [
            {'id': journal.id, 'name': journal.name, 'code': journal.code,
             'type': journal.type, 'selected': journal.id in selected}
            for journal in journals
        ]
        options['selected_journal_ids'] = [j['id'] for j in options['journals'] if j['selected']]

    def _init_options_all_entries(self, options, previous_options):
        options['all_entries'] = previous_options.get('all_entries', False)

    def _init_options_hierarchy(self, options, previous_options):
        options['hierarchy'] = previous_options.get('hierarchy', bool(self.filter_hierarchy == 'by_default'))

    def _init_options_partner(self, options, previous_options):
        if not self.filter_partner:
            return
        options['partner_ids'] = previous_options.get('partner_ids', [])

    def _init_options_analytic(self, options, previous_options):
        if not self.filter_analytic:
            return
        options['analytic_accounts'] = previous_options.get('analytic_accounts', [])

    def _init_options_search(self, options, previous_options):
        options['search'] = (previous_options.get('search') or '').strip()

    def _init_options_columns(self, options, previous_options):
        """Expand the report's column definitions across every compared period."""
        base_columns = self.column_ids or self.env['account.report.column']
        periods = [{
            'date_from': options['date']['date_from'],
            'date_to': options['date']['date_to'],
            'string': options['date']['string'],
        }] + options.get('comparison', {}).get('periods', [])

        columns = []
        headers = []
        for period in periods:
            for column in base_columns:
                columns.append({
                    'name': column.name,
                    'column_group_key': '%s_%s' % (period['date_from'], period['date_to']),
                    'expression_label': column.expression_label,
                    'figure_type': column.figure_type,
                    'blank_if_zero': column.blank_if_zero,
                    'sortable': column.sortable,
                    'date_from': period['date_from'],
                    'date_to': period['date_to'],
                    'group_label': column.group_label or period['string'],
                })

        # Consecutive columns sharing a heading are spanned under it, which is
        # what puts Debit and Credit together under the period while the opening
        # and closing balances keep headings of their own.
        for column in columns:
            if headers and headers[-1]['name'] == column['group_label']:
                headers[-1]['colspan'] += 1
            else:
                headers.append({'name': column['group_label'], 'colspan': 1})

        options['columns'] = columns
        options['column_headers'] = headers
        options['column_groups'] = {
            c['column_group_key']: {'date_from': c['date_from'], 'date_to': c['date_to']}
            for c in columns
        }

    # ------------------------------------------------------------------
    # Custom handlers
    # ------------------------------------------------------------------

    def _get_custom_handler_model(self):
        """Return the handler model instance for this report, if it declares one."""
        self.ensure_one()
        model_name = self.custom_handler_model_name or self.root_report_id.custom_handler_model_name
        if model_name and model_name in self.env:
            return self.env[model_name]
        return None

    # ------------------------------------------------------------------
    # Query scoping
    # ------------------------------------------------------------------

    def _get_date_scope_range(self, date_scope, date_from, date_to):
        """Translate an expression's ``date_scope`` into an effective date range.

        ``None`` as a lower bound means "since the beginning of time", which is
        what balance-sheet style accumulations need.
        """
        if date_scope == 'strict_range':
            return date_from, date_to
        if date_scope == 'from_beginning':
            return None, date_to
        if date_scope == 'from_fiscalyear':
            return self.env.company.compute_fiscalyear_dates(date_to)['date_from'], date_to
        if date_scope == 'to_beginning_of_fiscalyear':
            fy_from = self.env.company.compute_fiscalyear_dates(date_to)['date_from']
            return None, fy_from - relativedelta(days=1)
        if date_scope == 'to_beginning_of_period':
            return None, date_from - relativedelta(days=1)
        return date_from, date_to

    def _get_base_domain(self, options, date_scope, column_group_key):
        """Common ``account.move.line`` domain for every engine."""
        group = options['column_groups'][column_group_key]
        date_from = fields.Date.to_date(group['date_from'])
        date_to = fields.Date.to_date(group['date_to'])
        scoped_from, scoped_to = self._get_date_scope_range(date_scope, date_from, date_to)

        domain = [('company_id', 'in', self.env.companies.ids), ('date', '<=', scoped_to)]
        if scoped_from:
            domain.append(('date', '>=', scoped_from))

        if options.get('all_entries'):
            domain.append(('parent_state', '!=', 'cancel'))
        else:
            domain.append(('parent_state', '=', 'posted'))

        if options.get('selected_journal_ids'):
            domain.append(('journal_id', 'in', options['selected_journal_ids']))
        if options.get('partner_ids'):
            domain.append(('partner_id', 'in', options['partner_ids']))
        if options.get('analytic_accounts'):
            domain.append(('analytic_distribution', 'in', options['analytic_accounts']))
        if self.only_tax_exigible:
            return Domain(domain) & self.env['account.move.line']._get_tax_exigible_domain()
        return Domain(domain)

    # ------------------------------------------------------------------
    # Expression computation
    # ------------------------------------------------------------------

    def _compute_expression_values(self, options, column_group_key, lines=None):
        """Evaluate every expression of the report for one column group.

        Returns ``{expression_id: {'value': float}}``. Engines are evaluated in
        dependency order so that ``aggregation`` always sees resolved operands.
        """
        self.ensure_one()
        report_lines = lines if lines is not None else self._get_report_lines()
        expressions = report_lines.expression_ids
        by_engine = expressions.grouped('engine')

        results = {}
        results.update(self._compute_engine_account_codes(by_engine.get('account_codes', expressions.browse()), options, column_group_key))
        results.update(self._compute_engine_domain(by_engine.get('domain', expressions.browse()), options, column_group_key))
        results.update(self._compute_engine_tax_tags(by_engine.get('tax_tags', expressions.browse()), options, column_group_key))
        results.update(self._compute_engine_external(by_engine.get('external', expressions.browse()), options, column_group_key))
        results.update(self._compute_engine_aggregation(by_engine.get('aggregation', expressions.browse()), options, column_group_key, results))
        return results

    def _get_report_lines(self):
        """All lines of the report, parents and children alike."""
        self.ensure_one()
        return self.env['account.report.line'].search([('report_id', '=', self.id)])

    # -- account_codes -------------------------------------------------

    def _compute_engine_account_codes(self, expressions, options, column_group_key):
        """Sum balances of accounts whose code matches a prefix expression.

        A formula is a sum of signed terms, e.g. ``+40\\(401,402)D-70C``:
        an optional sign, a code prefix (or ``tag(xmlid)``), optionally excluded
        prefixes, and an optional ``D``/``C`` restriction keeping only accounts
        whose balance is a debit / a credit.
        """
        if not expressions:
            return {}

        # One aggregate query per date scope, then slice it per prefix in Python:
        # prefix matching in SQL would mean one query per term.
        balances_by_scope = {}
        for date_scope in set(expressions.mapped('date_scope')):
            domain = self._get_base_domain(options, date_scope, column_group_key)
            groups = self.env['account.move.line']._read_group(domain, groupby=['account_id'], aggregates=['balance:sum'])
            balances_by_scope[date_scope] = {account.id: balance for account, balance in groups}

        # Resolve every account once; ``code`` is company-dependent so it has to
        # be read through the ORM rather than matched in SQL.
        all_account_ids = {aid for balances in balances_by_scope.values() for aid in balances}
        accounts = self.env['account.account'].browse(sorted(all_account_ids))
        codes = {account.id: (account.code or '') for account in accounts}
        tags_by_account = {account.id: set(account.tag_ids.ids) for account in accounts}

        results = {}
        for expression in expressions:
            balances = balances_by_scope[expression.date_scope]
            total = 0.0
            for token in ACCOUNT_CODES_SPLIT_REGEX.split(expression.formula.replace(' ', '')):
                if not token:
                    continue
                match = ACCOUNT_CODES_TERM_REGEX.match(token)
                if not match:
                    raise UserError(_("Invalid account code formula %(formula)s", formula=expression.formula))
                sign = -1 if match['sign'] == '-' else 1
                prefix = match['prefix']
                excluded = [p for p in (match['excluded_prefixes'] or '').split(',') if p]
                balance_character = match['balance_character']

                tag_match = re.match(r'^tag\(([\w.]+)\)$', prefix)
                matching_tag_ids = None
                if tag_match:
                    matching_tag_ids = self._resolve_account_tag(tag_match.group(1))

                for account_id, balance in balances.items():
                    if matching_tag_ids is not None:
                        if not (tags_by_account.get(account_id, set()) & matching_tag_ids):
                            continue
                    else:
                        code = codes.get(account_id, '')
                        if not code.startswith(prefix):
                            continue
                        if any(code.startswith(ex) for ex in excluded):
                            continue
                    # D keeps debit-natured accounts, C keeps credit ones and
                    # reports them positively.
                    if balance_character == 'D':
                        if balance < 0:
                            continue
                    elif balance_character == 'C':
                        if balance > 0:
                            continue
                        balance = -balance
                    total += sign * balance
            results[expression.id] = {'value': total}
        return results

    def _resolve_account_tag(self, tag_ref):
        """Resolve ``tag(...)`` to a set of ``account.account.tag`` ids."""
        tag = self.env.ref(tag_ref, raise_if_not_found=False)
        if tag:
            return set(tag.ids)
        tags = self.env['account.account.tag'].search([('name', '=', tag_ref)])
        return set(tags.ids)

    # -- domain --------------------------------------------------------

    def _compute_engine_domain(self, expressions, options, column_group_key):
        """Sum a field over journal items matching an arbitrary domain."""
        results = {}
        for expression in expressions:
            domain = Domain(ast.literal_eval(expression.formula)) & self._get_base_domain(options, expression.date_scope, column_group_key)
            subformula = (expression.subformula or 'sum').strip()
            sign = -1 if subformula.startswith('-') else 1
            aggregated = self.env['account.move.line']._read_group(domain, aggregates=['balance:sum'])
            total = aggregated[0][0] or 0.0
            results[expression.id] = {'value': sign * total}
        return results

    # -- tax_tags ------------------------------------------------------

    def _compute_engine_tax_tags(self, expressions, options, column_group_key):
        """Sum journal items carrying the tax tag named by the formula.

        A single tag exists per name and country; a formula prefixed with ``-``
        means the line reports the opposite of the tags' balance.
        """
        if not expressions:
            return {}

        tags = expressions._get_matching_tags()
        tags_by_name = defaultdict(lambda: self.env['account.account.tag'])
        for tag in tags:
            tags_by_name[tag.name] |= tag

        results = {}
        for date_scope in set(expressions.mapped('date_scope')):
            base_domain = self._get_base_domain(options, date_scope, column_group_key)
            for expression in expressions.filtered(lambda e: e.date_scope == date_scope):
                matching = tags_by_name.get(expression.formula.lstrip('-'))
                if not matching:
                    results[expression.id] = {'value': 0.0}
                    continue
                aggregated = self.env['account.move.line']._read_group(
                    Domain(base_domain) & Domain('tax_tag_ids', 'in', matching.ids),
                    aggregates=['balance:sum'],
                )
                balance = aggregated[0][0] or 0.0
                results[expression.id] = {
                    'value': -balance if expression.formula.startswith('-') else balance,
                }
        return results

    # -- external ------------------------------------------------------

    def _compute_engine_external(self, expressions, options, column_group_key):
        """Read manually-encoded values from ``account.report.external.value``."""
        results = {}
        group = options['column_groups'][column_group_key]
        for expression in expressions:
            date_from, date_to = self._get_date_scope_range(
                expression.date_scope,
                fields.Date.to_date(group['date_from']),
                fields.Date.to_date(group['date_to']),
            )
            domain = [
                ('target_report_expression_id', '=', expression.id),
                ('date', '<=', date_to),
                ('company_id', 'in', self.env.companies.ids),
            ]
            if date_from:
                domain.append(('date', '>=', date_from))
            values = self.env['account.report.external.value'].search(domain, order='date desc')
            subformula = (expression.subformula or 'sum').strip()
            if subformula == 'most_recent':
                results[expression.id] = {'value': values[0].value if values else 0.0}
            else:
                results[expression.id] = {'value': sum(values.mapped('value'))}
        return results

    # -- aggregation ---------------------------------------------------

    def _compute_engine_aggregation(self, expressions, options, column_group_key, resolved):
        """Combine other expressions arithmetically, e.g. ``ASSETS.balance - LIAB.balance``."""
        if not expressions:
            return {}

        by_code = {}
        for expression in self._get_report_lines().expression_ids:
            if expression.report_line_id.code:
                by_code['%s.%s' % (expression.report_line_id.code, expression.label)] = expression

        results = {}
        pending = list(expressions)
        # Aggregations may reference one another; loop until nothing new resolves.
        for _pass in range(len(pending) + 1):
            still_pending = []
            for expression in pending:
                value = self._eval_aggregation(expression, by_code, resolved, options, column_group_key)
                if value is None:
                    still_pending.append(expression)
                else:
                    resolved[expression.id] = {'value': value}
                    results[expression.id] = {'value': value}
            if not still_pending or len(still_pending) == len(pending):
                pending = still_pending
                break
            pending = still_pending

        for expression in pending:
            # A cycle, or a reference to a line that is not part of this report.
            results[expression.id] = {'value': 0.0}
        return results

    def _eval_aggregation(self, expression, by_code, resolved, options, column_group_key):
        """Return the aggregation's value, or ``None`` while operands are missing."""
        formula = (expression.formula or '').strip()

        if formula == 'sum_children':
            total = 0.0
            for child in expression.report_line_id.children_ids:
                child_expression = child.expression_ids.filtered(lambda e: e.label == expression.label)
                if not child_expression:
                    continue
                if child_expression.id not in resolved:
                    return None
                total += resolved[child_expression.id]['value']
            return total

        # Substitute every ``line_code.label`` operand with its resolved value,
        # then evaluate the remaining pure arithmetic.
        substituted = formula
        for match in reversed(list(AGGREGATION_TERM_REGEX.finditer(formula))):
            key = '%s.%s' % (match.group('line_code'), match.group('expr_label'))
            operand = by_code.get(key)
            if operand is None:
                return 0.0
            if operand.id not in resolved:
                return None
            value = resolved[operand.id]['value']
            substituted = substituted[:match.start()] + repr(value) + substituted[match.end():]

        try:
            value = float(eval(substituted, {'__builtins__': {}}, {}))  # noqa: S307 - operands are numeric literals
        except (SyntaxError, NameError, TypeError, ValueError, ZeroDivisionError):
            return 0.0

        return self._apply_aggregation_subformula(expression, value)

    def _apply_aggregation_subformula(self, expression, value):
        subformula = (expression.subformula or '').strip()
        if not subformula:
            return value
        if_above = re.match(r'^if_above\(([A-Z]{3})\(([^)]+)\)\)$', subformula)
        if if_above:
            return value if value > float(if_above.group(2)) else 0.0
        if_below = re.match(r'^if_below\(([A-Z]{3})\(([^)]+)\)\)$', subformula)
        if if_below:
            return value if value < float(if_below.group(2)) else 0.0
        if subformula == 'round':
            return round(value)
        return value

    # ------------------------------------------------------------------
    # Line building
    # ------------------------------------------------------------------

    def _get_lines(self, options):
        """Render the report into a flat, ordered list of line dictionaries.

        Lines are flat rather than nested: each carries a ``level`` and a
        ``parent_id`` so the client can indent and fold without walking a tree.
        """
        self.ensure_one()

        column_groups = list(dict.fromkeys(column['column_group_key'] for column in options['columns']))
        report_lines = self._get_report_lines()
        totals_by_group = {
            group_key: self._compute_expression_values(options, group_key, lines=report_lines)
            for group_key in column_groups
        }

        handler = self._get_custom_handler_model()
        if handler is not None and hasattr(handler, '_dynamic_lines_generator'):
            return handler._dynamic_lines_generator(self, options, totals_by_group)

        lines = []
        for report_line in report_lines.filtered(lambda line: not line.parent_id):
            self._append_report_line(lines, report_line, options, totals_by_group, parent_line_id=None)
        return lines

    def _append_report_line(self, lines, report_line, options, totals_by_group, parent_line_id):
        line_id = self._build_line_id(
            self._parse_line_id(parent_line_id) + [(None, 'account.report.line', report_line.id)]
        )
        columns = self._build_columns_for_report_line(report_line, options, totals_by_group)

        if report_line.hide_if_zero and all(self._is_column_zero(column) for column in columns):
            return

        has_children = bool(report_line.children_ids)
        expandable = has_children or bool(report_line.groupby or report_line.user_groupby)
        unfolded = (
            not report_line.foldable
            or options.get('unfold_all')
            or line_id in options.get('unfolded_lines', [])
        )

        lines.append({
            'id': line_id,
            'name': report_line.name,
            'level': report_line.hierarchy_level,
            'columns': columns,
            'unfoldable': expandable and report_line.foldable,
            'unfolded': unfolded if expandable else False,
            'parent_id': parent_line_id,
            'caret_options': False,
            'action_id': report_line.action_id.id if report_line.action_id else False,
            'class': 'total' if not report_line.parent_id and has_children else '',
            'report_line_id': report_line.id,
        })

        if not unfolded:
            return

        for child in report_line.children_ids.sorted(lambda line: (line.sequence, line.id)):
            self._append_report_line(lines, child, options, totals_by_group, parent_line_id=line_id)

        groupby = report_line.user_groupby or report_line.groupby
        if groupby:
            lines.extend(self._expand_line_groupby(report_line, line_id, groupby, options))

        # A section that has been broken open is easier to read when it closes
        # on its own total, rather than leaving the reader to add the children up.
        # This applies equally to a line broken down by account, which is what
        # puts "Total Accounts Payable" under the accounts making it up.
        if self.show_section_totals and (has_children or groupby):
            lines.append({
                'id': self._build_line_id(
                    self._parse_line_id(line_id) + [('total', None, 0)]
                ),
                'name': _("Total %(section)s", section=report_line.name),
                'level': report_line.hierarchy_level,
                'columns': columns,
                'unfoldable': False,
                'unfolded': False,
                'parent_id': line_id,
                'caret_options': False,
                'class': 'subtotal',
            })

    def _build_columns_for_report_line(self, report_line, options, totals_by_group):
        expressions_by_label = {expression.label: expression for expression in report_line.expression_ids}
        columns = []
        for column in options['columns']:
            expression = expressions_by_label.get(column['expression_label'])
            totals = totals_by_group.get(column['column_group_key'], {})
            value = totals.get(expression.id, {}).get('value') if expression else None
            figure_type = (expression.figure_type if expression and expression.figure_type else column['figure_type'])
            blank_if_zero = column['blank_if_zero'] or (expression.blank_if_zero if expression else False)
            columns.append({
                'name': self._format_value(value, figure_type, blank_if_zero),
                'no_format': value,
                'figure_type': figure_type,
                'expression_label': column['expression_label'],
                'column_group_key': column['column_group_key'],
                'auditable': bool(expression and expression.auditable),
            })
        return columns

    @api.model
    def _is_column_zero(self, column):
        value = column.get('no_format')
        return value is None or (isinstance(value, float) and float_is_zero(value, precision_digits=6))

    def _format_value(self, value, figure_type, blank_if_zero=False):
        """Render a raw value the way its column declares it should be read."""
        if value is None:
            return ''
        if figure_type in ('monetary', 'float', 'integer', 'percentage'):
            if blank_if_zero and float_is_zero(value or 0.0, precision_digits=6):
                return ''
            if figure_type == 'monetary':
                return formatLang(self.env, value or 0.0, currency_obj=self.env.company.currency_id)
            if figure_type == 'integer':
                return formatLang(self.env, value or 0.0, digits=0)
            if figure_type == 'percentage':
                return '%s%%' % formatLang(self.env, value or 0.0)
            return formatLang(self.env, value or 0.0)
        if figure_type == 'date':
            return format_date(self.env, value) if value else ''
        if figure_type == 'boolean':
            return _("Yes") if value else _("No")
        return str(value) if value else ''

    # ------------------------------------------------------------------
    # Unfolding
    # ------------------------------------------------------------------

    def _expand_line_groupby(self, report_line, parent_line_id, groupby, options, extra_domain=None, depth=1):
        """Break a line down by the first field of its ``groupby``.

        A comma-separated groupby nests: unfolding a bucket breaks it down by
        the next field, restricted to that bucket via ``extra_domain``. That is
        what lets an income account be split by journal, separating point of
        sale takings from ordinary invoicing.
        """
        groupby_fields = [field.strip() for field in groupby.split(',') if field.strip()]
        if not groupby_fields:
            return []
        current_field = groupby_fields[0]
        remaining = ','.join(groupby_fields[1:])

        expressions = report_line.expression_ids.filtered(lambda e: e.engine in ('domain', 'account_codes', 'tax_tags'))
        if not expressions:
            return []

        sublines = []
        grouped_values = self._compute_groupby_values(report_line, expressions, current_field, options, extra_domain)
        comodel = self.env['account.move.line']._fields[current_field].comodel_name

        for record_id, label, values_by_key in grouped_values:
            line_id = self._build_line_id(
                self._parse_line_id(parent_line_id) + [('groupby', comodel or current_field, record_id)]
            )
            columns = []
            for column in options['columns']:
                value = values_by_key.get((column['column_group_key'], column['expression_label']))
                columns.append({
                    'name': self._format_value(value, column['figure_type'], column['blank_if_zero']),
                    'no_format': value,
                    'figure_type': column['figure_type'],
                    'expression_label': column['expression_label'],
                    'column_group_key': column['column_group_key'],
                    'auditable': True,
                })
            unfolded = bool(remaining) and (
                options.get('unfold_all') or line_id in options.get('unfolded_lines', [])
            )
            sublines.append({
                'id': line_id,
                'name': label,
                'level': report_line.hierarchy_level + depth,
                'columns': columns,
                'unfoldable': bool(remaining),
                'unfolded': unfolded,
                'parent_id': parent_line_id,
                'caret_options': comodel,
                'groupby': remaining,
                'class': '',
            })
            if unfolded:
                # Narrow the next level to the bucket just rendered.
                bucket_domain = Domain(current_field, '=', record_id)
                if extra_domain is not None:
                    bucket_domain = Domain(extra_domain) & bucket_domain
                sublines.extend(self._expand_line_groupby(
                    report_line, line_id, remaining, options,
                    extra_domain=bucket_domain, depth=depth + 1,
                ))
        return sublines

    def _compute_groupby_values(self, report_line, expressions, groupby_field, options, extra_domain=None):
        """Aggregate a line's expressions one bucket per value of ``groupby_field``."""
        field = self.env['account.move.line']._fields[groupby_field]
        buckets = {}
        order = []

        for column in options['columns']:
            expression = expressions.filtered(lambda e: e.label == column['expression_label'])[:1]
            if not expression:
                continue
            domain = self._get_groupby_domain(expression, options, column['column_group_key'])
            if extra_domain is not None:
                domain = Domain(domain) & Domain(extra_domain)
            groups = self.env['account.move.line']._read_group(
                domain, groupby=[groupby_field], aggregates=['balance:sum'],
            )
            sign = -1 if (expression.subformula or '').strip().startswith('-') else 1
            for record, balance in groups:
                key = record.id if field.relational else record
                if key not in buckets:
                    buckets[key] = {}
                    label = record.display_name if field.relational else str(record or _("None"))
                    order.append((key, label))
                buckets[key][(column['column_group_key'], column['expression_label'])] = sign * balance

        return [(key, label, buckets[key]) for key, label in order]

    def _get_groupby_domain(self, expression, options, column_group_key):
        base = self._get_base_domain(options, expression.date_scope, column_group_key)
        if expression.engine == 'domain':
            return Domain(ast.literal_eval(expression.formula)) & base
        if expression.engine == 'tax_tags':
            tags = expression._get_matching_tags()
            return Domain('tax_tag_ids', 'in', tags.ids) & base
        # account_codes: restrict to the accounts the prefixes resolve to.
        account_ids = self._resolve_account_codes_accounts(expression)
        return Domain('account_id', 'in', account_ids) & base

    def _resolve_account_codes_accounts(self, expression):
        account_ids = set()
        for token in ACCOUNT_CODES_SPLIT_REGEX.split(expression.formula.replace(' ', '')):
            if not token:
                continue
            match = ACCOUNT_CODES_TERM_REGEX.match(token)
            if not match:
                continue
            prefix = match['prefix']
            tag_match = re.match(r'^tag\(([\w.]+)\)$', prefix)
            if tag_match:
                domain = [('tag_ids', 'in', list(self._resolve_account_tag(tag_match.group(1))))]
            else:
                domain = [('code', '=like', '%s%%' % prefix)]
            excluded = [p for p in (match['excluded_prefixes'] or '').split(',') if p]
            for excluded_prefix in excluded:
                domain.append(('code', 'not like', '%s%%' % excluded_prefix))
            account_ids.update(self.env['account.account'].search(domain).ids)
        return list(account_ids)

    def _expand_line(self, options, line_id, groupby):
        """Entry point used by the client when unfolding a generated subline."""
        self.ensure_one()
        report_line_id = None
        for _markup, model, value in self._parse_line_id(line_id):
            if model == 'account.report.line':
                report_line_id = value
        if not report_line_id:
            return []
        report_line = self.env['account.report.line'].browse(report_line_id)
        return self._expand_line_groupby(report_line, line_id, groupby, options)
