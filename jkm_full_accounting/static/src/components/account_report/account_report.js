/** @odoo-module */

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { Chatter } from "@mail/chatter/web_portal/chatter";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { formatDate } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";

const { DateTime } = luxon;

/** Named periods offered by the date filter, mirroring the server's resolver. */
const DATE_FILTERS = [
    { id: "this_year", label: _t("This Year") },
    { id: "this_quarter", label: _t("This Quarter") },
    { id: "this_month", label: _t("This Month") },
    { id: "today", label: _t("Today") },
    { id: "previous_year", label: _t("Last Year") },
    { id: "previous_quarter", label: _t("Last Quarter") },
    { id: "previous_month", label: _t("Last Month") },
];

const COMPARISON_FILTERS = [
    { id: "no_comparison", label: _t("No Comparison") },
    { id: "previous_period", label: _t("Previous Period") },
    { id: "same_last_year", label: _t("Same Period Last Year") },
];

export class CommunityAccountReport extends Component {
    static template = "jkm_full_accounting.CommunityAccountReport";
    static components = { Chatter, Dropdown, DropdownItem };
    static props = { action: Object, "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            payload: null,
            loading: true,
            error: null,
            customDateFrom: "",
            customDateTo: "",
            chatter: null,
            search: "",
        });
        this.dateFilters = DATE_FILTERS;
        this.comparisonFilters = COMPARISON_FILTERS;
        this.reportId = this.props.action.context.report_id;
        // Filter as the user types; the pause keeps a long report from being
        // rebuilt on every keystroke.
        this.onSearchInput = useDebounced(() => this.applySearch(), 400);
        onWillStart(() => this.load(this.props.action.context.default_options || {}));
    }

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------

    async load(previousOptions) {
        this.state.loading = true;
        this.state.error = null;
        try {
            const payload = await this.orm.call("account.report", "get_report_data", [
                this.reportId,
                previousOptions,
            ]);
            this.state.payload = payload;
            this.state.customDateFrom = payload.options.date.date_from || "";
            this.state.customDateTo = payload.options.date.date_to || "";
            this.state.search = payload.options.search || "";
        } catch (error) {
            this.state.error = error.message || _t("Unable to load the accounting report.");
        } finally {
            this.state.loading = false;
        }
    }

    get options() {
        return this.state.payload?.options || {};
    }

    get columns() {
        return this.options.columns || [];
    }

    get columnHeaders() {
        return this.options.column_headers || [];
    }

    get lines() {
        return this.state.payload?.lines || [];
    }

    get warnings() {
        return this.state.payload?.warnings || [];
    }

    get annotations() {
        return this.state.payload?.annotations || {};
    }

    annotationFor(line) {
        return this.annotations[line.id];
    }

    /**
     * Row icons belong to the records themselves, not to the rows that summarise
     * them. A line that folds open is a heading for what is underneath it; its
     * actions are the named badges instead.
     */
    hasRecord(line) {
        return Boolean(line.caret_options) && !line.unfoldable;
    }

    canAnnotate(line) {
        return this.hasRecord(line);
    }

    /** Accounts and partners aggregate journal items, so they can show them. */
    hasJournalItems(line) {
        return line.unfoldable && ["account.account", "res.partner"].includes(line.caret_options);
    }

    /** Name what the action opens; "Open Record" says nothing useful. */
    openRecordLabel(line) {
        return {
            "account.move.line": _t("View Journal Entry"),
            "res.partner": _t("View Partner"),
            "account.account": _t("View Account"),
            "account.tax": _t("View Tax"),
        }[line.caret_options] || _t("View Record");
    }

    /**
     * Label for the badge opening the record a line stands for. Naming the
     * record type is clearer than a bare icon when a row carries several
     * actions.
     */
    recordBadgeLabel(line) {
        // A journal item reaches its entry through the row icons, so it needs
        // no badge of its own.
        if (!line.unfoldable) {
            return false;
        }
        return {
            "res.partner": _t("Partner"),
            "account.account": _t("Account"),
            "account.tax": _t("Tax"),
        }[line.caret_options];
    }

    /** Only an account can be traced through to the ledger. */
    hasGeneralLedger(line) {
        return line.caret_options === "account.account";
    }

    async openGeneralLedger(line) {
        const action = await this.orm.call("account.report", "action_open_general_ledger", [
            this.reportId,
            line.id,
            this.options,
        ]);
        if (action) {
            this.action.doAction(action);
        }
    }

    /** A tax figure is checked against the entries it was built from. */
    hasTaxAudit(line) {
        return line.caret_options === "account.tax";
    }

    async openTaxAudit(line) {
        const action = await this.orm.call("account.report", "action_open_tax_audit", [
            this.reportId,
            line.id,
            this.options,
        ]);
        if (action) {
            this.action.doAction(action);
        }
    }

    async openJournalItems(line) {
        const action = await this.orm.call("account.report", "action_open_journal_items", [
            this.reportId,
            line.id,
            this.options,
        ]);
        if (action) {
            this.action.doAction(action);
        }
    }

    async openLineRecord(line) {
        const action = await this.orm.call("account.report", "action_open_line_record", [
            this.reportId,
            line.id,
        ]);
        if (action) {
            this.action.doAction(action);
        }
    }

    /**
     * Show the conversation attached to the line's record. Lines with nothing
     * to talk to - a report's own section headings - fall back to a plain note,
     * so the icon does something useful on every report.
     */
    async openChatter(line) {
        const thread = await this.orm.call("account.report", "get_line_thread", [
            this.reportId,
            line.id,
        ]);
        if (!thread) {
            return this.editAnnotation(line);
        }
        this.state.chatter = {
            model: thread.model,
            id: thread.id,
            name: thread.name,
            lineId: line.id,
        };
    }

    closeChatter() {
        this.state.chatter = null;
    }

    async editAnnotation(line) {
        const current = this.annotationFor(line);
        const text = window.prompt(_t("Note for %s", line.name), current?.text || "");
        if (text === null) {
            return;
        }
        const result = await this.orm.call("account.report", "set_line_annotation", [
            this.reportId,
            line.id,
            text,
        ]);
        // Patch in place so the whole report does not have to be recomputed.
        if (result) {
            this.state.payload.annotations[line.id] = result;
        } else {
            delete this.state.payload.annotations[line.id];
        }
    }

    get hasSearch() {
        return Boolean(this.state.payload?.report?.search_bar);
    }

    get reportName() {
        return this.state.payload?.report?.name || _t("Accounting Report");
    }

    /**
     * Statement reports (Balance Sheet, P&L) read as banded sections; ledger
     * reports (General Ledger, Aged Balance...) are a flat table. Both sit on
     * the same centred sheet; a table with many columns scrolls within it
     * rather than stretching the page edge to edge.
     */
    get sheetClass() {
        const report = this.state.payload?.report || {};
        return `layout-${report.layout || "hierarchy"}`;
    }

    copyOptions() {
        return JSON.parse(JSON.stringify(this.options));
    }

    // ------------------------------------------------------------------
    // Filter labels
    // ------------------------------------------------------------------

    get dateLabel() {
        const date = this.options.date;
        if (!date) {
            return "";
        }
        // A balance sheet is read at a date; a P&L over a span.
        if (date.mode === "single") {
            return _t("As of %s", this.formatDay(date.date_to));
        }
        return date.string || `${this.formatDay(date.date_from)} - ${this.formatDay(date.date_to)}`;
    }

    formatDay(value) {
        if (!value) {
            return "";
        }
        return formatDate(DateTime.fromISO(value));
    }

    get comparisonLabel() {
        const comparison = this.options.comparison;
        if (!comparison || comparison.filter === "no_comparison") {
            return _t("Comparison");
        }
        const match = COMPARISON_FILTERS.find((f) => f.id === comparison.filter);
        return match ? match.label : _t("Comparison");
    }

    get journalLabel() {
        const selected = (this.options.journals || []).filter((j) => j.selected);
        if (!selected.length) {
            return _t("All Journals");
        }
        if (selected.length === 1) {
            return selected[0].name;
        }
        return _t("%s Journals", selected.length);
    }

    get entriesLabel() {
        return this.options.all_entries ? _t("All Entries") : _t("Posted Entries");
    }

    // ------------------------------------------------------------------
    // Filter actions
    // ------------------------------------------------------------------

    async setDateFilter(filterId) {
        const options = this.copyOptions();
        options.date = { ...options.date, filter: filterId };
        // Drop the custom bounds so the server resolves the named period afresh.
        delete options.date.date_from;
        delete options.date.date_to;
        await this.load(options);
    }

    async applyCustomDates() {
        const options = this.copyOptions();
        options.date = {
            ...options.date,
            filter: "custom",
            date_from: this.state.customDateFrom,
            date_to: this.state.customDateTo,
        };
        await this.load(options);
    }

    async setComparison(filterId) {
        const options = this.copyOptions();
        options.comparison = { ...(options.comparison || {}), filter: filterId };
        await this.load(options);
    }

    async setComparisonPeriods(number) {
        const options = this.copyOptions();
        options.comparison = { ...(options.comparison || {}), number_period: number };
        await this.load(options);
    }

    async toggleJournal(journalId) {
        const options = this.copyOptions();
        const selected = new Set(options.selected_journal_ids || []);
        selected.has(journalId) ? selected.delete(journalId) : selected.add(journalId);
        options.selected_journal_ids = [...selected];
        await this.load(options);
    }

    async clearJournals() {
        const options = this.copyOptions();
        options.selected_journal_ids = [];
        await this.load(options);
    }

    async setAllEntries(allEntries) {
        const options = this.copyOptions();
        options.all_entries = allEntries;
        await this.load(options);
    }

    async applySearch() {
        // The fold state is left as the user set it: searching narrows what is
        // on screen rather than opening the report up underneath them.
        const options = this.copyOptions();
        options.search = this.state.search;
        await this.load(options);
    }

    async clearSearch() {
        this.state.search = "";
        await this.applySearch();
    }

    async toggleUnfoldAll() {
        const options = this.copyOptions();
        options.unfold_all = !options.unfold_all;
        options.unfolded_lines = [];
        await this.load(options);
    }

    async toggleLine(line) {
        if (!line.unfoldable) {
            return;
        }
        const options = this.copyOptions();
        const unfolded = new Set(options.unfolded_lines || []);
        unfolded.has(line.id) ? unfolded.delete(line.id) : unfolded.add(line.id);
        options.unfolded_lines = [...unfolded];
        await this.load(options);
    }

    // ------------------------------------------------------------------
    // Rendering helpers
    // ------------------------------------------------------------------

    lineClass(line) {
        const classes = [`line_level_${Math.min(line.level ?? 0, 6)}`];
        if (line.class) {
            classes.push(line.class);
        }
        if (line.unfoldable) {
            classes.push("unfoldable");
        }
        if (line.unfolded) {
            classes.push("unfolded");
        }
        return classes.join(" ");
    }

    /** Negative figures are shown in red, the way an accountant expects. */
    cellClass(column) {
        const classes = ["line_cell"];
        if (["monetary", "float", "integer", "percentage"].includes(column.figure_type)) {
            classes.push("numeric");
            if (column.no_format < 0) {
                classes.push("negative");
            }
        }
        return classes.join(" ");
    }
}

registry.category("actions").add("account_report", CommunityAccountReport);
