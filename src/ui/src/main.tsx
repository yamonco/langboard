import { ThemeProvider } from "next-themes";
import React from "react";
import ReactDOM from "react-dom/client";
import "@/core/injection";
import App from "@/App";
import { setupPreloadRecovery } from "@/core/helpers/setupPreloadRecovery";
import "@/assets/styles/main.css";

const Strict = process.env.IS_PRODUCTION !== "true" ? React.StrictMode : React.Fragment;

setupPreloadRecovery(window);

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
    ReactDOM.createRoot(document.getElementById("root")!).render(
        <Strict>
            <ThemeProvider attribute="class">
                <App />
            </ThemeProvider>
        </Strict>
    );
}
