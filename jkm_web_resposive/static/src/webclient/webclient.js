import { useService } from "@web/core/utils/hooks";
import { WebClient } from "@web/webclient/webclient";
import { ResponsiveNavBar } from "./navbar/navbar";

export class WebClientResponsive extends WebClient {
    static components = {
        ...WebClient.components,
        NavBar: ResponsiveNavBar,
    };

    setup() {
        super.setup();
        this.homeMenu = useService("home_menu");
    }

    _loadDefaultApp() {
        return this.homeMenu.toggle(true);
    }
}
