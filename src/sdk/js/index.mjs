const encoder = new TextEncoder();
const MAX_STATE_BYTES = 16 * 1024;
const MAX_CACHE_BYTES = 256 * 1024;
const MAX_CACHE_ENTRIES = 32;
const READY_TIMEOUT_MS = 10_000;

// Validate before serialization: JSON.stringify alone silently drops unsafe values.
function snapshot(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
        throw new TypeError("Panel state must be a JSON object");
    }
    let nodes = 0;
    let contentBytes = 0;
    const countBytes = (text) => {
        contentBytes += encoder.encode(text).byteLength;
        if (contentBytes > MAX_STATE_BYTES) throw new RangeError("Panel state exceeds 16 KiB");
    };
    const ancestors = new Set();
    function visit(item, depth) {
        if (++nodes > MAX_STATE_BYTES || depth > 64) throw new RangeError("Panel state is too complex");
        if (item === null || typeof item === "boolean") return;
        if (typeof item === "string") {
            countBytes(item);
            return;
        }
        if (typeof item === "number" && Number.isFinite(item)) return;
        if (typeof item !== "object") throw new TypeError("Panel state must contain only JSON values");
        const proto = Object.getPrototypeOf(item);
        if (proto !== Object.prototype && proto !== null && !(Array.isArray(item) && proto === Array.prototype)) {
            throw new TypeError("Panel state has an unsupported prototype");
        }
        if (ancestors.has(item)) throw new TypeError("Panel state must not contain cycles");
        if (Array.isArray(item) && item.length > MAX_STATE_BYTES) throw new RangeError("Panel array is too large");
        ancestors.add(item);
        for (const key of Reflect.ownKeys(item)) {
            if (Array.isArray(item) && key === "length") continue;
            const property = Object.getOwnPropertyDescriptor(item, key);
            if (typeof key !== "string" || !property.enumerable || !("value" in property) ||
                key === "__proto__" || key === "constructor" || key === "prototype") {
                throw new TypeError("Panel state has an unsupported property");
            }
            countBytes(key);
            if (Array.isArray(item) && !/^(0|[1-9]\d*)$/.test(key)) throw new TypeError("Panel arrays must contain only indices");
            visit(property.value, depth + 1);
        }
        ancestors.delete(item);
    }
    visit(value, 0);
    const json = JSON.stringify(value);
    const bytes = encoder.encode(json).byteLength;
    if (bytes > MAX_STATE_BYTES) throw new RangeError("Panel state exceeds 16 KiB");
    return { json, bytes, value: JSON.parse(json) };
}

function panelContext(context) {
    const result = {};
    for (const key of ["project_uid", "app_key", "app_version", "language"]) {
        if (typeof context?.[key] !== "string" || !context[key] || context[key].length > 1024) {
            throw new TypeError(`Invalid panel context: ${key}`);
        }
        result[key] = context[key];
    }
    return result;
}

// Matches the existing Langboard main.css semantic variables. No arbitrary CSS authority.
export const PANEL_DESIGN_TOKENS = Object.freeze([
    "--background", "--foreground", "--card", "--card-foreground", "--popover", "--popover-foreground",
    "--primary", "--primary-foreground", "--secondary", "--secondary-foreground", "--muted", "--muted-foreground",
    "--accent", "--accent-foreground", "--destructive", "--destructive-foreground", "--warning", "--warning-foreground",
    "--warning-border", "--border", "--input", "--ring", "--radius", "--chart-1", "--chart-2", "--chart-3",
    "--chart-4", "--chart-5", "--brand", "--highlight",
]);

function panelDesign(input, expectedOrigin, allowResources = true) {
    const design = snapshot(input).value;
    if (design.mode !== "light" && design.mode !== "dark") throw new TypeError("Invalid panel design mode");
    if (Object.keys(design).some((key) => !["mode", "tokens", "resources"].includes(key))) throw new TypeError("Invalid design field");
    const tokens = snapshot(design.tokens).value;
    for (const [key, value] of Object.entries(tokens)) {
        if (!PANEL_DESIGN_TOKENS.includes(key) || typeof value !== "string" || value.length > 64) {
            throw new TypeError("Invalid panel design token");
        }
        if (key === "--radius") {
            if (!/^(?:\d+(?:\.\d+)?|\.\d+)(?:px|rem)$/.test(value) || parseFloat(value) > 64) {
                throw new TypeError("Invalid panel radius");
            }
        } else {
            const match = /^(\d+(?:\.\d+)?) (\d+(?:\.\d+)?)% (\d+(?:\.\d+)?)%$/.exec(value);
            if (!match || +match[1] > 360 || +match[2] > 100 || +match[3] > 100) {
                throw new TypeError("Invalid panel color channels");
            }
        }
    }
    const result = { mode: design.mode, tokens };
    if (design.resources !== undefined) {
        if (!allowResources) throw new TypeError("Design updates cannot change resources");
        const resources = snapshot(design.resources).value;
        if (Object.keys(resources).length !== 2) throw new TypeError("Invalid design resources");
        result.resources = {};
        for (const key of ["module_url", "css_url"]) {
            if (typeof resources[key] !== "string" || resources[key].length > 2048) throw new TypeError("Invalid design resource URL");
            const url = new URL(resources[key]);
            const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
            if (url.username || url.password || url.hash || (url.protocol !== "https:" && !(url.protocol === "http:" && local)) ||
                (expectedOrigin && url.origin !== expectedOrigin)) throw new TypeError("Untrusted design resource URL");
            result.resources[key] = url.href;
        }
    }
    return result;
}

