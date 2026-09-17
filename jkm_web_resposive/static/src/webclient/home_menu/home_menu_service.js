import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { Mutex } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
import {
    ControllerNotFoundError,
    standardActionServiceProps,
} from "@web/webclient/actions/action_service";
import { computeAppsAndMenuItems, reorderApps } from "@web/webclient/menus/menu_helpers";
import { Component, onMounted, onWillUnmount, reactive, useState, xml } from "@odoo/owl";
import { HomeMenu } from "./home_menu";

export const homeMenuService = {
    dependencies: ["action"],
    start(env) {
        const state = reactive({
            hasHomeMenu: false,
            hasBackgroundAction: false,
            toggle,
        });
        const mutex = new Mutex();

        class HomeMenuAction extends Component {
            static components = { HomeMenu };
            static target = "current";
            static props = { ...standardActionServiceProps };
            static template = xml`<HomeMenu t-props="homeMenuProps"/>`;
            static displayName = _t("Home");

            setup() {
                this.menus = useService("menu");
                const config = JSON.parse(user.settings?.homemenu_config || "null");
                const apps = useState(
                    computeAppsAndMenuItems(this.menus.getMenuAsTree("root")).apps
                );
                if (config) {
                    reorderApps(apps, config);
                }
                this.homeMenuProps = {
                    apps,
                    reorderApps: (order) => reorderApps(apps, order),
                };
                onMounted(() => {
                    state.hasHomeMenu = true;
                    state.hasBackgroundAction = this.env.config.breadcrumbs.length > 0;
                    this.env.bus.trigger("HOME-MENU:TOGGLED");
                });
                onWillUnmount(() => {
                    state.hasHomeMenu = false;
                    state.hasBackgroundAction = false;
                    this.env.bus.trigger("HOME-MENU:TOGGLED");
                });
            }
        }

        registry.category("actions").add("menu", HomeMenuAction);
        env.bus.addEventListener("HOME-MENU:TOGGLED", () => {
            document.body.classList.toggle("o_home_menu_background", state.hasHomeMenu);
        });

        async function toggle(show) {
            return mutex.exec(async () => {
                show = show === undefined ? !state.hasHomeMenu : Boolean(show);
                if (show !== state.hasHomeMenu) {
                    if (show) {
                        await env.services.action.doAction("menu");
                    } else {
                        try {
                            await env.services.action.restore();
                        } catch (error) {
                            if (!(error instanceof ControllerNotFoundError)) {
                                throw error;
                            }
                        }
                    }
                }
                return new Promise((resolve) => setTimeout(resolve));
            });
        }

        return state;
    },
};

registry.category("services").add("home_menu", homeMenuService);
