import { useService, useBus } from "@web/core/utils/hooks";
import { NavBar } from "@web/webclient/navbar/navbar";
import { _t } from "@web/core/l10n/translation";
import { useEffect, useRef } from "@odoo/owl";

export class ResponsiveNavBar extends NavBar {
    static template = "jkm_web_resposive.ResponsiveNavBar";

    setup() {
        super.setup();
        this.hm = useService("home_menu");
        this.pwa = useService("pwa");
        this.menuAppsRef = useRef("menuApps");
        this.navRef = useRef("nav");
        useBus(this.env.bus, "HOME-MENU:TOGGLED", () => this._updateMenuAppsIcon());
        useEffect(() => this._updateMenuAppsIcon());
    }

    get isInApp() {
        return !this.hm.hasHomeMenu;
    }

    get hasBackgroundAction() {
        return this.hm.hasBackgroundAction;
    }

    _openAppMenuSidebar() {
        if (this.hm.hasHomeMenu) {
            this.hm.toggle(false);
        } else {
            this.state.isAppMenuSidebarOpened = true;
        }
    }

    onAllAppsBtnClick() {
        super.onAllAppsBtnClick();
        this.hm.toggle(true);
        this._closeAppMenuSidebar();
    }

    _updateMenuAppsIcon() {
        const menuAppsEl = this.menuAppsRef.el;
        if (!menuAppsEl) {
            return;
        }
        const isInApp = this.isInApp;
        menuAppsEl.classList.toggle("o_hidden", !isInApp && !this.hasBackgroundAction);
        menuAppsEl.classList.toggle("o_menu_toggle_back", !isInApp && this.hasBackgroundAction);
        if (!this.isScopedApp) {
            const title = !isInApp && this.hasBackgroundAction ? _t("Previous view") : _t("Home menu");
            menuAppsEl.title = title;
            menuAppsEl.ariaLabel = title;
        }
        const menuBrand = this.navRef.el?.querySelector(".o_menu_brand");
        if (menuBrand) menuBrand.classList.toggle("o_hidden", !isInApp);
        const menuBrandIcon = this.navRef.el?.querySelector(".o_menu_brand_icon");
        if (menuBrandIcon) menuBrandIcon.classList.toggle("o_hidden", !isInApp);
        if (this.appSubMenus.el) this.appSubMenus.el.classList.toggle("o_hidden", !isInApp);
        const breadcrumb = this.navRef.el?.querySelector(".o_breadcrumb");
        if (breadcrumb) breadcrumb.classList.toggle("o_hidden", !isInApp);
    }
}