function applyPanelDesign(root, design, previousTokens = {}) {
    if (!root) return;
    for (const key of Object.keys(previousTokens)) {
        if (!(key in design.tokens)) root.style.removeProperty(key);
    }
    for (const [key, value] of Object.entries(design.tokens)) root.style.setProperty(key, value);
    root.classList.toggle("dark", design.mode === "dark");
    root.style.colorScheme = design.mode;
}

function loadPanelWidgets(document, resources, signal) {
    if (!resources) return Promise.resolve(null);
    if (!document?.head) return Promise.reject(new Error("Panel design resources require a document"));
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.crossOrigin = "anonymous";
    link.referrerPolicy = "no-referrer";
    link.href = resources.css_url;
    const loaded = new Promise((resolve, reject) => {
        const settle = (error) => {
            link.onload = null;
            link.onerror = null;
            signal.removeEventListener("abort", abort);
            if (error) reject(error); else resolve();
        };
        const abort = () => settle(new Error("Panel design loading disposed"));
        link.onload = () => settle();
        link.onerror = () => settle(new Error("Panel design stylesheet failed to load"));
        signal.addEventListener("abort", abort, { once: true });
        document.head.appendChild(link);
    });
    signal.addEventListener("abort", () => link.remove(), { once: true });
    return loaded.then(async () => {
        if (signal.aborted) throw new Error("Panel design loading disposed");
        // URLs were validated against the actual parent origin before this import.
        const widgets = await import(resources.module_url);
        if (signal.aborted) throw new Error("Panel design loading disposed");
        return widgets;
    });
}

