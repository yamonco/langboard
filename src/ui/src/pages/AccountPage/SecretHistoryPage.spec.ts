import { test, expect } from "@playwright/test";
for (const width of [1440, 390]) {
    test(`history pagination clears prior rows after denial at ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        let calls = 0;
        await page.route("**/secret-references/fixture/history*", async (route) => {
            calls++;
            const cursor = new URL(route.request().url()).searchParams.get("cursor");
            if (calls === 3) return route.fulfill({ status: 404, json: {} });
            expect(cursor).toBe(calls === 1 ? null : "next-1");
            await route.fulfill({
                json: {
                    items: [
                        {
                            uid: `event-${calls}`,
                            action: calls === 1 ? "rotated" : "created",
                            created_at: "2026-10-08T00:00:00Z",
                            actor_uid: "actor-fixture",
                            source_kind: "api",
                            reason_code: "user_input",
                            request_id: "server-request-fixture",
                            revision_before: calls === 1 ? 0 : null,
                            revision_after: calls === 1 ? 1 : 0,
                        },
                    ],
                    next_cursor: `next-${calls}`,
                },
            });
        });
        await page.goto("/src/pages/AccountPage/secret-history.fixture.html");
        await expect(page.locator("li")).toHaveCount(1);
        await expect(page.getByText("Value replaced", { exact: true })).toBeVisible();
        await expect(page.getByText("Explicit browser input", { exact: true })).toHaveAttribute("title", "server-request-fixture");
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `test-results/secret-history-${width}.png` });
        await page.getByRole("button", { name: "Older events" }).click();
        await expect(page.locator("li")).toHaveCount(2);
        await page.getByRole("button", { name: "Older events" }).click();
        await expect(page.getByRole("alert")).toBeVisible();
        await expect(page.locator("li")).toHaveCount(0);
        expect(calls).toBe(3);
    });
}

for (const width of [1440, 390])
    for (const late of ["denial", "same-reference-return"])
        test(`late history pagination ignored after navigation ${late} at ${width}`, async ({ page }) => {
            await page.setViewportSize({ width, height: 900 });
            let oldPage: import("@playwright/test").Route | undefined;
            let initial = 0;
            await page.route("**/secret-references/*/history*", async (route) => {
                const url = new URL(route.request().url());
                if (url.searchParams.has("cursor")) {
                    oldPage = route;
                    return;
                }
                initial++;
                await route.fulfill({
                    json: {
                        items: [
                            {
                                uid: `event-${initial}`,
                                action: "created",
                                created_at: "2026-10-08T00:00:00Z",
                                actor_uid: `current-actor-${initial}`,
                                source_kind: "api",
                                revision_before: null,
                                revision_after: 0,
                            },
                        ],
                        next_cursor: "older",
                    },
                });
            });
            await page.goto("/src/pages/AccountPage/secret-history.fixture.html");
            await expect(page.getByText(/current-actor-1/)).toBeVisible();
            await page.getByRole("button", { name: "Older events" }).click();
            await expect.poll(() => Boolean(oldPage)).toBe(true);
            await page.getByRole("button", { name: "Other reference", exact: true }).click();
            await expect(page.getByText(/current-actor-2/)).toBeVisible();
            if (late === "same-reference-return") {
                await page.getByRole("button", { name: "Fixture reference", exact: true }).click();
                await expect(page.getByText(/current-actor-3/)).toBeVisible();
            }
            const response = page.waitForResponse((response) => new URL(response.url()).searchParams.has("cursor"));
            await oldPage!.fulfill(
                late === "denial"
                    ? { status: 404, json: {} }
                    : {
                          json: {
                              items: [
                                  {
                                      uid: "stale-event",
                                      action: "revoked",
                                      created_at: "2026-10-08T00:00:00Z",
                                      actor_uid: "stale-actor",
                                      source_kind: "api",
                                      revision_before: 0,
                                      revision_after: 1,
                                  },
                              ],
                              next_cursor: null,
                          },
                      }
            );
            await (await response).finished();
            await expect(page.getByText(new RegExp(`current-actor-${initial}`))).toBeVisible();
            await expect(page.getByRole("alert")).toHaveCount(0);
            await expect(page.locator("li")).toHaveCount(1);
            await expect(page.getByText(/stale-actor/)).toHaveCount(0);
            await expect(page.getByRole("button", { name: "Older events" })).toBeEnabled();
        });

for (const width of [1920, 390]) {
    test(`source links use authorized local card and wiki routes at ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await page.route("**/secret-references/fixture/history*", (route) =>
            route.fulfill({
                json: {
                    items: [
                        {
                            uid: "one",
                            created_at: "2026-10-09T00:00:00Z",
                            actor_uid: "actor",
                            action: "created",
                            source_kind: "card",
                            revision_before: null,
                            revision_after: 0,
                            source_link: { kind: "card", href: "/board/board/card" },
                        },
                        {
                            uid: "two",
                            created_at: "2026-10-09T00:00:00Z",
                            actor_uid: "actor",
                            action: "created",
                            source_kind: "card",
                            revision_before: null,
                            revision_after: 0,
                            source_link: { kind: "card", href: "https://untrusted.invalid" },
                        },
                        {
                            uid: "three",
                            created_at: "2026-10-09T00:00:00Z",
                            actor_uid: "actor",
                            action: "created",
                            source_kind: "card",
                            revision_before: null,
                            revision_after: 0,
                        },
                        {
                            uid: "four",
                            created_at: "2026-10-09T00:00:00Z",
                            actor_uid: "actor",
                            action: "created",
                            source_kind: "wiki",
                            revision_before: null,
                            revision_after: 0,
                            source_link: { kind: "wiki", href: "/board/board/wiki/wiki" },
                        },
                        {
                            uid: "five",
                            created_at: "2026-10-09T00:00:00Z",
                            actor_uid: "actor",
                            action: "created",
                            source_kind: "wiki",
                            revision_before: null,
                            revision_after: 0,
                            source_link: { kind: "wiki", href: "/board/board/card" },
                        },
                    ],
                    next_cursor: null,
                },
            })
        );
        await page.goto("/src/pages/AccountPage/secret-history.fixture.html");
        const links = page.getByRole("link", { name: "Open source card" });
        await expect(links).toHaveCount(1);
        await expect(links).toHaveAttribute("href", "/board/board/card");
        const wikiLinks = page.getByRole("link", { name: "Open source wiki" });
        await expect(wikiLinks).toHaveCount(1);
        await expect(wikiLinks).toHaveAttribute("href", "/board/board/wiki/wiki");
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
}

for (const locale of ["en-US", "ko-KR", "ja-JP", "zh-CN"]) {
    test(`history dates follow account language ${locale} instead of browser language`, async ({ browser }) => {
        const context = await browser.newContext({ locale: "en-US", timezoneId: "Asia/Seoul" });
        const page = await context.newPage();
        await page.addInitScript((value) => localStorage.setItem("lang", value), locale);
        await page.route("**/secret-references/fixture/history*", (route) =>
            route.fulfill({
                json: {
                    items: [
                        {
                            uid: "locale-event",
                            action: "created",
                            created_at: "2026-10-08T00:00:00Z",
                            actor_uid: "fixture",
                            source_kind: "api",
                            revision_before: null,
                            revision_after: 0,
                        },
                    ],
                    next_cursor: null,
                },
            })
        );
        await page.goto("/src/pages/AccountPage/secret-history.fixture.html");
        const expected = await page.evaluate(
            (language) => new Intl.DateTimeFormat(language, { dateStyle: "medium", timeStyle: "short" }).format(new Date("2026-10-08T00:00:00Z")),
            locale
        );
        await expect(page.locator("time")).toHaveText(expected);
        await expect(page.locator("time")).toHaveAttribute("datetime", "2026-10-08T00:00:00Z");
        await context.close();
    });
}

for (const width of [1440, 390]) {
    test(`canonical editor reference opens native history at ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await page.goto("/src/components/plate-ui/secret-reference-link.fixture.html");
        for (const name of ["Editable reference", "Static reference"]) {
            const region = page.getByRole("region", { name });
            await expect(region.getByRole("link", { name: "••••" })).toHaveAttribute("href", "/secret-references/fixture/history");
            await expect(region.getByText("Invalid", { exact: true })).not.toHaveAttribute("href", "/secret-references/fixture/history");
        }
        await page.getByRole("region", { name: "Editable reference" }).getByRole("link", { name: "••••" }).click();
        await expect(page).toHaveURL(/\/secret-references\/fixture\/history$/);
    });
}

for (const width of [1440, 390]) {
    test(`explicit copy submits metadata once and links independent history at ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        let posts = 0;
        await page.route("**/secret-references/fixture/history*", (route) =>
            route.fulfill({
                json: {
                    items: posts
                        ? [
                              {
                                  uid: "copy-event",
                                  action: "copied",
                                  created_at: "2026-10-10T00:00:00Z",
                                  actor_uid: "copy-actor",
                                  source_kind: "api",
                                  reason_code: "reference_copied",
                                  revision_before: 7,
                                  revision_after: 7,
                              },
                          ]
                        : [],
                    next_cursor: null,
                },
            })
        );
        await page.route("**/secret-references/fixture", (route) =>
            route.fulfill({ json: { reference: { name: "provider/key", state: "active", revision: 7 } } })
        );
        await page.route("**/secret-references/fixture/copy", async (route) => {
            posts++;
            expect(route.request().postDataJSON()).toEqual({ name: "provider/new-key", expected_revision: 7 });
            await route.fulfill({ status: 201, json: { reference: { uri: "secret://ref/copied", revision: 0 } } });
        });
        await page.goto("/src/pages/AccountPage/secret-history.fixture.html");
        await page.getByRole("button", { name: "Copy secret", exact: true }).click();
        const name = page.getByRole("textbox", { name: "New logical name" });
        await expect(name).toBeEnabled();
        await name.fill("provider/new-key");
        await page.getByRole("button", { name: "Create copy", exact: true }).click();
        await expect(page.getByRole("status")).toHaveText("Copy created. The original is unchanged.");
        await expect(page.getByRole("link", { name: "Open copied secret history" })).toHaveAttribute("href", "/secret-references/copied/history");
        await expect(page.getByText("Copied", { exact: true })).toBeVisible();
        expect(posts).toBe(1);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `test-results/secret-copy-${width}.png` });
    });
}

