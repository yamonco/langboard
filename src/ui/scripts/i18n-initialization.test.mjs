import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer } from "vite";

const caseValue = process.env.LANGBOARD_I18N_INIT_CASE;
if (caseValue) {
    const { cached, browser, expected } = JSON.parse(caseValue);
    const values = new Map(cached === null ? [] : [["lang", cached]]);
    const storage = {
        getItem: (key) => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, String(value)),
        removeItem: (key) => values.delete(key),
    };
    // Only browser platform inputs are substituted. The production module,
    // i18next, detector and lazy resource backend execute without mocks.
    globalThis.window = { localStorage: storage };
    globalThis.document = { documentElement: { lang: "" } };
    Object.defineProperty(globalThis, "navigator", { value: { languages: [browser], language: browser }, configurable: true });
    const server = await createServer({
        configFile: false,
        root: fileURLToPath(new URL("..", import.meta.url)),
        cacheDir: join(tmpdir(), `langboard-i18n-init-${process.pid}`),
        resolve: { alias: { "@": fileURLToPath(new URL("../src", import.meta.url)) } },
        optimizeDeps: { noDiscovery: true, include: [] },
        server: { middlewareMode: true, watch: null },
        appType: "custom",
    });
    try {
        const { default: i18n } = await server.ssrLoadModule("/src/i18n.ts");
        if (!i18n.isInitialized) await new Promise((resolve) => i18n.on("initialized", resolve));
        assert.equal(i18n.language, expected);
        assert.equal(document.documentElement.lang, expected);
        assert.equal(storage.getItem("lang"), expected);
        assert.deepEqual(i18n.options.fallbackLng, ["en-US"]);
        assert.deepEqual(
            i18n.options.supportedLngs.filter((locale) => locale !== "cimode"),
            ["en-US", "ko-KR", "ja-JP", "zh-CN"]
        );
        assert.equal(i18n.options.load, "currentOnly");
        assert.equal(i18n.options.preload, false);
        assert.equal(i18n.t("common.Close"), { "en-US": "Close", "ko-KR": "닫기", "ja-JP": "閉じる", "zh-CN": "关闭" }[expected]);
        await i18n.changeLanguage("ja-JP");
        assert.equal(document.documentElement.lang, "ja-JP");
        assert.equal(storage.getItem("lang"), "ja-JP");
        assert.equal(i18n.t("common.Close"), "閉じる");
    } finally {
        await server.close();
    }
} else {
    for (const [cached, browser, expected] of [
        [null, "en-US", "en-US"],
        [null, "ko", "ko-KR"],
        [null, "ja_JP", "ja-JP"],
        [null, "zh-Hans", "zh-CN"],
        ["ja", "ko-KR", "ja-JP"],
        ["../bad", "ko-KR", "en-US"],
        [null, "zh-Hant", "en-US"],
    ]) {
        test(`production initialization: cache ${cached}, browser ${browser} → ${expected}`, () => {
            const result = spawnSync(process.execPath, [fileURLToPath(import.meta.url)], {
                env: { ...process.env, LANGBOARD_I18N_INIT_CASE: JSON.stringify({ cached, browser, expected }) },
                encoding: "utf8",
                timeout: 20000,
            });
            assert.equal(result.status, 0, result.error?.message ?? result.stderr);
        });
    }
}
