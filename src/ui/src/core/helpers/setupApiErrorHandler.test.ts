import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";
import { AxiosError } from "axios";
import i18next from "i18next";
import ts from "typescript";

for (const locale of ["en-US", "ko-KR", "ja-JP", "zh-CN"]) {
    test(`archive delete denial and unknown error codes have readable messages in ${locale}`, async () => {
        const errors = JSON.parse(readFileSync(new URL(`../../assets/locales/${locale}/errors.json`, import.meta.url), "utf8"));
        const i18n = i18next.createInstance();
        await i18n.init({ lng: locale, resources: { [locale]: { translation: { errors } } } });
        const require = createRequire(import.meta.url);
        const module = { exports: {} as { default: (map: object, ref: { message: string }) => { handle: (error: AxiosError) => unknown } } };
        const source = readFileSync(new URL("./setupApiErrorHandler.ts", import.meta.url), "utf8");
        const javascript = ts.transpileModule(source, {
            compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
        }).outputText;
        runInNewContext(javascript, {
            module,
            exports: module.exports,
            require: (name: string) => {
                if (name === "i18next") return { t: i18n.t.bind(i18n) };
                if (name === "@/components/base/Toast") return { Add: { error: () => undefined } };
                if (name === "@langboard/core/utils") return { Utils: { Type: { isString: (value: unknown) => typeof value === "string" } } };
                if (name === "@langboard/core/enums") return { EHttpStatus: { HTTP_403_FORBIDDEN: 403 } };
                return require(name);
            },
            console,
        });
        for (const [code, expected] of [
            ["PE2006", errors.requests.PE2006],
            ["UNRECOGNIZED_CODE", errors["Internal server error"]],
        ]) {
            const error = new AxiosError();
            error.response = { status: 403, data: { code } } as AxiosError["response"];
            const ref = { message: "" };
            module.exports.default({}, ref).handle(error);
            assert.ok(expected);
            assert.equal(ref.message, expected);
            assert.ok(!ref.message.includes("errors.requests."));
        }
    });
}
