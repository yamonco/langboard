import { test, expect, type Page, type Route } from "@playwright/test";

const FIXTURE = "/src/pages/BoardPage/components/board/CardViewerDeepLink.fixture.html";

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
    api_key_role_actions: ["all"],
    setting_role_actions: ["all"],
    mcp_role_actions: ["all"],
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
    current_auth_role_actions: ["all"],
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
            current_auth_role_actions: ["all"],
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
    await page.route("**/board/fixture-project/card/fixture-card", async (route) => {
        if (options.cardDelay) {
            await new Promise((resolve) => setTimeout(resolve, options.cardDelay));
        }
        await fulfillWithCors(route, cardPayload);
    });
    await page.route("**/board/fixture-project/column/dock", (route) => fulfillWithCors(route, { column_uids: [] }));
    await page.route("**/board/fixture-project/columns", (route) => fulfillWithCors(route, { columns: [] }));
    await page.route("**/board/fixture-project", async (route) => {
        if (options.projectDelay) {
            await new Promise((resolve) => setTimeout(resolve, options.projectDelay));
        }
        await fulfillWithCors(route, projectPayload);
    });
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
