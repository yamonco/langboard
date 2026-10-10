const reloadKey = "langboard:vite-preload-reload";
const reloadCooldown = 60_000;

export function setupPreloadRecovery(browser: Pick<Window, "addEventListener" | "sessionStorage" | "location">, now = Date.now) {
    browser.addEventListener("vite:preloadError", () => {
        // Keep Vite's rejection intact: canceling this event resolves a failed
        // dynamic import to undefined, which breaks React.lazy's module contract.
        try {
            const previous = browser.sessionStorage.getItem(reloadKey);
            const timestamp = previous === null ? NaN : Number(previous);
            const current = now();
            if (Number.isFinite(timestamp) && current - timestamp >= 0 && current - timestamp < reloadCooldown) {
                console.error("Vite chunk loading failed during the preload-error reload cooldown.");
                return;
            }
            // Persist across startup. An expired guard allows a later deployment
            // to recover without creating an immediate reload loop.
            browser.sessionStorage.setItem(reloadKey, String(current));
            browser.location.reload();
        } catch (error) {
            // Storage may be unavailable. Without a durable guard, do not reload.
            console.error("Unable to persist Vite preload recovery state.", error);
        }
    });
}
