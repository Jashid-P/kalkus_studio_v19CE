import { hasTouch, isIosApp, isMacOS } from "@web/core/browser/feature_detection";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import {
    Component,
    onMounted,
    onPatched,
    useExternalListener,
    useRef,
    useState,
} from "@odoo/owl";

/**
 * Footer shown at the bottom of the command palette when it is opened from the
 * home menu, hinting that the palette is reachable from anywhere.
 */
class FooterComponent extends Component {
    static template = "jkm_web_resposive.HomeMenu.CommandPalette.Footer";
    static props = {
        // injected by the command palette
        switchNamespace: { type: Function, optional: true },
    };

    setup() {
        this.controlKey = isMacOS() ? "COMMAND" : "CONTROL";
    }
}

export class HomeMenu extends Component {
    static template = "jkm_web_resposive.HomeMenu";
    static props = {
        apps: { type: Array },
        reorderApps: { type: Function },
    };

    setup() {
        this.menus = useService("menu");
        this.homeMenu = useService("home_menu");
        this.command = useService("command");
        this.ui = useService("ui");
        this.state = useState({ focusedIndex: null, isIosApp: isIosApp() });
        this.searchRef = useRef("search");
        this.draggedApp = null;

        if (!this.env.isSmall) {
            this.registerHotkeys();
        }
        onMounted(() => {
            if (!hasTouch()) {
                this.focusSearch();
            }
        });
        onPatched(() => {
            if (this.state.focusedIndex !== null) {
                document.querySelector(".o_home_menu .o_app.o_focused")
                    ?.scrollIntoView({ block: "center" });
            }
        });
    }

    get displayedApps() {
        // Searching is delegated to the command palette, so the grid always
        // shows every app.
        return this.props.apps;
    }

    get maxIconNumber() {
        if (window.innerWidth < 576) return 3;
        if (window.innerWidth < 768) return 4;
        return 6;
    }

    selectApp(app) {
        return this.menus.selectMenu(app);
    }

    focusSearch() {
        if (!this.env.isSmall) {
            this.searchRef.el?.focus({ preventScroll: true });
        }
    }

    /**
     * Typing anywhere on the home menu hands over to the command palette,
     * pre-seeded with the "/" namespace so it searches the whole menu tree
     * rather than just the app names.
     */
    onSearchInput() {
        const onClose = () => {
            this.focusSearch();
            if (this.searchRef.el) {
                this.searchRef.el.value = "";
            }
        };
        // While an IME composition is in progress the input value is not yet
        // final, so open on the bare namespace and let the palette take over.
        const searchValue = this.compositionStart
            ? "/"
            : `/${this.searchRef.el.value.trim()}`;
        this.compositionStart = false;
        this.command.openMainPalette({ searchValue, FooterComponent }, onClose);
    }

    onSearchBlur() {
        if (hasTouch()) {
            return;
        }
        // Losing focus to the body (e.g. clicking a non-interactive element)
        // would break IME input, so take the focus back.
        setTimeout(() => {
            if (document.activeElement === document.body && this.ui.activeElement === document) {
                this.focusSearch();
            }
        }, 0);
    }

    onCompositionStart() {
        this.compositionStart = true;
    }

    /**
     * Keeps the hidden input focused so that typing anywhere on the home menu
     * starts a search, unless the user is already typing in another field.
     */
    onWindowKeydown() {
        if (
            document.activeElement !== this.searchRef.el &&
            this.ui.activeElement === document &&
            !["TEXTAREA", "INPUT"].includes(document.activeElement.tagName)
        ) {
            this.focusSearch();
        }
    }

    onDragStart(app, ev) {
        this.draggedApp = app;
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData("text/plain", app.xmlid);
    }

    onDragOver(ev) {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "move";
    }

    async onDrop(target, ev) {
        ev.preventDefault();
        if (!this.draggedApp || target === this.draggedApp) return;
        const apps = [...this.props.apps];
        const from = apps.indexOf(this.draggedApp);
        const to = apps.indexOf(target);
        apps.splice(from, 1);
        apps.splice(to, 0, this.draggedApp);
        const order = apps.map((app) => app.xmlid);
        this.props.reorderApps(order);
        await user.setUserSettings("homemenu_config", JSON.stringify(order));
        this.draggedApp = null;
    }

    registerHotkeys() {
        useHotkey("ArrowDown", () => this.moveFocus("nextLine"));
        useHotkey("ArrowUp", () => this.moveFocus("previousLine"));
        useHotkey("ArrowRight", () => this.moveFocus("nextColumn"));
        useHotkey("ArrowLeft", () => this.moveFocus("previousColumn"));
        useHotkey("Tab", () => this.moveFocus("nextElem"));
        useHotkey("shift+Tab", () => this.moveFocus("previousElem"));
        useHotkey("Enter", () => {
            const app = this.displayedApps[this.state.focusedIndex];
            if (app) this.selectApp(app);
        });
        useHotkey("Escape", () => this.homeMenu.toggle(false));
        useExternalListener(window, "keydown", this.onWindowKeydown);
    }

    moveFocus(direction) {
        const count = this.displayedApps.length;
        const lastIndex = count - 1;
        if (lastIndex < 0) {
            return;
        }
        if (this.state.focusedIndex === null) {
            this.state.focusedIndex = 0;
            return;
        }
        const columns = this.maxIconNumber;
        const current = this.state.focusedIndex;
        let next;
        switch (direction) {
            case "previousElem":
                next = current - 1;
                break;
            case "nextElem":
                next = current + 1;
                break;
            case "previousColumn":
                next = current % columns
                    ? current - 1
                    : current + Math.min(lastIndex - current, columns - 1);
                break;
            case "nextColumn":
                next = current === lastIndex || (current + 1) % columns === 0
                    ? current - (current % columns)
                    : current + 1;
                break;
            case "nextLine":
                next = Math.min(current + columns, lastIndex);
                break;
            case "previousLine":
                next = Math.max(current - columns, 0);
                break;
        }
        this.state.focusedIndex = Math.max(0, Math.min(next, lastIndex));
    }
}
