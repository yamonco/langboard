import { PANEL_DESIGN_TOKENS, type PanelDesign } from "../../../../sdk/js/index.mjs";

interface ResourceManifest {
    version: number;
    module_url: string;
    css_url: string;
}

export function readPanelDesign(): Omit<PanelDesign, "resources"> {
    const element = document.documentElement;
    const style = getComputedStyle(element);
    const tokens = Object.fromEntries(PANEL_DESIGN_TOKENS.map((name) => [name, style.getPropertyValue(name).trim()]));
    return { mode: element.classList.contains("dark") ? "dark" : "light", tokens };
}

export async function loadPanelResources(signal: AbortSignal): Promise<NonNullable<PanelDesign["resources"]>> {
    const response = await fetch(new URL("/panel-sdk-resources.json", window.location.origin), { signal, credentials: "omit", cache: "no-cache" });
    if (!response.ok) throw new Error("Panel widget resources unavailable");
    const text = await response.text();
    if (text.length > 8192) throw new Error("Panel resource manifest is too large");
    const manifest: ResourceManifest = JSON.parse(text);
    if (manifest.version !== 1) throw new Error("Unsupported panel widget resources");
    const resolve = (path: string) => {
        if (typeof path !== "string" || !path || path.length > 2048) throw new Error("Invalid panel resource URL");
        if (typeof path !== "string" || path.length > 2048) throw new Error("Invalid panel resource URL");
        const url = new URL(path, window.location.origin);
        if (url.origin !== window.location.origin || url.username || url.password) throw new Error("Panel resources must share the host origin");
        return url.href;
    };
    return { module_url: resolve(manifest.module_url), css_url: resolve(manifest.css_url) };
}
