import { browser } from "@web/core/browser/browser";
import { cookie } from "@web/core/browser/cookie";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

function systemColorScheme() {
    return browser.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function currentColorScheme() {
    return cookie.get("color_scheme");
}

export const colorSchemeService = {
    async start() {
        let newColorScheme = systemColorScheme();
        if (["light", "dark"].includes(user.settings.color_scheme)) {
            newColorScheme = user.settings.color_scheme;
        }
        const current = currentColorScheme();
        if (newColorScheme !== current) {
            cookie.set("color_scheme", newColorScheme);
            if (current || (!current && newColorScheme === "dark")) {
                browser.location.reload();
                await new Promise(() => {});
            }
        }
        return {
            get systemColorScheme() {
                return systemColorScheme();
            },
            get currentColorScheme() {
                return currentColorScheme();
            },
            get userColorScheme() {
                return user.settings.color_scheme;
            },
        };
    },
};

registry.category("services").add("color_scheme", colorSchemeService);
