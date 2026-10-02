import { URL } from "node:url";
import process from "node:process";
import console from "node:console";
import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { SUPPORTED_LOCALES, DEFAULT_LOCALE } from "../src/core/utils/LocalePolicy.ts";

const root = new URL("../src/assets/locales/", import.meta.url);
const canonicalFiles = (await readdir(new URL(`${DEFAULT_LOCALE}/`, root))).filter((file) => file.endsWith(".json")).sort();
const flatten = (object, prefix = "") =>
    Object.fromEntries(
        Object.entries(object).flatMap(([key, value]) => {
            const path = prefix ? `${prefix}.${key}` : key;
            return typeof value === "string" ? [[path, value]] : Object.entries(flatten(value, path));
        })
    );
const tokens = (value) => [...value.matchAll(/\{\{[^}]+\}\}|<\/?[A-Za-z0-9][^>]*>/g)].map(([token]) => token).sort();
const read = async (locale, file) => JSON.parse(await readFile(new URL(`${locale}/${file}`, root), "utf8"));
const structure = (value) => {
    if (typeof value === "string") return "string";
    if (Array.isArray(value)) return value.map(structure);
    assert(value && typeof value === "object", "resource values must be strings, arrays or objects");
    return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, structure(child)]));
};
const report = {};
for (const locale of SUPPORTED_LOCALES.filter((locale) => locale !== DEFAULT_LOCALE)) {
    const files = (await readdir(new URL(`${locale}/`, root))).filter((file) => file.endsWith(".json")).sort();
    assert(files.length > 0, `${locale}: no translated resources`);
    let values = 0;
    for (const file of files) {
        assert(canonicalFiles.includes(file), `${locale}/${file}: unknown namespace`);
        const sourceTree = await read(DEFAULT_LOCALE, file);
        const translatedTree = await read(locale, file);
        assert.deepEqual(structure(translatedTree), structure(sourceTree), `${locale}/${file}: structure mismatch`);
        const source = flatten(sourceTree);
        const translated = flatten(translatedTree);
        assert.deepEqual(Object.keys(translated).sort(), Object.keys(source).sort(), `${locale}/${file}: key mismatch`);
        for (const [key, value] of Object.entries(translated)) {
            assert(value.trim(), `${locale}/${file}/${key}: empty value`);
            assert.deepEqual(tokens(value), tokens(source[key]), `${locale}/${file}/${key}: placeholder mismatch`);
            for (const token of ["MCP", "API", "JSON", "Copilot"]) {
                if (source[key].includes(token)) assert(value.includes(token), `${locale}/${file}/${key}: missing ${token}`);
            }
            values++;
        }
    }
    const missing = canonicalFiles.filter((file) => !files.includes(file));
    report[locale] = { namespaces: files.length, values, missing };
    if (process.argv.includes("--complete")) assert.equal(missing.length, 0, `${locale}: ${missing.length} untranslated namespaces`);
}
console.log(JSON.stringify({ canonicalNamespaces: canonicalFiles.length, locales: report }, null, 2));