for (const failure of ["revoked", "conflict", "late-response"]) {
    test(`copy fences ${failure} and retains current reference UI`, async ({ page }) => {
        let held: import("@playwright/test").Route | undefined;
        let posts = 0;
        await page.route("**/secret-references/*/history*", (route) => route.fulfill({ json: { items: [], next_cursor: null } }));
        await page.route("**/secret-references/fixture", (route) =>
            route.fulfill({ json: { reference: { name: "provider/key", state: failure === "revoked" ? "revoked" : "active", revision: 2 } } })
        );
        await page.route("**/secret-references/fixture/copy", async (route) => {
            posts++;
            if (failure === "late-response") {
                held = route;
                return;
            }
            await route.fulfill({ status: 409, json: {} });
        });
        await page.goto("/src/pages/AccountPage/secret-history.fixture.html");
        await page.getByRole("button", { name: "Copy secret", exact: true }).click();
        if (failure === "revoked") {
            await expect(page.getByRole("alert")).toBeVisible();
            await expect(page.getByRole("button", { name: "Create copy", exact: true })).toBeDisabled();
            expect(posts).toBe(0);
            return;
        }
        const name = page.getByRole("textbox", { name: "New logical name" });
        await expect(name).toBeEnabled();
        await name.fill("provider/new-key");
        await page.getByRole("button", { name: "Create copy", exact: true }).click();
        if (failure === "conflict") {
            await expect(page.getByRole("alert")).toBeVisible();
            await expect(name).toHaveValue("provider/new-key");
            await expect(page.getByRole("link", { name: "Open copied secret history" })).toHaveCount(0);
        } else {
            await expect.poll(() => !!held).toBe(true);
            await expect(page.getByRole("button", { name: "Create copy", exact: true })).toBeDisabled();
            await page.getByRole("button", { name: "Other reference", exact: true }).click();
            const response = page.waitForResponse("**/secret-references/fixture/copy");
            await held!.fulfill({ status: 201, json: { reference: { uri: "secret://ref/copied" } } });
            await (await response).finished();
            await expect(page.getByRole("link", { name: "Open copied secret history" })).toHaveCount(0);
            await expect(page.getByRole("alert")).toHaveCount(0);
        }
        expect(posts).toBe(1);
    });
}

