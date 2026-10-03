import { test, expect, type Page, type Route } from "@playwright/test";

const FIXTURE = "/src/pages/BoardPage/components/board/CardViewerDeepLink.fixture.html";

test.beforeEach(async ({ page }) => {
    page.on("pageerror", (error) => console.error("Fixture page error:", error.message));
    page.on("requestfailed", (request) => console.error("Fixture request failure:", new URL(request.url()).pathname, request.failure()?.errorText));
});

const NOW_ISO = new Date().toISOString();

const FIXTURE_USER = {
    uid: "fixture-user",
    created_at: NOW_ISO,
    updated_at: NOW_ISO,
    type: "user",
    firstname: "Fixture",
    lastname: "User",
    email: "fixture@example.com",
    username: "fixture",
    api_key_role_actions: ["*"],
    setting_role_actions: ["*"],
    mcp_role_actions: ["*"],
    user_groups: [],
    subemails: [],
    preferred_lang: "en",
    notification_unsubs: {},
    industry: "",
    purpose: "",
};

const FIXTURE_CARD = {
    uid: "fixture-card",
    created_at: NOW_ISO,
    updated_at: NOW_ISO,
    project_uid: "fixture-project",
    project_column_uid: "fixture-column",
    project_column_name: "Fixture column",
    title: "Fixture card",
    description: [],
    order: 0,
    count_comment: 0,
    member_uids: [],
    current_auth_role_actions: ["*"],
    project_members: [],
    labels: [],
    relationships: [],
    has_description: false,
};

/** The API client sends credentialed cross-origin requests, so the mocked
 * responses must mirror the page origin exactly instead of using "*". */
function corsHeaders(route: Route): Record<string, string> {
    const origin = route.request().headers()["origin"] || "http://127.0.0.1:4175";
    return {
        "access-control-allow-origin": origin,
        "access-control-allow-credentials": "true",
        "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
        "access-control-allow-headers": "authorization,content-type,content-encoding",
    };
}

async function fulfillWithCors(route: Route, payload: unknown): Promise<void> {
    if (route.request().method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers: corsHeaders(route) });
        return;
    }
    await route.fulfill({ json: payload, headers: corsHeaders(route) });
}

interface IMockOptions {
    projectDelay?: number;
    cardDelay?: number;
}

async function mockBoardApi(page: Page, options: IMockOptions = {}): Promise<void> {
    const projectPayload = {
        project: {
            uid: "fixture-project",
            created_at: NOW_ISO,
            updated_at: NOW_ISO,
            owner_uid: FIXTURE_USER.uid,
            title: "Fixture project",
            project_type: "default",
            archive_visible_days: 30,
            all_members: [FIXTURE_USER],
            invited_member_uids: [],
            starred: false,
            internal_bots: [],
            internal_bot_settings: {},
            current_auth_role_actions: ["*"],
            labels: [],
            description: "",
            last_viewed_at: NOW_ISO,
            view_count: 0,
        },
        project_bot_scopes: [],
        project_bot_schedules: [],
    };

    const cardPayload = {
        card: FIXTURE_CARD,
        attachments: [],
        checklists: [],
        global_relationships: [],
        project_columns: [],
        project_labels: [],
        bot_scopes: [],
        execution_receipts: [],
    };

    // Catch-all first so the specific routes registered later take precedence.
    await page.route("**/board/fixture-project/**", (route) => fulfillWithCors(route, { comments: [], replies: [], total_count: 0 }));
    await page.route("**/board/fixture-project/card/*", async (route) => {
        if (options.cardDelay) {
            await new Promise((resolve) => setTimeout(resolve, options.cardDelay));
        }
        const uid = new URL(route.request().url()).pathname.split("/").at(-1)!;
        await fulfillWithCors(route, {
            ...cardPayload,
            card: { ...FIXTURE_CARD, uid, title: uid === "fixture-card" ? "Fixture card" : `Card ${uid}` },
        });
    });
    await page.route("**/board/fixture-project/cards/available", (route) => {
        const uids = route.request().method() === "OPTIONS" ? [] : route.request().postDataJSON().card_uids;
        return fulfillWithCors(route, { card_uids: uids });
    });
    await page.route("**/board/fixture-project/column/dock", (route) => fulfillWithCors(route, { column_uids: [] }));
    await page.route("**/board/fixture-project/columns", (route) => fulfillWithCors(route, { columns: [] }));
    await page.route("**/board/fixture-project", async (route) => {
        if (options.projectDelay) {
            await new Promise((resolve) => setTimeout(resolve, options.projectDelay));
        }
        await fulfillWithCors(route, projectPayload);
    });
    await page.route("**/activity/project/fixture-project/card/*/column-history", (route) => fulfillWithCors(route, { history: [], total_count: 0 }));
    await page.route("**/auth/**", (route) => fulfillWithCors(route, { access_token: "fixture-token", user: FIXTURE_USER, bots: [] }));
}

