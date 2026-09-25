import { ThemeProvider } from "next-themes";
import React from "react";
import ReactDOM from "react-dom/client";
import "@/core/injection";
import App from "@/App";
import "@/assets/styles/main.css";

const Strict = process.env.IS_PRODUCTION !== "true" ? React.StrictMode : React.Fragment;

const vitePreloadReloadKey = "langboard:vite-preload-reload";

window.addEventListener("vite:preloadError", (event) => {
    event.preventDefault();

    // A stale runtime can legitimately need one hard reload after deployment.
    // Repeated failures must stop instead of turning a missing chunk into an
    // infinite page reload loop.
    if (window.sessionStorage.getItem(vitePreloadReloadKey) === "1") {
        console.error("Vite chunk loading failed after a preload-error reload.");
        return;
    }

    window.sessionStorage.setItem(vitePreloadReloadKey, "1");
    window.location.reload();
});

const configuredPublicUIURL = new URL(process.env.PUBLIC_UI_URL || window.location.origin);
const currentURL = new URL(window.location.href);
const loopbackHostnames = new Set(["localhost", "127.0.0.1"]);

if (
    process.env.IS_PRODUCTION === "true" &&
    loopbackHostnames.has(configuredPublicUIURL.hostname) &&
    loopbackHostnames.has(currentURL.hostname) &&
    configuredPublicUIURL.origin !== currentURL.origin
) {
    currentURL.protocol = configuredPublicUIURL.protocol;
    currentURL.hostname = configuredPublicUIURL.hostname;
    currentURL.port = configuredPublicUIURL.port;
    window.location.replace(currentURL);
} else {
    window.sessionStorage.removeItem(vitePreloadReloadKey);
    ReactDOM.createRoot(document.getElementById("root")!).render(
        <Strict>
            <ThemeProvider attribute="class">
                <App />
            </ThemeProvider>
        </Strict>
    );
}
