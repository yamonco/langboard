const assert = require("node:assert/strict");
const { execFile } = require("node:child_process");
const fs = require("node:fs/promises");
const path = require("node:path");
const { promisify } = require("node:util");
const { chromium } = require(
  process.env.PLAYWRIGHT_MODULE_PATH || "playwright",
);

const exec = promisify(execFile);
const runId = process.env.BOARD_CHAT_RUN_ID;
const apiContainer = process.env.PHOENIX_BROWSER_API_CONTAINER;
const fixturePath = process.env.PHOENIX_BROWSER_FIXTURE_PATH;
const origin = process.env.PHOENIX_BROWSER_UI_ORIGIN;
const uiBuild = path.resolve(process.env.BOARD_CHAT_UI_BUILD || "");
const output = path.resolve("local/socket-migration", `socket-ui-${runId}`);
const results = [];
const errors = [];

function redactCredentials(message) {
  return message.replace(/([?&]authorization=)[^&#\s]+/gi, "$1[redacted]");
}

assert.match(runId || "", /^[0-9a-f-]{36}$/);
assert.ok(
  apiContainer && fixturePath && origin && process.env.BOARD_CHAT_UI_BUILD,
);

async function credentials() {
  const response = await exec(
    "docker",
    [
      "exec",
      apiContainer,
      "uv",
      "run",
      "--no-sync",
      "python",
      fixturePath,
      "credentials",
      runId,
    ],
    { timeout: 180000 },
  );
  return JSON.parse(response.stdout.trim());
}

async function makePage(browser, user, cookieName, mobile) {
  const context = await browser.newContext(
    mobile
      ? {
          viewport: { width: 390, height: 844 },
          isMobile: true,
          hasTouch: true,
        }
      : { viewport: { width: 1360, height: 860 } },
  );
  await context.addCookies([
    {
      name: cookieName,
      value: user.refresh_token,
      url: origin,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  await context.addInitScript(() => {
    const Native = window.WebSocket;
    window.__socketUiFrames = [];
    window.WebSocket = class extends Native {
      constructor(url, protocols) {
        if (protocols === undefined) super(url);
        else super(url, protocols);
        this.addEventListener("message", (event) => {
          if (typeof event.data !== "string") return;
          try {
            const frame = JSON.parse(event.data);
            if (
              ["subscribed", "subscription:revoked", "error"].includes(
                frame.event,
              ) ||
              frame.event?.startsWith("board:card:created:") ||
              frame.event?.includes("wiki")
            ) {
              window.__socketUiFrames.push(frame);
            }
          } catch {
            // Non-JSON editor frames are checked by the editor probe.
          }
        });
      }
    };
  });
  await context.route(`${origin}/**`, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (
      request.resourceType() !== "document" &&
      !pathname.startsWith("/assets/") &&
      !pathname.startsWith("/images/")
    ) {
      return route.continue();
    }
    const file = path.resolve(
      uiBuild,
      request.resourceType() === "document" ? "index.html" : pathname.slice(1),
    );
    assert.ok(file.startsWith(uiBuild + path.sep));
    await route.fulfill({
      body: await fs.readFile(file),
      contentType: file.endsWith(".html")
        ? "text/html"
        : file.endsWith(".css")
          ? "text/css"
          : file.endsWith(".js")
            ? "text/javascript"
            : undefined,
    });
  });
  const page = await context.newPage();
  page.on("pageerror", (error) =>
    errors.push({ mobile, message: redactCredentials(error.message) }),
  );
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push({ mobile, message: redactCredentials(message.text()) });
    }
  });
  return page;
}

async function visit(
  page,
  name,
  route,
  topic,
  mobile,
  topicId,
  dialog = false,
) {
  await page.goto(`${origin}${route}`, { waitUntil: "domcontentloaded" });
  try {
    await page.waitForFunction(
      ({ route, topic, topicId, name }) =>
        (window.location.pathname === route ||
          (name === "wiki" &&
            window.location.pathname.startsWith(`${route}/`))) &&
        document.body.innerText.trim().length > 10 &&
        window.__socketUiFrames.some(
          (frame) =>
            frame.event === "subscribed" &&
            frame.topic === topic &&
            (topicId
              ? frame.topic_id.includes(topicId)
              : frame.topic_id.length > 0),
        ),
      { route, topic, topicId, name },
      { timeout: 30000 },
    );
    if (dialog) await page.getByRole("dialog").waitFor({ timeout: 30000 });
    if (topic === "board") {
      await page
        .getByText("Editor verification", { exact: true })
        .waitFor({ timeout: 30000 });
    }
  } catch (error) {
    const state = await page.evaluate(() => ({
      pathname: location.pathname,
      text: document.body.innerText.slice(0, 2000),
      frames: window.__socketUiFrames,
    }));
    await page.screenshot({
      path: path.join(
        output,
        `failed-${mobile ? "mobile" : "desktop"}-${name}.png`,
      ),
    });
    throw new Error(`${name} socket UI failed: ${JSON.stringify(state)}`, {
      cause: error,
    });
  }
  const visibleText = await page.locator("body").innerText();
  assert.ok(!visibleText.includes("Page not found"), `${name} rendered 404`);
  await page.screenshot({
    path: path.join(output, `${mobile ? "mobile" : "desktop"}-${name}.png`),
  });
  results.push({
    name,
    route,
    topic,
    topicId,
    mobile,
    pathname: new URL(page.url()).pathname,
  });
}

async function main() {
  let completed = false;
  await fs.mkdir(output, { recursive: true });
  const fixture = await credentials();
  const browser = await chromium.launch({
    headless: true,
    channel: "chrome",
    args: ["--disable-features=LocalNetworkAccessChecks"],
  });
  try {
    const desktop = await makePage(
      browser,
      fixture.users[0],
      fixture.refresh_cookie_name,
      false,
    );
    const mobile = await makePage(
      browser,
      fixture.users[1],
      fixture.refresh_cookie_name,
      true,
    );
    const mobileAdmin = await makePage(
      browser,
      fixture.users[0],
      fixture.refresh_cookie_name,
      true,
    );
    const project = fixture.project_uid;
    const routes = [
      ["dashboard-projects", "/dashboard/projects/all", "dashboard", project],
      ["dashboard-cards", "/dashboard/cards", "global", "all"],
      ["dashboard-tracking", "/dashboard/tracking", "global", "all"],
      ["board", `/board/${project}`, "board", project],
      [
        "card",
        `/board/${project}/${fixture.card_uid}`,
        "board_card",
        fixture.card_uid,
      ],
      ["wiki", `/board/${project}/wiki`, "board_wiki", project],
      [
        "wiki-document",
        `/board/${project}/wiki/${fixture.wiki_uid}`,
        "board_wiki",
        project,
      ],
      [
        "project-settings",
        `/board/${project}/settings`,
        "board_settings",
        project,
      ],
    ];
    for (const [name, route, topic, topicId] of routes) {
      await visit(desktop, name, route, topic, false, topicId);
      await visit(mobile, name, route, topic, true, topicId);
      if (name === "wiki-document") {
        for (const page of [desktop, mobile]) {
          await page.waitForFunction(
            (wikiUID) =>
              window.__socketUiFrames.some(
                (frame) =>
                  frame.event === "subscribed" &&
                  frame.topic === "board_wiki_private" &&
                  frame.topic_id.includes(wikiUID),
              ),
            fixture.wiki_uid,
            { timeout: 30000 },
          );
        }
      }
    }
    await visit(
      desktop,
      "project-settings-edit",
      `/board/${project}/settings`,
      "board_settings",
      false,
      project,
    );
    await visit(
      mobile,
      "project-settings-peer",
      `/board/${project}/settings`,
      "board_settings",
      true,
      project,
    );
    const projectForm = desktop
      .locator("form")
      .filter({ has: desktop.locator('input[name="title"]') });
    const originalProjectTitle = await projectForm
      .locator('input[name="title"]')
      .inputValue();
    const projectTitle = `Live project ${runId}`;
    await projectForm
      .getByRole("button", { name: "Edit", exact: true })
      .click();
    await projectForm.locator('input[name="title"]').fill(projectTitle);
    await projectForm
      .getByRole("button", { name: "Save", exact: true })
      .click();
    await mobile.locator('input[name="title"]').waitFor({ timeout: 30000 });
    await mobile.waitForFunction(
      (title) => document.querySelector('input[name="title"]')?.value === title,
      projectTitle,
      { timeout: 30000 },
    );
    await mobile.reload({ waitUntil: "domcontentloaded" });
    await mobile.waitForFunction(
      (title) => document.querySelector('input[name="title"]')?.value === title,
      projectTitle,
      { timeout: 30000 },
    );
    await projectForm
      .getByRole("button", { name: "Edit", exact: true })
      .click();
    await projectForm.locator('input[name="title"]').fill(originalProjectTitle);
    await projectForm
      .getByRole("button", { name: "Save", exact: true })
      .click();
    await mobile.waitForFunction(
      (title) => document.querySelector('input[name="title"]')?.value === title,
      originalProjectTitle,
      { timeout: 30000 },
    );
    await mobile.reload({ waitUntil: "domcontentloaded" });
    await mobile.waitForFunction(
      (title) => document.querySelector('input[name="title"]')?.value === title,
      originalProjectTitle,
      { timeout: 30000 },
    );
    results.push({
      name: "project-settings-title-realtime",
      route: `/board/${project}/settings`,
      topic: "board_settings",
    });
    await visit(
      desktop,
      "board-after-settings",
      `/board/${project}`,
      "board",
      false,
      project,
    );
    await visit(
      mobile,
      "board-peer-after-settings",
      `/board/${project}`,
      "board",
      true,
      project,
    );
    await desktop.getByText("Editor verification", { exact: true }).waitFor();
    await mobile.getByText("Editor verification", { exact: true }).waitFor();
    await desktop.getByRole("button", { name: "Add column" }).click();
    const columnName = `Live column ${runId}`;
    await desktop.getByPlaceholder("Enter a name").fill(columnName);
    await desktop.getByPlaceholder("Enter a name").press("Enter");
    await desktop
      .getByText(columnName, { exact: true })
      .waitFor({ timeout: 30000 });
    await mobile
      .getByText(columnName, { exact: true })
      .waitFor({ timeout: 30000 });
    results.push({
      name: "board-column-create-realtime",
      route: `/board/${project}`,
      topic: "board",
    });
    await desktop
      .getByText(columnName, { exact: true })
      .locator("xpath=../..")
      .locator("button[aria-haspopup='menu']")
      .click();
    await desktop.getByRole("menuitem", { name: "Rename" }).click();
    const renamedColumn = `${columnName} renamed`;
    await desktop.getByPlaceholder("Enter a name").fill(renamedColumn);
    await desktop.getByRole("button", { name: "Save" }).click();
    await mobile
      .getByText(renamedColumn, { exact: true })
      .waitFor({ timeout: 30000 });
    results.push({
      name: "board-column-rename-realtime",
      route: `/board/${project}`,
      topic: "board",
    });
    await desktop
      .getByText(renamedColumn, { exact: true })
      .locator("xpath=../..")
      .locator("button[aria-haspopup='menu']")
      .click();
    await desktop.getByRole("menuitem", { name: "Delete column" }).click();
    await desktop.getByRole("button", { name: "Delete", exact: true }).click();
    await mobile
      .getByText(renamedColumn, { exact: true })
      .waitFor({ state: "detached", timeout: 30000 });
    await visit(
      mobile,
      "board-peer-after-column-delete",
      `/board/${project}`,
      "board",
      true,
      project,
    );
    await mobile.getByText("Editor verification", { exact: true }).waitFor();
    assert.equal(
      await mobile.getByText(renamedColumn, { exact: true }).count(),
      0,
    );
    results.push({
      name: "board-column-delete-realtime",
      route: `/board/${project}`,
      topic: "board",
    });
    const primaryColumn = desktop
      .getByText("Editor verification", { exact: true })
      .locator("xpath=ancestor::*[contains(@class, 'snap-center')][1]");
    await primaryColumn.getByRole("button", { name: "Add a card" }).click();
    const cardTitle = `Live card ${runId}`;
    await primaryColumn.getByPlaceholder("Enter a title").fill(cardTitle);
    await primaryColumn.getByPlaceholder("Enter a title").press("Enter");
    try {
      await mobile
        .getByText(cardTitle, { exact: true })
        .waitFor({ timeout: 30000 });
    } catch (error) {
      const state = await mobile.evaluate(() => ({
        pathname: location.pathname,
        text: document.body.innerText.slice(0, 4000),
        frames: window.__socketUiFrames,
      }));
      await fs.writeFile(
        path.join(output, "card-create-failure.json"),
        JSON.stringify({ cardTitle, state }, null, 2),
      );
      await mobile.screenshot({
        path: path.join(output, "card-create-failure.png"),
      });
      await mobile.reload({ waitUntil: "domcontentloaded" });
      const visibleAfterReload = await mobile
        .getByText(cardTitle, { exact: true })
        .waitFor({ timeout: 30000 })
        .then(
          () => true,
          () => false,
        );
      await fs.writeFile(
        path.join(output, "card-create-reload.json"),
        JSON.stringify({ visibleAfterReload }),
      );
      throw error;
    }
    await visit(
      mobile,
      "board-peer-after-card-create",
      `/board/${project}`,
      "board",
      true,
      project,
    );
    await mobile
      .getByText(cardTitle, { exact: true })
      .waitFor({ timeout: 30000 });
    results.push({
      name: "board-card-create-realtime",
      route: `/board/${project}`,
      topic: "board",
    });
    await desktop.goto(`${origin}/board/${project}/wiki`, {
      waitUntil: "domcontentloaded",
    });
    await mobile.goto(`${origin}/board/${project}/wiki`, {
      waitUntil: "domcontentloaded",
    });
    await desktop.locator(`#board-wiki-${fixture.wiki_uid}-tab`).waitFor();
    await mobile.locator(`#board-wiki-${fixture.wiki_uid}-tab`).waitFor();
    await Promise.all(
      [desktop, mobile].map((page) =>
        page.waitForFunction(
          (projectUID) =>
            window.__socketUiFrames.some(
              (frame) =>
                frame.event === "subscribed" &&
                frame.topic === "board_wiki" &&
                frame.topic_id.includes(projectUID),
            ),
          project,
        ),
      ),
    );
    const wikiCreateButton = desktop
      .locator("button:has(svg.lucide-plus):visible")
      .first();
    await wikiCreateButton.click();
    await desktop
      .locator("[id^='board-wiki-'][id$='-tab']")
      .filter({ hasText: "New page" })
      .waitFor({ timeout: 30000 });
    const mobileNewWikiTab = mobile
      .locator("[id^='board-wiki-'][id$='-tab']")
      .filter({ hasText: "New page" });
    try {
      await mobileNewWikiTab.waitFor({ state: "attached", timeout: 30000 });
    } catch (error) {
      console.error(
        JSON.stringify(
          await mobile.evaluate(() => ({
            tabs: [
              ...document.querySelectorAll("[id^='board-wiki-'][id$='-tab']"),
            ].map((tab) => tab.textContent),
            frames: window.__socketUiFrames.filter((frame) =>
              frame.event?.includes("wiki"),
            ),
          })),
        ),
      );
      throw error;
    }
    await mobileNewWikiTab.scrollIntoViewIfNeeded();
    await mobileNewWikiTab.waitFor({ state: "visible" });
    results.push({
      name: "wiki-create-realtime",
      route: `/board/${project}/wiki`,
      topic: "board_wiki",
    });
    await desktop.getByRole("button", { name: "Edit", exact: true }).click();
    await desktop
      .locator("h1 span")
      .filter({ hasText: "New page" })
      .dispatchEvent("pointerdown");
    const renamedWiki = `Live wiki ${runId}`;
    await desktop.locator("textarea:visible").fill(renamedWiki);
    await desktop.getByRole("button", { name: "Save", exact: true }).click();
    await mobile
      .locator("[id^='board-wiki-'][id$='-tab']")
      .filter({ hasText: renamedWiki })
      .waitFor({ timeout: 30000 });
    results.push({
      name: "wiki-title-realtime",
      route: `/board/${project}/wiki`,
      topic: "board_wiki",
    });
    for (const tab of ["starred", "recent", "unstarred"]) {
      const route = `/dashboard/projects/${tab}`;
      await visit(
        desktop,
        `dashboard-${tab}`,
        route,
        "dashboard",
        false,
        project,
      );
      await visit(
        mobile,
        `dashboard-${tab}`,
        route,
        "dashboard",
        true,
        project,
      );
    }
    for (const name of ["new-project", "my-activity"]) {
      const route = `/dashboard/projects/all/${name}`;
      await visit(
        desktop,
        `dashboard-${name}`,
        route,
        "dashboard",
        false,
        project,
        true,
      );
      await visit(
        mobile,
        `dashboard-${name}`,
        route,
        "dashboard",
        true,
        project,
        true,
      );
    }
    const accountPages = [
      "profile",
      "emails",
      "password",
      "groups",
      "preferences",
    ];
    for (const name of accountPages) {
      await visit(
        desktop,
        `account-${name}`,
        `/account/${name}`,
        "user_private",
        false,
        fixture.users[0].uid,
      );
      await visit(
        mobile,
        `account-${name}`,
        `/account/${name}`,
        "user_private",
        true,
        fixture.users[1].uid,
      );
    }
    const wikiDialogs = ["activity", "metadata"];
    for (const name of wikiDialogs) {
      const route = `/board/${project}/wiki/${fixture.wiki_uid}/${name}`;
      await visit(
        desktop,
        `wiki-${name}`,
        route,
        "board_wiki",
        false,
        project,
        true,
      );
      await visit(
        mobile,
        `wiki-${name}`,
        route,
        "board_wiki",
        true,
        project,
        true,
      );
    }
    const settings = [
      ["project-templates", null],
      ["api-keys", "api_key"],
      ["users", "user"],
      ["bots", "bot"],
      ["internal-bots", "internal_bot"],
      ["global-relationships", "global_relationship"],
      ["api-comfort-tools", "api_comfort_tool"],
      ["webhooks", "webhook"],
      ["notification-schedule", "notification_schedule"],
      ["mcp", "mcp_tool_group"],
    ];
    let editorBotUID;
    let settingBotUID;
    let settingBotName;
    for (const [name, topicId] of settings) {
      await visit(
        desktop,
        `settings-${name}`,
        `/settings/${name}`,
        "app_settings",
        false,
        topicId,
      );
      await visit(
        mobileAdmin,
        `settings-${name}`,
        `/settings/${name}`,
        "app_settings",
        true,
        topicId,
      );
      if (name === "bots") {
        const response = await exec(
          "docker",
          [
            "exec",
            apiContainer,
            "uv",
            "run",
            "--no-sync",
            "python",
            fixturePath,
            "create-setting-bot",
            runId,
          ],
          { timeout: 180000 },
        );
        const bot = JSON.parse(response.stdout.trim());
        settingBotUID = bot.uid;
        settingBotName = bot.name;
        await desktop.getByText(bot.name).waitFor({ timeout: 30000 });
        await mobileAdmin.getByText(bot.name).waitFor({ timeout: 30000 });
        results.push({
          name: "settings-bots-realtime",
          route: "/settings/bots",
          topic: "app_settings",
        });
      }
      if (name === "internal-bots") {
        const response = await exec(
          "docker",
          [
            "exec",
            apiContainer,
            "uv",
            "run",
            "--no-sync",
            "python",
            fixturePath,
            "configure-editor-ai",
            runId,
          ],
          { timeout: 180000 },
        );
        editorBotUID = JSON.parse(response.stdout.trim()).editor_chat_bot_uid;
        const displayName = `Migration Editor Chat ${runId}`;
        await desktop.getByText(displayName).waitFor({ timeout: 30000 });
        await mobileAdmin.getByText(displayName).waitFor({ timeout: 30000 });
        results.push({
          name: "settings-internal-bots-realtime",
          route: "/settings/internal-bots",
          topic: "global",
        });
      }
      if (name === "users") {
        const peerEmail = `editor-peer-${runId}@example.invalid`;
        const desktopPeer = desktop
          .getByRole("row")
          .filter({ hasText: peerEmail });
        const mobilePeer = mobileAdmin
          .getByRole("row")
          .filter({ hasText: peerEmail });
        await desktopPeer.waitFor({ timeout: 30000 });
        await mobilePeer.waitFor({ timeout: 30000 });
        const firstname = `Live User ${runId.slice(0, 8)}`;
        await desktopPeer.locator("td").nth(2).click();
        await desktopPeer.locator("td").nth(2).locator("input").fill(firstname);
        await desktopPeer.locator("td").nth(2).locator("input").press("Enter");
        await desktopPeer.getByText(firstname).waitFor({ timeout: 30000 });
        await mobilePeer.getByText(firstname).waitFor({ timeout: 30000 });
        await mobileAdmin.reload({ waitUntil: "domcontentloaded" });
        await mobileAdmin
          .getByRole("row")
          .filter({ hasText: peerEmail })
          .getByText(firstname)
          .waitFor({ timeout: 30000 });
        results.push({
          name: "settings-users-ui-update-realtime",
          route: "/settings/users",
          topic: "app_settings",
        });
      }
    }
    assert.ok(editorBotUID);
    assert.ok(settingBotUID);
    await visit(
      desktop,
      "bot-details",
      `/settings/bots/${settingBotUID}`,
      "app_settings",
      false,
      "bot",
    );
    await visit(
      mobileAdmin,
      "bot-details",
      `/settings/bots/${settingBotUID}`,
      "app_settings",
      true,
      "bot",
    );
    const renamedBot = `Live bot ${runId.slice(0, 8)}`;
    await desktop.getByText(settingBotName, { exact: true }).first().click();
    await desktop.locator("input:visible").first().fill(renamedBot);
    await desktop.locator("input:visible").first().press("Enter");
    await mobileAdmin
      .getByText(renamedBot, { exact: true })
      .waitFor({ timeout: 30000 });
    await mobileAdmin.reload({ waitUntil: "domcontentloaded" });
    await mobileAdmin
      .getByText(renamedBot, { exact: true })
      .waitFor({ timeout: 30000 });
    results.push({
      name: "settings-bot-ui-update-realtime",
      route: `/settings/bots/${settingBotUID}`,
      topic: "app_settings",
    });
    await visit(
      desktop,
      "internal-bot-details",
      `/settings/internal-bots/${editorBotUID}`,
      "app_settings",
      false,
      "internal_bot",
    );
    await visit(
      mobileAdmin,
      "internal-bot-details",
      `/settings/internal-bots/${editorBotUID}`,
      "app_settings",
      true,
      "internal_bot",
    );
    const createDialogs = [
      ["api-key", "/settings/api-keys/create", "api_key"],
      ["user", "/settings/users/create", "user"],
      ["bot", "/settings/bots/create", "bot"],
      ["internal-bot", "/settings/internal-bots/create", "internal_bot"],
      [
        "global-relationship",
        "/settings/global-relationships/create",
        "global_relationship",
      ],
      ["webhook", "/settings/webhooks/create", "webhook"],
      ["mcp-global", "/settings/mcp/create/global", "mcp_tool_group"],
      ["mcp-admin", "/settings/mcp/create/admin", "mcp_tool_group"],
    ];
    for (const [name, route, topicId] of createDialogs) {
      await visit(
        desktop,
        `create-${name}`,
        route,
        "app_settings",
        false,
        topicId,
        true,
      );
      await visit(
        mobileAdmin,
        `create-${name}`,
        route,
        "app_settings",
        true,
        topicId,
        true,
      );
    }
    assert.deepEqual(errors, []);
    completed = true;
  } finally {
    await browser.close();
    await fs.writeFile(
      path.join(output, "report.json"),
      JSON.stringify(
        {
          success: completed && errors.length === 0,
          results,
          errors,
        },
        null,
        2,
      ),
    );
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