async function collectResults(page: Page): Promise<{ viewerMounted: number; openAnimationStarts: number; events: { type: string; t: number }[] }> {
    return page.evaluate(() => {
        const globals = window as unknown as Record<string, unknown>;
        return {
            viewerMounted: (globals.__viewerMounted as number) ?? 0,
            openAnimationStarts: (globals.__openAnimationStarts as number) ?? 0,
            events: (globals.__events as { type: string; t: number }[]) ?? [],
        };
    });
}

test("deep link with a restored session plays the open animation exactly once", async ({ page }) => {
    await mockBoardApi(page, { projectDelay: 150, cardDelay: 400 });

    await page.goto(`${FIXTURE}?authDelay=0&projectDelay=150`);

    const viewer = page.locator("[data-card-viewer]");
    await expect(viewer).toBeVisible();
    // Wait for the loaded card content and let any second play happen.
    await expect(page.getByText("Fixture card").first()).toBeVisible();
    await page.waitForTimeout(900);

    const results = await collectResults(page);
    expect(results.viewerMounted).toBe(1);
    expect(results.openAnimationStarts).toBe(1);
});

test("deep link stays animated once when the app-root Suspense swaps after mount", async ({ page }) => {
    await mockBoardApi(page, { projectDelay: 150, cardDelay: 400 });

    // A late lazy chunk suspends the app-root Suspense boundary 800ms after
    // the viewer mounted; React 18 hides the subtree and restarts CSS
    // animations when it is restored. Before the mount-once gate this
    // replayed the card open animation a second time.
    await page.goto(`${FIXTURE}?authDelay=0&projectDelay=150&lateSuspense=1&lateSuspenseAt=800`);

    const viewer = page.locator("[data-card-viewer]");
    await expect(viewer).toBeVisible();
    await expect(page.getByText("Fixture card").first()).toBeVisible();
    // Cover the late suspense suspension (800ms + 500ms chunk delay) and restore.
    await page.waitForTimeout(2200);

    const results = await collectResults(page);
    expect(results.openAnimationStarts).toBe(1);
});

test("deep link under StrictMode double mounts plays the open animation exactly once", async ({ page }) => {
    await mockBoardApi(page, { projectDelay: 150, cardDelay: 400 });

    await page.goto(`${FIXTURE}?authDelay=0&projectDelay=150&strictMode=1`);

    const viewer = page.locator("[data-card-viewer]");
    await expect(viewer).toBeVisible();
    await expect(page.getByText("Fixture card").first()).toBeVisible();
    await page.waitForTimeout(900);

    const results = await collectResults(page);
    expect(results.openAnimationStarts).toBe(1);
});

test("visual blank area dismisses the card while surface and floating actions stay open", async ({ page }) => {
    await mockBoardApi(page);
    await page.goto(FIXTURE);
    const viewer = page.locator("[data-card-viewer]");
    await expect(page.locator("[data-card-surface]")).toBeVisible();
    await page.locator("[data-card-surface]").click({ position: { x: 10, y: 10 } });
    await expect(viewer).toBeVisible();
    await page.getByRole("button", { name: "Actions", exact: true }).click();
    await expect(viewer).toBeVisible();
    const surface = await page.locator("[data-card-surface]").boundingBox();
    const nav = await page.locator("[data-floating-nav-content]").locator("button").first().boundingBox();
    expect(surface).not.toBeNull();
    expect(nav).not.toBeNull();
    await page.mouse.click(surface!.x + 8, (surface!.y + surface!.height + nav!.y) / 2);
    await expect(viewer).toHaveCount(0);
});

async function seedTray(page: Page, count: number) {
    await page.addInitScript((count) => {
        sessionStorage.setItem(
            "langboard-card-flip-session",
            JSON.stringify({
                state: {
                    trays: {
                        "fixture-user:fixture-project": Array.from({ length: count }, (_, index) => ({
                            uid: `other-${index}`,
                            title: `Card other-${index}`,
                        })),
                        "fixture-user:another-project": [{ uid: "foreign", title: "Foreign card" }],
                    },
                },
                version: 0,
            })
        );
    }, count);
}