/** Session memory only. Keys must encode user, board, app and app version. */
export class PanelStateCache {
    #entries = new Map();
    #bytes = 0;
    get(key) {
        const entry = this.#entries.get(key);
        if (!entry) return null;
        this.#entries.delete(key);
        this.#entries.set(key, entry);
        return JSON.parse(entry.json);
    }
    set(key, state) {
        if (typeof key !== "string" || !key || encoder.encode(key).byteLength > 1024) {
            throw new TypeError("Panel cache key must be a bounded identity string");
        }
        const entry = snapshot(state);
        this.delete(key);
        this.#entries.set(key, { json: entry.json, bytes: entry.bytes });
        this.#bytes += entry.bytes;
        while (this.#entries.size > MAX_CACHE_ENTRIES || this.#bytes > MAX_CACHE_BYTES) {
            this.delete(this.#entries.keys().next().value);
        }
    }
    delete(key) {
        const entry = this.#entries.get(key);
        if (!entry) return false;
        this.#bytes -= entry.bytes;
        return this.#entries.delete(key);
    }
    clear() {
        this.#entries.clear();
        this.#bytes = 0;
    }
}

/** Call after the newly authorized iframe has loaded. */
export function createPanelHost({ frame, context, state = null, design, onState, onReady, onClose, onError }) {
    const init = { type: "langboard.panel.init", version: 1, context: panelContext(context),
        state: state === null ? null : snapshot(state).value };
    if (design !== undefined) init.design = panelDesign(design);
    if (!frame?.contentWindow) throw new TypeError("Panel frame must have a contentWindow");
    frame.setAttribute("sandbox", "allow-scripts allow-forms");
    frame.referrerPolicy = "no-referrer";
    const { port1, port2 } = new MessageChannel();
    let disposed = false;
    let ready = false;
    let writes = [];
    let timer;
    const dispose = () => {
        if (disposed) return;
        disposed = true;
        clearTimeout(timer);
        port1.onmessage = null;
        try { port1.postMessage({ type: "dispose", version: 1 }); } catch { /* Best effort only. */ }
        port1.close();
        port2.close();
        frame.remove();
    };
    dispose.updateDesign = (next) => {
        if (disposed) return;
        const clean = panelDesign(next, undefined, false);
        init.design = { ...clean, ...(init.design?.resources ? { resources: init.design.resources } : {}) };
        port1.postMessage({ type: "design", version: 1, design: clean });
    };
    const fail = (error) => { dispose(); onError?.(error); };
    port1.onmessage = ({ data }) => {
        if (disposed || data?.version !== 1) return;
        if (data.type === "ready" && !ready) {
            ready = true;
            clearTimeout(timer);
            onReady?.();
        } else if (data.type === "close") {
            dispose();
            onClose?.();
        } else if (data.type === "state" && ready) {
            const now = performance.now();
            writes = writes.filter((time) => now - time < 1000);
            if (writes.length >= 8) return;
            writes.push(now);
            let next;
            try { next = snapshot(data.state).value; } catch { return; }
            onState?.(next);
        }
    };
    port1.start();
    timer = setTimeout(() => fail(new Error("Panel ready timeout")), READY_TIMEOUT_MS);
    try { frame.contentWindow.postMessage(init, "*", [port2]); }
    catch (error) { fail(error); }
    return dispose;
}

export function connectPanel({ expectedHostOrigin, onShow, onDispose }) {
    let origin;
    try { origin = new URL(expectedHostOrigin).origin; } catch { /* Reject below. */ }
    if (!origin || origin === "null" || origin !== expectedHostOrigin || !/^https?:/.test(origin)) {
        return Promise.reject(new TypeError("expectedHostOrigin must be an exact HTTP(S) origin"));
    }
    const target = globalThis.window;
    if (!target?.parent || target.parent === target) return Promise.reject(new Error("Panel requires a parent window"));
    return new Promise((resolve, reject) => {
        const bootstrap = (event) => {
            if (event.source !== target.parent || event.origin !== expectedHostOrigin ||
                event.data?.type !== "langboard.panel.init" || event.data.version !== 1 || event.ports?.length !== 1) return;
            const port = event.ports[0];
            let context, state, design;
            try {
                context = panelContext(event.data.context);
                design = event.data.design === undefined ? null : panelDesign(event.data.design, expectedHostOrigin);
                state = event.data.state === null ? null : snapshot(event.data.state).value;
            } catch { port.close(); return; }
            target.removeEventListener("message", bootstrap);
            clearTimeout(timer);
            const controller = new AbortController();
            const root = target.document?.documentElement;
            const originalTokens = new Map();
            const originalDark = root?.classList.contains("dark");
            const originalColorScheme = root?.style.colorScheme;
            const rememberTokens = (tokens) => {
                if (!root) return;
                for (const key of Object.keys(tokens)) {
                    if (!originalTokens.has(key)) originalTokens.set(key, [root.style.getPropertyValue(key), root.style.getPropertyPriority(key)]);
                }
            };
            if (design) { rememberTokens(design.tokens); applyPanelDesign(root, design); }
            const widgets = loadPanelWidgets(target.document, design?.resources, controller.signal);
            // The promise stays observable by callers without an unhandled rejection for unused widgets.
            void widgets.catch(() => {});
            let disposed = false;
            let pending = null;
            let writeTimer;
            let lastWrite = -Infinity;
            const sendPending = () => {
                writeTimer = undefined;
                if (disposed || pending === null) return;
                const remaining = 150 - (performance.now() - lastWrite);
                if (remaining > 0) {
                    writeTimer = setTimeout(sendPending, Math.ceil(remaining));
                    return;
                }
                const next = pending;
                pending = null;
                lastWrite = performance.now();
                port.postMessage({ type: "state", version: 1, state: JSON.parse(next) });
            };
            const dispose = () => {
                if (disposed) return;
                disposed = true;
                clearTimeout(writeTimer);
                pending = null;
                controller.abort();
                if (root && design) {
                    for (const [key, [value, priority]] of originalTokens) {
                        if (value) root.style.setProperty(key, value, priority); else root.style.removeProperty(key);
                    }
                    root.classList.toggle("dark", originalDark);
                    root.style.colorScheme = originalColorScheme;
                }
                port.onmessage = null;
                port.close();
                target.removeEventListener("pagehide", dispose);
                onDispose?.();
            };
            const session = {
                context, state, design, widgets, signal: controller.signal,
                saveState(next) {
                    if (disposed) throw new Error("Panel session is disposed");
                    const clean = snapshot(next);
                    session.state = clean.value;
                    pending = clean.json;
                    if (writeTimer !== undefined) return;
                    const remaining = 150 - (performance.now() - lastWrite);
                    if (remaining <= 0) sendPending();
                    else writeTimer = setTimeout(sendPending, Math.ceil(remaining));
                },
                close() {
                    if (disposed) return;
                    try { port.postMessage({ type: "close", version: 1 }); } finally { dispose(); }
                },
                dispose,
            };
            port.onmessage = ({ data }) => {
                if (disposed || data?.version !== 1) return;
                if (data.type === "dispose") dispose();
                else if (data.type === "design") {
                    let next;
                    try { next = panelDesign(data.design, expectedHostOrigin, false); } catch { return; }
                    rememberTokens(next.tokens);
                    applyPanelDesign(root, next, design?.tokens);
                    design = { ...next, ...(design?.resources ? { resources: design.resources } : {}) };
                    session.design = design;
                }
            };
            port.start();
            target.addEventListener("pagehide", dispose, { once: true });
            try {
                port.postMessage({ type: "ready", version: 1 });
                onShow?.(session);
                resolve(session);
            } catch (error) { dispose(); reject(error); }
        };
        const timer = setTimeout(() => {
            target.removeEventListener("message", bootstrap);
            reject(new Error("Panel init timeout"));
        }, READY_TIMEOUT_MS);
        target.addEventListener("message", bootstrap);
    });
}
