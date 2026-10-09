import { test } from "node:test";
import assert from "node:assert/strict";
import { setTimeout as delay } from "node:timers/promises";
import { createPanelHost, connectPanel, PanelStateCache } from "./index.mjs";

const context = { project_uid: "board", app_key: "app", app_version: "1", language: "en" };
const flush = () => delay(20);
function host(options = {}) {
    let client;
    const frame = {
        contentWindow: { postMessage(data, origin, ports) {
            assert.equal(origin, "*");
            const transferred = structuredClone({ data, port: ports[0] }, { transfer: ports });
            client = transferred.port;
            options.init?.(transferred.data);
        } },
        setAttribute(name, value) { this[name] = value; },
        remove() { this.removed = true; },
    };
    const dispose = createPanelHost({ frame, context, ...options });
    return { frame, client, dispose };
}

test("host sanitizes init, accepts only ready/state/close and disposes independently", async () => {
    const states = [];
    let ready = 0, closed = 0;
    const fixture = host({ context: { ...context, bearer: "excluded" }, state: { draft: "a" },
        init(data) { assert.deepEqual(data.context, context); assert.deepEqual(data.state, { draft: "a" }); },
        onReady() { ready++; }, onState(state) { states.push(state); }, onClose() { closed++; } });
    assert.equal(fixture.frame.sandbox, "allow-scripts allow-forms");
    assert.equal(fixture.frame.referrerPolicy, "no-referrer");
    fixture.client.postMessage({ type: "state", version: 1, state: { ignored: true } });
    fixture.client.postMessage({ type: "ready", version: 1 });
    fixture.client.postMessage({ type: "ready", version: 1 });
    fixture.client.postMessage({ type: "business.write", version: 1 });
    fixture.client.postMessage({ type: "state", version: 2, state: { ignored: true } });
    fixture.client.postMessage({ type: "state", version: 1, state: { draft: "b" } });
    await flush();
    assert.equal(ready, 1);
    assert.deepEqual(states, [{ draft: "b" }]);
    fixture.client.postMessage({ type: "close", version: 1 });
    await flush();
    assert.equal(closed, 1);
    assert.equal(fixture.frame.removed, true);
    fixture.dispose();
    fixture.client.close();
});

test("state UTF-8 byte limit, unsafe values and rolling rate limit", async () => {
    const states = [];
    const fixture = host({ onState(state) { states.push(state); } });
    fixture.client.postMessage({ type: "ready", version: 1 });
    for (const state of [null, [], { text: "😀".repeat(4096) }, JSON.parse('{"__proto__": {"admin": true}}')]) {
        fixture.client.postMessage({ type: "state", version: 1, state });
    }
    for (let index = 0; index < 12; index++) fixture.client.postMessage({ type: "state", version: 1, state: { index } });
    await flush();
    assert.equal(states.length, 4); // Four invalid attempts consume half the validation budget.
    await delay(1010);
    fixture.client.postMessage({ type: "state", version: 1, state: { text: "a".repeat(16373) } });
    await flush();
    assert.equal(states.length, 5); // {"text":"..."} adds 11 bytes, exactly 16 KiB.
    fixture.dispose();
    fixture.client.close();
    const cache = new PanelStateCache();
    for (const invalid of [{ f() {} }, { n: NaN }, { value: new Date() }, Object.create({ grant: true }), { items: new Array(1000000) }]) {
        assert.throws(() => cache.set("key", invalid));
    }
    const accessor = Object.defineProperty({}, "secret", { enumerable: true, get() { throw Error("getter ran"); } });
    assert.throws(() => cache.set("key", accessor), /unsupported property/);
});

test("global cache eviction is independent of identity, respects byte bound and clones", () => {
    const cache = new PanelStateCache();
    const key = (user, board) => JSON.stringify([user, board, "app", "1"]);
    for (let index = 0; index < 32; index++) cache.set(key(`user${index}`, `board${index}`), { index });
    cache.get(key("user0", "board0"));
    cache.set(key("new-user", "new-board"), { draft: "new" });
    assert.equal(cache.get(key("user1", "board1")), null);
    assert.deepEqual(cache.get(key("user0", "board0")), { index: 0 });
    const input = { draft: { text: "saved" } };
    cache.set("clone", input);
    input.draft.text = "changed";
    const output = cache.get("clone");
    output.draft.text = "changed again";
    assert.equal(cache.get("clone").draft.text, "saved");
    cache.clear();
    for (let index = 0; index < 17; index++) cache.set(key(`user${index}`, "large-board"), { text: "a".repeat(16373) });
    assert.equal(cache.get(key("user0", "large-board")), null);
    assert.notEqual(cache.get(key("user1", "large-board")), null);
    assert.equal(cache.delete(key("user1", "large-board")), true);
    cache.clear();
    assert.equal(cache.get(key("user16", "large-board")), null);
});

