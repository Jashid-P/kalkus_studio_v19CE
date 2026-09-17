/** @odoo-module */

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Renders a journal item's matching number as a link to the entries it was
 * reconciled against, so a match can be inspected without leaving the list.
 */
class MatchingLink extends Component {
    static props = { ...standardFieldProps };
    static template = "jkm_full_accounting.MatchingLink";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
    }

    get matchingNumber() {
        return this.props.record.data[this.props.name] || "";
    }

    async viewMatch() {
        const action = await this.orm.call(
            "account.move.line",
            "open_reconcile_view",
            [this.props.record.resId],
            {},
        );
        this.action.doAction(action, { additionalContext: { is_matched_view: true } });
    }

    async reconcile() {
        this.action.doAction("jkm_full_accounting.action_move_line_posted_unreconciled", {
            additionalContext: {
                search_default_partner_id: this.props.record.data.partner_id?.id,
                search_default_account_id: this.props.record.data.account_id?.id,
            },
        });
    }

    get colorCode() {
        // 'P' marks a partial match and '*' several of them; the rest is the
        // full-reconcile number, cycled over the 11 usable tag colours.
        const value = this.matchingNumber.replace("P", "");
        if (!value || value === "*") {
            return 0;
        }
        return (parseInt(value, 10) % 11) + 1;
    }
}

registry.category("fields").add("matching_link_widget", {
    component: MatchingLink,
});
