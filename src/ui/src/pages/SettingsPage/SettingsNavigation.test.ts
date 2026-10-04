import assert from "node:assert/strict";
import { test } from "node:test";
import { settingsRedirect } from "./SettingsNavigation.ts";

test("permission revocation and unavailable settings select only a visible route", () => {
    const routes = { "/settings/workflow-stages": { hidden: true }, "/settings/api-keys": { hidden: false } };
    assert.equal(settingsRedirect(routes, "/settings/workflow-stages", "/dashboard"), "/settings/api-keys");
    assert.equal(settingsRedirect(routes, "/settings/api-keys", "/dashboard"), undefined);
    assert.equal(settingsRedirect(routes, "/settings/ollama", "/dashboard"), "/settings/api-keys");
    routes["/settings/api-keys"].hidden = true;
    assert.equal(settingsRedirect(routes, "/settings/api-keys", "/dashboard"), "/dashboard");
    assert.equal(settingsRedirect({}, "/settings/api-keys", "/dashboard"), "/dashboard");
});