test("client rejects wrong source/origin, removes bootstrap, aborts and closes channel", async () => {
    const listeners = new Map();
    const parent = {};
    const target = { parent,
        addEventListener(type, listener) { listeners.set(type, listener); },
        removeEventListener(type, listener) { if (listeners.get(type) === listener) listeners.delete(type); } };
    globalThis.window = target;
    let disposed = 0;
    let shown = 0;
    const channel = new MessageChannel();
    const received = [];
    channel.port1.onmessage = ({ data }) => received.push(data);
    try {
        await assert.rejects(connectPanel({ expectedHostOrigin: "*" }), /exact/);
        const connected = connectPanel({ expectedHostOrigin: "https://host.example", onShow() { shown++; }, onDispose() { disposed++; } });
        const bootstrap = listeners.get("message");
        const event = { source: parent, origin: "https://host.example", data: { type: "langboard.panel.init", version: 1, context, state: null }, ports: [channel.port2] };
        bootstrap({ ...event, source: {} });
        bootstrap({ ...event, origin: "https://evil.example" });
        await flush();
        assert.equal(received.length, 0);
        assert.equal(listeners.get("message"), bootstrap);
        bootstrap(event);
        const session = await connected;
        assert.equal(listeners.has("message"), false);
        assert.equal(shown, 1);
        for (const invalid of [null, [], { draft: () => {} }, JSON.parse('{"constructor": true}')]) {
            assert.throws(() => session.saveState(invalid));
        }
        session.saveState({ draft: "saved" });
        await flush();
        assert.deepEqual(received, [{ type: "ready", version: 1 }, { type: "state", version: 1, state: { draft: "saved" } }]);
        channel.port1.postMessage({ type: "dispose", version: 1 });
        await flush();
        assert.equal(session.signal.aborted, true);
        assert.equal(disposed, 1);
        assert.equal(listeners.has("pagehide"), false);
        session.dispose();
        assert.equal(disposed, 1);
        assert.throws(() => session.saveState({ draft: "late" }), /disposed/);
    } finally { channel.port1.close(); channel.port2.close(); delete globalThis.window; }
});

test("host timeout disposes without reload and clears timer", (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    let error;
    const fixture = host({ onError(value) { error = value; } });
    t.mock.timers.tick(10_000);
    assert.match(error.message, /ready timeout/);
    assert.equal(fixture.frame.removed, true);
    fixture.client.close();
});

test("rapid saves restore latest snapshot and disposal cancels pending sends", async () => {
    const listeners = new Map();
    const parent = {};
    globalThis.window = { parent,
        addEventListener(type, listener) { listeners.set(type, listener); },
        removeEventListener(type, listener) { if (listeners.get(type) === listener) listeners.delete(type); } };
    const cache = new PanelStateCache();
    const states = [];
    const connected = connectPanel({ expectedHostOrigin: "https://host.example" });
    const frame = {
        contentWindow: { postMessage(data, origin, ports) {
            const transferred = structuredClone({ data, port: ports[0] }, { transfer: ports });
            listeners.get("message")({ source: parent, origin: "https://host.example", data: transferred.data, ports: [transferred.port] });
        } },
        setAttribute() {}, remove() {},
    };
    const dispose = createPanelHost({ frame, context, onState(state) { states.push(state); cache.set("identity", state); } });
    try {
        const panel = await connected;
        for (let index = 0; index < 30; index++) panel.saveState({ draft: `edit-${index}` });
        assert.deepEqual(panel.state, { draft: "edit-29" });
        await delay(180);
        assert.deepEqual(states, [{ draft: "edit-0" }, { draft: "edit-29" }]);
        assert.deepEqual(cache.get("identity"), { draft: "edit-29" });
        // A new save remains queued until the next 150 ms slot. Local disposal cancels it.
        panel.saveState({ draft: "discard-on-disposal" });
        assert.deepEqual(panel.state, { draft: "discard-on-disposal" });
        panel.dispose();
        await delay(180);
        assert.equal(panel.signal.aborted, true);
        assert.equal(states.length, 2);
        assert.deepEqual(cache.get("identity"), { draft: "edit-29" });
    } finally { dispose(); delete globalThis.window; }
});

function designWindow() {
    const listeners = new Map();
    const values = new Map([["--background", ["original", "important"]]]);
    const classes = new Set();
    const links = [];
    const root = {
        style: {
            colorScheme: "normal",
            getPropertyValue(key) { return values.get(key)?.[0] ?? ""; },
            getPropertyPriority(key) { return values.get(key)?.[1] ?? ""; },
            setProperty(key, value, priority = "") { values.set(key, [value, priority]); },
            removeProperty(key) { values.delete(key); },
        },
        classList: { contains(key) { return classes.has(key); }, toggle(key, active) { if (active) classes.add(key); else classes.delete(key); } },
    };
    const target = { parent: {},
        addEventListener(type, listener) { listeners.set(type, listener); },
        removeEventListener(type, listener) { if (listeners.get(type) === listener) listeners.delete(type); },
        document: { documentElement: root, createElement() { return { remove() { this.removed = true; } }; }, head: { appendChild(link) { links.push(link); } } },
    };
    return { target, root, links, listeners, values };
}

