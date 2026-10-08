FROM node:22@sha256:0e5f906573693feaa1e21057ebdcfdb5bd5021f050b2dc7c9deceb629c7da2a8 AS build
WORKDIR /app

COPY shared/ts /shared/ts
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn cd /shared/ts && yarn install --frozen-lockfile --network-concurrency 4 --network-timeout 120000 && yarn build

COPY socket /app
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn yarn install --frozen-lockfile --network-concurrency 4 --network-timeout 120000 && yarn build
# Reinstall from empty dependency trees: Yarn file dependencies copy their source tree.
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn cd /shared/ts && rm -rf node_modules && yarn install --frozen-lockfile --production --network-concurrency 4 --network-timeout 120000
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn rm -rf node_modules && yarn install --frozen-lockfile --production --network-concurrency 4 --network-timeout 120000

FROM node:22@sha256:0e5f906573693feaa1e21057ebdcfdb5bd5021f050b2dc7c9deceb629c7da2a8
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack /opt/yarn-* \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack /usr/local/bin/yarn /usr/local/bin/yarnpkg /usr/local/bin/pnpm /usr/local/bin/pnpx
WORKDIR /app
RUN mkdir -p /app/local && chown -R node:node /app/local
ENV SOCKET_DATA_DIR=/app/local
COPY --from=build --chown=node:node /shared/ts /shared/ts
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/dist ./dist
COPY --from=build --chown=node:node /app/package.json ./package.json
USER 1000:1000
# Exercise native SQLite and both database drivers in the final filesystem.
RUN node --input-type=module <<'JS'
import assert from "node:assert/strict";
import { readFileSync, unlinkSync } from "node:fs";
import sqlite3 from "sqlite3";
import { DataSource } from "typeorm";
import pg from "pg";
assert.equal(typeof pg.Pool, "function");
const smokePath = `${process.env.SOCKET_DATA_DIR}/.build-smoke.sqlite`;
const database = new sqlite3.Database(smokePath);
try {
    const row = await new Promise((resolve, reject) => database.get("SELECT 1 AS ok", (error, row) => error ? reject(error) : resolve(row)));
    assert.equal(row.ok, 1);
} finally {
    await new Promise((resolve, reject) => database.close(error => error ? reject(error) : resolve()));
    unlinkSync(smokePath);
}
const sqlite = new DataSource({ type: "sqlite", database: ":memory:" });
await sqlite.initialize();
try {
    assert.equal((await sqlite.query("SELECT 1 AS ok"))[0].ok, 1);
} finally {
    await sqlite.destroy();
}
const postgres = new DataSource({ type: "postgres" });
assert.equal(postgres.driver.postgres, pg);
await import("terminal-kit"); // Logger uses createRequire for this external.
// Import actual static external modules retained by the Socket bundle, without starting it.
const bundle = readFileSync("dist/index.js", "utf8");
const imports = bundle.matchAll(/^import\s+(?:[^;]*?\s+from\s+)?["']([^"']+)["']/gm);
for (const specifier of new Set([...imports].map(match => match[1]))) {
    if (!specifier.startsWith(".") && !specifier.startsWith("/")) await import(specifier);
}
JS
EXPOSE 5690
CMD ["node", "dist/index.js"]
