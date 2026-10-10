import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const source = readFileSync(new URL('./useGetProjectDetails.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;

function load(dock) {
    const models = Object.fromEntries(['Project', 'ProjectCard', 'ProjectColumn', 'InternalBotModel', 'ChatTemplateModel'].map(name => [name, {
        Model: { fromOne: value => value, fromArray: value => value },
    }]));
    const dependencies = {
        '@langboard/core/constants': { Routing: { API: { BOARD: { DETAILS: '/board/{uid}/details' } } } },
        '@/core/helpers/Api': { api: { get: async () => ({ data: { project: {}, cards: [], columns: [], internal_bots: [], chat_templates: [] } }) } },
        '@/core/helpers/QueryMutation': { useQueryMutation: () => ({ query: (_, callback) => callback }) },
        '@/core/models': models,
        '@langboard/core/utils': { Utils: { String: { format: value => value } } },
        '@/controllers/api/board/refreshProjectColumnDock': { default: dock },
        '@/core/helpers/setupApiErrorHandler': { default: () => ({ handle: () => {} }) },
    };
    const exports = {};
    vm.runInNewContext(compiled, { exports, require: name => dependencies[name] });
    return exports.default({ uid: 'board', includeCards: false });
}

test('settings response completes while dock enrichment remains pending', async () => {
    const query = load(() => new Promise(() => {}));
    const result = await Promise.race([query(), new Promise((_, reject) => setTimeout(() => reject(new Error('Settings blocked on dock')), 100))]);
    assert.ok(result.project);
});

test('dock failure does not discard the authorized settings response', async () => {
    const result = await load(() => Promise.reject(new Error('Dock unavailable')))();
    assert.ok(result.project);
});