test("Flip preserves a card, restores it and swaps a second card without mounting two viewers", async ({ page }) => {
    await mockBoardApi(page);
    await seedTray(page, 1);
    await page.goto(FIXTURE);
    await expect(page.getByRole("button", { name: "Flip card", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Flip card", exact: true }).click();
    await expect(page.locator("[data-card-viewer]")).toHaveCount(0);
    const saved = await page.evaluate(() => JSON.parse(sessionStorage.getItem("langboard-card-flip-session")!).state.trays);
    expect(saved["fixture-user:fixture-project"].map((card: { uid: string }) => card.uid)).toEqual(["fixture-card", "other-0"]);
    await page.getByRole("button", { name: "Restore Fixture card", exact: true }).click();
    await expect(page.locator("[data-card-viewer]")).toHaveCount(1);
    const otherCard = page.getByRole("button", { name: "Restore Card other-0", exact: true });
    if (!(await otherCard.isVisible())) await page.getByRole("button", { name: "Flipped cards · 1", exact: true }).click();
    await otherCard.click();
    await expect(page.locator("[data-card-viewer]")).toHaveCount(1);
    await expect(page.getByText("Card other-0", { exact: true }).first()).toBeVisible();
    const swappedCard = page.getByRole("button", { name: "Restore Fixture card", exact: true });
    if (!(await swappedCard.isVisible())) await page.getByRole("button", { name: "Flipped cards · 1", exact: true }).click();
    await expect(swappedCard).toBeVisible();
});

test("card edit mode permits draft-preserving Flip while protecting tray swaps", async ({ page }) => {
    await mockBoardApi(page);
    await seedTray(page, 1);
    await page.goto(FIXTURE);
    await page.evaluate(() => {
        const events: string[] = [];
        (window as unknown as { __editEvents: string[] }).__editEvents = events;
        for (const name of ["pointerdown", "click", "focusin", "focusout"]) {
            document.addEventListener(
                name,
                (event) => {
                    const target = event.target as HTMLElement;
                    const label = target.getAttribute("aria-label") ?? target.textContent?.slice(0, 40);
                    events.push(`${name}:${target.tagName}:${label}:${!!target.closest("[data-dialog-content]")}`);
                },
                true
            );
        }
    });
    await page.locator("[data-floating-nav-content]").getByRole("button", { name: "Edit", exact: true }).click();
    try {
        await expect(page.getByRole("button", { name: "Cancel", exact: true })).toBeVisible();
        await expect(page.getByRole("button", { name: "Flip card", exact: true })).toBeEnabled();
    } catch (error) {
        console.error(
            "Edit transition diagnostics:",
            await page.evaluate(() => ({
                events: (window as unknown as { __editEvents: string[] }).__editEvents,
                buttons: Array.from(document.querySelectorAll("[data-floating-nav-content] button")).map((button) => ({
                    text: button.textContent,
                    disabled: (button as HTMLButtonElement).disabled,
                })),
            }))
        );
        throw error;
    }
    await expect(page.getByRole("button", { name: "Restore Card other-0", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.getByRole("button", { name: "Flip card", exact: true })).toBeEnabled();
});

for (const width of [360, 390, 768, 1440]) {
    for (const count of [1, 3, 10]) {
        test(`Flip tray contains ${count} cards without horizontal overflow at ${width}px`, async ({ page }) => {
            await page.setViewportSize({ width, height: 844 });
            await mockBoardApi(page);
            await seedTray(page, count);
            await page.goto(FIXTURE);
            const tray = page.locator("[data-card-flip-tray]");
            await expect(tray).toBeVisible();
            await expect(page.getByText("Foreign card", { exact: true })).toHaveCount(0);
            const bounds = await tray.boundingBox();
            expect(bounds!.x).toBeGreaterThanOrEqual(0);
            expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
            const overflow = page.getByRole("button", { name: `Flipped cards · ${count}`, exact: true });
            if (width < 768 || count === 10) {
                await overflow.click();
                await expect(page.getByRole("button", { name: `Restore Card other-${count - 1}`, exact: true })).toBeVisible();
                await page.keyboard.press("Escape");
                await expect(page.locator("[data-card-viewer]")).toHaveCount(1);
            }
        });
    }
}

for (const status of [403, 500]) {
    test(`tray availability ${status} ${status === 403 ? "removes inaccessible" : "preserves temporarily unavailable"} cards`, async ({ page }) => {
        await mockBoardApi(page);
        await seedTray(page, 3);
        let validated = false;
        await page.route("**/board/fixture-project/cards/available", async (route) => {
            if (route.request().method() === "OPTIONS") {
                await route.fulfill({ status: 204, headers: corsHeaders(route) });
                return;
            }
            validated = true;
            await route.fulfill({ status, json: { message: "Availability fixture" }, headers: corsHeaders(route) });
        });
        await page.goto(FIXTURE);
        await expect(page.getByRole("button", { name: "Flip card", exact: true })).toBeVisible();
        await expect.poll(() => validated).toBe(true);
        const persistedCount = () =>
            page.evaluate(
                () => JSON.parse(sessionStorage.getItem("langboard-card-flip-session")!).state.trays["fixture-user:fixture-project"].length
            );
        await expect.poll(persistedCount).toBe(status === 403 ? 0 : 3);
        await expect(page.locator("[data-card-viewer]")).toHaveCount(1);
    });
}

test("reduced-motion keeps the compact tray keyboard accessible", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 390, height: 844 });
    await mockBoardApi(page);
    await seedTray(page, 3);
    await page.goto(FIXTURE);
    const button = page.getByRole("button", { name: "Flipped cards · 3", exact: true });
    await button.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "Restore Card other-0", exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await expect(button).toBeFocused();
    await expect(page.locator("[data-card-viewer]")).toHaveCount(1);
});

test("retained comment draft has a tray dot and restore expands from the chip", async ({ page }) => {
    await mockBoardApi(page);
    await seedTray(page, 1);
    await page.addInitScript(() => sessionStorage.setItem("comment-fixture-project-other-0", "Unsaved comment"));
    await page.goto(FIXTURE);
    const chip = page.locator("[data-card-flip-item=other-0]");
    await expect(chip.locator("[data-card-flip-unsaved]")).toBeVisible();
    await page.getByRole("button", { name: "Restore Card other-0", exact: true }).click();
    const viewer = page.locator("[data-card-viewer]");
    await expect(viewer).toHaveCount(1);
    await expect.poll(() => viewer.evaluate((element) => element.style.getPropertyValue("--card-origin-transform"))).toContain("translate(");
});

test("restoring a suspended card resumes its unsaved title edit", async ({ page }) => {
    await mockBoardApi(page);
    await page.addInitScript(() => {
        sessionStorage.setItem(
            "langboard-card-flip-drafts",
            JSON.stringify({ state: { drafts: { "fixture-user:fixture-project:fixture-card": { title: "Suspended title" } } }, version: 0 })
        );
    });
    await page.goto(FIXTURE);
    await expect(page.getByRole("button", { name: "Cancel", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Flip card", exact: true }).click();
    await expect(page.locator("[data-card-viewer]")).toHaveCount(0);
    await expect(page.locator("[data-card-flip-unsaved]")).toBeVisible();
    await page.getByRole("button", { name: "Restore Fixture card", exact: true }).click();
    await expect(page.getByRole("button", { name: "Cancel", exact: true })).toBeVisible();
});

for (const width of [390, 1280]) {
    test(`tray drag changes order without restoring a card at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 844 });
        await mockBoardApi(page);
        await seedTray(page, 3);
        await page.goto(FIXTURE);
        const overflow = page.getByRole("button", { name: "Flipped cards · 3", exact: true });
        const vertical = width < 768;
        if (vertical) await overflow.waitFor({ state: "visible" });
        if (vertical) await overflow.click();
        const first = await page.locator("[data-card-flip-item=other-0] [data-card-flip-drag-handle]").boundingBox();
        const last = await page.locator("[data-card-flip-item=other-2]").boundingBox();
        await page.mouse.move(first!.x + first!.width / 2, first!.y + first!.height / 2);
        await page.mouse.down();
        await page.mouse.move(vertical ? last!.x + 12 : last!.x + last!.width / 2 + 8, vertical ? last!.y + last!.height / 2 + 8 : last!.y + 12, {
            steps: 20,
        });
        await page.mouse.up();
        await expect
            .poll(() =>
                page.evaluate(() =>
                    JSON.parse(sessionStorage.getItem("langboard-card-flip-session")!).state.trays["fixture-user:fixture-project"].map(
                        (card: { uid: string }) => card.uid
                    )
                )
            )
            .toEqual(["other-1", "other-2", "other-0"]);
        await expect(page.locator("[data-card-viewer]")).toHaveCount(1);
    });
}

test("touch drag reorders compact tray without restoring", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockBoardApi(page);
    await seedTray(page, 3);
    await page.goto(FIXTURE);
    await page.getByRole("button", { name: "Flipped cards · 3", exact: true }).click();
    const first = await page.locator("[data-card-flip-item=other-0] [data-card-flip-drag-handle]").boundingBox();
    const last = await page.locator("[data-card-flip-item=other-2]").boundingBox();
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: first!.x + 10, y: first!.y + 15 }] });
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: last!.x + 10, y: last!.y + last!.height / 2 + 8 }] });
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await expect
        .poll(() =>
            page.evaluate(() =>
                JSON.parse(sessionStorage.getItem("langboard-card-flip-session")!).state.trays["fixture-user:fixture-project"].map(
                    (c: { uid: string }) => c.uid
                )
            )
        )
        .toEqual(["other-1", "other-2", "other-0"]);
    await expect(page.locator("[data-card-viewer]")).toHaveCount(1);
});