for (const width of [1440, 390]) {
    test(`canonical markdown stores masked void nodes and roundtrips without captions at ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await page.goto("/src/components/plate-ui/secret-masked-node.fixture.html");
        for (const name of ["Masked editable", "Masked static"]) {
            const section = page.getByRole("region", { name, exact: true });
            await expect(section.getByRole("link", { name: "Secret history", exact: true })).toHaveCount(2);
            await expect(section.getByRole("link", { name: "Secret history", exact: true }).first()).toHaveAttribute(
                "href",
                "/secret-references/fixture/history"
            );
            await expect(section).not.toContainText("legacy-caption");
            await expect(section).not.toContainText("another-caption");
            await expect(section.getByText("External", { exact: true })).toBeVisible();
            await expect(section.getByText("Invalid", { exact: true })).toBeVisible();
        }
        await expect(page.locator("[data-reference-value]")).not.toContainText("legacy-caption");
        await expect(page.locator("[data-reference-value]")).toContainText(String.raw`"type":"secretReference"`);
        await page.getByRole("button", { name: "Save reference draft" }).click();
        await expect(page.locator("[data-saved-reference]")).toContainText("secret://ref/fixture");
        await expect(page.locator("[data-saved-reference]")).not.toContainText("legacy-caption");
        await page.getByRole("button", { name: "Reload reference draft" }).click();
        await expect(page.getByRole("region", { name: "Masked editable" }).getByRole("link", { name: "Secret history" })).toHaveCount(2);
        await page.screenshot({ path: `test-results/secret-masked-node-${width}.png` });
        await page.getByRole("region", { name: "Masked editable" }).getByRole("link", { name: "Secret history" }).first().click();
        await expect(page).toHaveURL(/\/secret-references\/fixture\/history$/);
    });
}

for (const width of [1440, 390]) {
    test(`collaborative JSON normalizes reference links and strips node captions at ${width}`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await page.goto("/src/components/plate-ui/secret-masked-node.fixture.html");
        await page.getByRole("button", { name: "Load collaborative reference" }).click();
        const editor = page.getByRole("region", { name: "Masked editable" });
        await expect(editor.getByRole("link", { name: "Secret history" })).toHaveCount(2);
        await expect(editor).not.toContainText("json-caption");
        await expect(editor).not.toContainText("tainted-caption");
        await page.getByRole("button", { name: "Save reference draft" }).click();
        await expect(page.locator("[data-saved-reference]")).not.toContainText("json-caption");
        await expect(page.locator("[data-saved-reference]")).not.toContainText("tainted-caption");
        await expect(page.locator("[data-reference-value]")).not.toContainText("json-caption");
        await expect(page.locator("[data-reference-value]")).not.toContainText("tainted-caption");
        await page.getByRole("button", { name: "Reload reference draft" }).click();
        await expect(editor.getByRole("link", { name: "Secret history" })).toHaveCount(2);
    });
}

test("native Yjs peers normalize initial links and persist caption-free remote updates", async ({ page }) => {
    await page.goto("/src/components/plate-ui/secret-masked-node.fixture.html");
    await page.getByRole("button", { name: "Verify Yjs peers" }).click();
    const result = page.locator("[data-sync-result]");
    await expect(result).toContainText("updated ");
    const state = JSON.parse(await result.innerText());
    expect(state.peers).toHaveLength(2);
    // Plate assigns editor-local node IDs; Yjs intentionally excludes those metadata props.
    const content = (value: unknown) => JSON.parse(JSON.stringify(value, (key, node) => (key === "id" ? undefined : node)));
    expect(content(state.peers[0])).toEqual(content(state.peers[1]));
    // Y.XmlText omits Slate's structural empty text siblings. Compare the reference subtree.
    expect(content(state.peers[0][0].children[1])).toEqual(state.shared[0][0].children[1]);
    for (const peer of state.initial) {
        expect(peer[0].children[1]).toMatchObject({
            type: "secretReference",
            uri: "secret://ref/fixture",
            children: [{ text: "" }],
        });
    }
    expect(state.peers[0][0].children[1]).toMatchObject({
        type: "secretReference",
        uri: "secret://ref/other",
        children: [{ text: "" }],
    });
    expect(state.shared[0]).toEqual(state.shared[1]);
    for (const caption of ["remote-caption", "remote-tainted"]) {
        await expect(result).not.toContainText(caption);
    }
});