test("design tokens apply automatically, update without reload and restore on disposal", async () => {
    const fixture = designWindow();
    globalThis.window = fixture.target;
    const connected = connectPanel({ expectedHostOrigin: "https://host.example" });
    let loads = 0;
    const frame = { contentWindow: { postMessage(data, origin, ports) {
        loads++;
        const transfer = structuredClone({ data, port: ports[0] }, { transfer: ports });
        fixture.listeners.get("message")({ source: fixture.target.parent, origin: "https://host.example", data: transfer.data, ports: [transfer.port] });
    } }, setAttribute() {}, remove() {} };
    const dispose = createPanelHost({ frame, context, design: { mode: "light", tokens: { "--background": "0 0% 100%", "--radius": "0.5rem" } } });
    try {
        const session = await connected;
        assert.equal(await session.widgets, null);
        assert.equal(fixture.values.get("--background")[0], "0 0% 100%");
        assert.equal(fixture.root.style.colorScheme, "light");
        dispose.updateDesign({ mode: "dark", tokens: { "--background": "224 71.4% 4.1%" } });
        await flush();
        assert.equal(loads, 1);
        assert.equal(session.design.mode, "dark");
        assert.equal(fixture.root.classList.contains("dark"), true);
        assert.equal(fixture.values.has("--radius"), false);
        assert.throws(() => dispose.updateDesign({ mode: "light", tokens: {}, resources: { module_url: "https://host.example/other.mjs", css_url: "https://host.example/other.css" } }), /resources/);
        assert.throws(() => dispose.updateDesign({ mode: "light", tokens: { "--background": "url(https://evil.example)" } }), /color/);
        assert.throws(() => dispose.updateDesign({ mode: "light", tokens: { "--unknown": "0 0% 0%" } }), /token/);
        dispose();
        await flush();
        assert.equal(session.signal.aborted, true);
        assert.deepEqual(fixture.values.get("--background"), ["original", "important"]);
        assert.equal(fixture.root.style.colorScheme, "normal");
        assert.equal(fixture.root.classList.contains("dark"), false);
    } finally { dispose(); delete globalThis.window; }
});

test("bootstrap resources reject foreign origins and unsafe protocols; owned CSS cleans up", async () => {
    const fixture = designWindow();
    globalThis.window = fixture.target;
    const connected = connectPanel({ expectedHostOrigin: "https://host.example" });
    const bootstrap = fixture.listeners.get("message");
    const makeEvent = (resources, origin = "https://host.example") => {
        const channel = new MessageChannel();
        return { channel, event: { source: fixture.target.parent, origin,
            data: { type: "langboard.panel.init", version: 1, context, state: null, design: { mode: "dark", tokens: { "--primary": "262.1 83.3% 57.8%" }, resources } }, ports: [channel.port2] } };
    };
    for (const module_url of ["https://evil.example/widgets.mjs", "javascript:alert(1)", "http://host.example/widgets.mjs", "https://user:pass@host.example/widgets.mjs", "https://host.example/widgets.mjs#fragment"]) {
        const { channel, event } = makeEvent({ module_url, css_url: "https://host.example/styles.css" });
        bootstrap(event);
        assert.equal(fixture.links.length, 0);
        channel.port1.close(); channel.port2.close();
    }
    const invalidSource = makeEvent({ module_url: "https://host.example/widgets.mjs", css_url: "https://host.example/styles.css" }, "https://evil.example");
    bootstrap(invalidSource.event);
    assert.equal(fixture.links.length, 0);
    invalidSource.channel.port1.close(); invalidSource.channel.port2.close();
    const { channel, event } = makeEvent({ module_url: "https://host.example/widgets.mjs", css_url: "https://host.example/styles.css" });
    try {
        bootstrap(event);
        const session = await connected;
        assert.equal(fixture.links.length, 1);
        assert.equal(fixture.links[0].href, "https://host.example/styles.css");
        assert.equal(fixture.links[0].crossOrigin, "anonymous");
        channel.port1.postMessage({ type: "design", version: 1, design: { mode: "light", tokens: {}, resources: { module_url: "https://evil.example/x", css_url: "https://evil.example/y" } } });
        await flush();
        assert.equal(session.design.mode, "dark");
        assert.equal(fixture.links.length, 1);
        session.dispose();
        await assert.rejects(session.widgets, /disposed/);
        assert.equal(fixture.links[0].removed, true);
        assert.equal(fixture.links[0].onload, null);
        assert.equal(fixture.links[0].onerror, null);
    } finally { channel.port1.close(); channel.port2.close(); delete globalThis.window; }
});
