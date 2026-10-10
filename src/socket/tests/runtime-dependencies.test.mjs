import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { runInNewContext } from "node:vm";

const socket = new URL("../", import.meta.url);
const shared = new URL("../../shared/ts/", import.meta.url);
const dockerfile = readFileSync(new URL("Dockerfile", socket), "utf8");

// Match the production RUN commands so the fixture exercises the shipped order/flags.
const productionCommands = [...dockerfile.matchAll(/^RUN --mount=\S+ (.+yarn install [^\n]*--production[^\n]*)$/gm)]
    .map(match => match[1]);

test("final filesystem retains native smoke and nonroot storage, removes package tools", () => {
    const stages = dockerfile.split(/^FROM /m).slice(1);
    assert.equal(stages.length, 2);
    assert.equal(stages[0].split(" AS ")[0], stages[1].split("\n")[0]);
    const runtime = stages[1];
    for (const path of ["/usr/local/lib/node_modules/npm", "/usr/local/lib/node_modules/corepack", "/opt/yarn-*",
        "/usr/local/bin/npm", "/usr/local/bin/npx", "/usr/local/bin/corepack", "/usr/local/bin/yarn", "/usr/local/bin/yarnpkg"]) {
        assert.ok(runtime.includes(path), `missing package tool removal: ${path}`);
    }
    assert.ok(runtime.includes("ENV SOCKET_DATA_DIR=/app/local"));
    assert.ok(runtime.includes("chown -R node:node /app/local"));
    assert.ok(runtime.includes("USER 1000:1000"));
    assert.ok(runtime.includes('CMD ["node", "dist/index.js"]'));
    const smoke = runtime.match(/RUN node --input-type=module <<'JS'\n([\s\S]+?)\nJS/);
    assert.ok(smoke, "final-stage node smoke must run as nonroot");
    assert.ok(runtime.indexOf(smoke[0]) > runtime.indexOf("USER 1000:1000"));
    assert.match(smoke[1], /database\.get\("SELECT 1 AS ok"/);
    assert.match(smoke[1], /process\.env\.SOCKET_DATA_DIR/);
    assert.match(smoke[1], /unlinkSync\(smokePath\)/);
    assert.match(smoke[1], /sqlite\.initialize\(\)/);
    assert.match(smoke[1], /postgres\.driver\.postgres/);
    assert.match(smoke[1], /await import\(specifier\)/);
    const importPattern = runInNewContext(smoke[1].match(/const imports = bundle\.matchAll\((.+)\);/)[1]);
    const sample = `import { value } from "axios";\nimport "reflect-metadata";\n// import "comment-only";\nconst request = "import 'request-only'";\nconst text = "from 'string-only'";`;
    assert.deepEqual([...sample.matchAll(importPattern)].map(match => match[1]), ["axios", "reflect-metadata"]);
    const checked = spawnSync(process.execPath, ["--input-type=module", "--check"], { input: smoke[1], encoding: "utf8" });
    assert.equal(checked.status, 0, checked.stderr);
});

test("Yarn classic production reinstall excludes dev trees from copied file dependency", { timeout: 300_000 }, () => {
    const fixture = mkdtempSync(join(tmpdir(), "socket-runtime-dependencies-"));
    const sharedDir = join(fixture, "shared", "ts");
    const socketDir = join(fixture, "socket");
    try {
        for (const [source, target] of [[shared, sharedDir], [socket, socketDir]]) {
            mkdirSync(target, { recursive: true });
            for (const name of ["package.json", "yarn.lock"]) copyFileSync(new URL(name, source), join(target, name));
        }
        const version = spawnSync("yarn", ["--version"], { encoding: "utf8" });
        assert.equal(version.status, 0, version.stderr);
        assert.match(version.stdout, /^1\./, "fixture requires Yarn classic");
        const install = (directory, production = false) => {
            const args = ["install", "--frozen-lockfile", "--ignore-scripts", "--non-interactive", "--network-concurrency", "4", "--network-timeout", "120000"];
            if (production) args.push("--production");
            const result = spawnSync("yarn", args, { cwd: directory, encoding: "utf8", timeout: 120_000,
                env: { ...process.env, NODE_ENV: "development", NODE_AUTH_TOKEN: process.env.NODE_AUTH_TOKEN ?? "" }, maxBuffer: 4 * 1024 * 1024 });
            assert.equal(result.status, 0, result.error?.message ?? result.stdout + result.stderr);
        };
        // Package-only reproduction of both builder installs. Lifecycle scripts never run.
        install(sharedDir);
        install(socketDir);
        for (const directory of [sharedDir, socketDir, join(socketDir, "node_modules", "@langboard", "core")]) {
            assert.ok(existsSync(join(directory, "node_modules", "typescript")), `development fixture missing TypeScript: ${directory}`);
        }
        assert.equal(productionCommands.length, 2);
        assert.match(productionCommands[0], /^cd \/shared\/ts && rm -rf node_modules && yarn install/);
        assert.match(productionCommands[1], /^rm -rf node_modules && yarn install/);
        for (const directory of [sharedDir, socketDir]) {
            rmSync(join(directory, "node_modules"), { recursive: true, force: true });
            install(directory, true);
        }
        const copiedCore = join(socketDir, "node_modules", "@langboard", "core");
        for (const directory of [sharedDir, socketDir, copiedCore]) {
            for (const name of ["typescript", "eslint", "rollup", "pm2"]) {
                assert.equal(existsSync(join(directory, "node_modules", name)), false, `${directory} retained ${name}`);
            }
        }
        const requireSocket = createRequire(join(socketDir, "package.json"));
        for (const name of ["axios", "pg", "sqlite3", "typeorm", "reflect-metadata", "ws", "redis", "jsonwebtoken", "@hocuspocus/server"]) {
            assert.ok(requireSocket.resolve(name), `missing runtime dependency: ${name}`);
        }
        for (const directory of [sharedDir, copiedCore]) {
            assert.ok(createRequire(join(directory, "package.json")).resolve("axios"));
        }
        // sqlite3 is resolved, never loaded: --ignore-scripts deliberately omits native compilation.
        for (const name of ["pg", "typeorm", "ws", "redis", "jsonwebtoken"]) requireSocket(name);
    } finally {
        rmSync(fixture, { recursive: true, force: true });
    }
});
