const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { chromium } = require(
  process.env.PLAYWRIGHT_MODULE_PATH || "playwright",
);

const exec = promisify(execFile);
const runId = process.env.PHOENIX_BROWSER_RUN_ID;
const scenario = process.env.PHOENIX_EDITOR_AI_SCENARIO;
const apiContainer = process.env.PHOENIX_BROWSER_API_CONTAINER;
const fixturePath = process.env.PHOENIX_BROWSER_FIXTURE_PATH;
const inspectPath = process.env.PHOENIX_BROWSER_INSPECT_PATH;
const graphContainer = process.env.PHOENIX_BROWSER_GRAPH_CONTAINER;
const origin = process.env.PHOENIX_BROWSER_UI_ORIGIN;
const apiOrigin = process.env.PHOENIX_BROWSER_API_ORIGIN;
const failoverSignal = process.env.PHOENIX_BROWSER_FAILOVER_SIGNAL;
const failoverStage = process.env.PHOENIX_BROWSER_FAILOVER_STAGE || "connected";
const reconnectRounds = Number.parseInt(
  process.env.PHOENIX_BROWSER_RECONNECT_ROUNDS || "1",
  10,
);
const uiBuild = path.resolve(process.env.PHOENIX_BROWSER_UI_BUILD || "");
const output = path.resolve(
  "local/socket-migration",
  `editor-ai-${scenario}-${runId}-${Date.now()}`,
);

assert.match(runId || "", /^[0-9a-f-]{36}$/);
assert.ok(
  ["copilot", "approve", "reject", "revocation", "cancel", "sync"].includes(
    scenario,
  ),
);
assert.ok(
  ["connected", "socket-reconnect", "repeated", "resume", "worker"].includes(
    failoverStage,
  ),
);
assert.ok(
  failoverStage === "connected" ||
    scenario === "approve" ||
    (scenario === "sync" && failoverStage === "repeated"),
);
assert.ok(Number.isInteger(reconnectRounds));
assert.ok(reconnectRounds >= 1 && reconnectRounds <= 20);
assert.ok(apiContainer && fixturePath && inspectPath && graphContainer);
assert.ok(origin, "PHOENIX_BROWSER_UI_ORIGIN is required");
assert.ok(apiOrigin, "PHOENIX_BROWSER_API_ORIGIN is required");
assert.ok(
  process.env.PHOENIX_BROWSER_UI_BUILD,
  "PHOENIX_BROWSER_UI_BUILD is required",
);

const errors = [];
const expectedDisconnectErrors = [];
const pages = [];
let browser;
let stage = "startup";

function redact(value) {
  return String(value)
    .replace(/authorization=[^\s'"&]+/gi, "authorization=<redacted>")
    .replace(/Bearer\s+[^\s'"&]+/gi, "Bearer <redacted>");
}

async function runDiagnostic(script, ...args) {
  const result = await exec(
    "docker",
    ["exec", apiContainer, "uv", "run", "--no-sync", "python", script, ...args],
    { timeout: 180000 },
  );
  return JSON.parse(result.stdout.trim());
}

async function snapshot() {
  return runDiagnostic(inspectPath, runId);
}

async function waitForRunStatus(taskID, expectedStatus) {
  const deadline = Date.now() + 90000;
  let lastRun;
  while (Date.now() < deadline) {
    const state = await snapshot();
    lastRun = state.runs.find((item) => item.client_task_id === taskID);
    if (lastRun?.status === expectedStatus) return state;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(
    `Editor AI run ${taskID} did not reach ${expectedStatus}; last status: ${lastRun?.status}`,
  );
}

async function waitForGraphBarrier(file) {
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    try {
      await exec("docker", ["exec", graphContainer, "test", "-f", file]);
      return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }
  throw new Error(`Graph did not reach ${file}`);
}

async function graphToolCallCount(marker) {
  const graphLogs = await exec("docker", ["logs", graphContainer], {
    timeout: 15000,
    maxBuffer: 2 * 1024 * 1024,
  });
  return graphLogs.stdout
    .split("\n")
    .filter((line) => line.startsWith("PROBE_TOOL ") && line.includes(marker))
    .length;
}

async function waitForPhoenixBrowserFailover(projectUID, round = 1) {
  assert.ok(failoverSignal, "PHOENIX_BROWSER_FAILOVER_SIGNAL is required");
  const signalSuffix = round === 1 ? "" : `.${round}`;
  const before = await Promise.all(
    pages.map((page) =>
      page.evaluate(
        (uid) => ({
          jsonCloses: window.__socketFrames.filter(
            (frame) => frame.event === "close" && frame.json,
          ).length,
          editorSyncCloses: window.__socketFrames.filter(
            (frame) => frame.event === "close" && frame.editorSync,
          ).length,
          editorSyncSockets: window.__editorSyncSockets.length,
          subscriptions: window.__socketFrames.filter(
            (frame) =>
              frame.event === "subscribed" &&
              frame.topic === "board" &&
              frame.topic_id?.includes(uid),
          ).length,
        }),
        projectUID,
      ),
    ),
  );
  before.forEach((state) => assert.ok(state.editorSyncSockets > 0));
  await fs.writeFile(
    `${failoverSignal}.ready${signalSuffix}`,
    JSON.stringify({ pages: pages.length, round }),
  );
  await Promise.all(
    pages.map((page, index) =>
      page.waitForFunction(
        ({ jsonCloses, editorSyncCloses }) =>
          window.__socketFrames.filter(
            (frame) => frame.event === "close" && frame.json,
          ).length > jsonCloses &&
          window.__socketFrames.filter(
            (frame) => frame.event === "close" && frame.editorSync,
          ).length > editorSyncCloses,
        before[index],
        { timeout: 90000 },
      ),
    ),
  );
  await fs.writeFile(
    `${failoverSignal}.disconnected${signalSuffix}`,
    JSON.stringify({ pages: pages.length, round }),
  );
  await Promise.all(
    pages.map((page, index) =>
      page.waitForFunction(
        ({ uid, editorSyncSockets, subscriptions }) =>
          window.__socketFrames.filter(
            (frame) =>
              frame.event === "subscribed" &&
              frame.topic === "board" &&
              frame.topic_id?.includes(uid),
          ).length > subscriptions &&
          window.__editorSyncSockets.length > editorSyncSockets &&
          window.__editorSyncSockets
            .slice(editorSyncSockets)
            .some((socket) => socket.readyState === WebSocket.OPEN),
        { uid: projectUID, ...before[index] },
        { timeout: 90000 },
      ),
    ),
  );
  await fs.writeFile(
    `${failoverSignal}.recovered${signalSuffix}`,
    JSON.stringify({ pages: pages.length, round }),
  );
}

async function waitForPhoenixWorkerLoss(projectUID) {
  assert.ok(failoverSignal, "PHOENIX_BROWSER_FAILOVER_SIGNAL is required");
  const before = await Promise.all(
    pages.map((page) =>
      page.evaluate(
        (uid) => ({
          closes: window.__socketFrames.filter(
            (frame) => frame.event === "close" && frame.json,
          ).length,
          subscriptions: window.__socketFrames.filter(
            (frame) =>
              frame.event === "subscribed" &&
              frame.topic === "board" &&
              frame.topic_id?.includes(uid),
          ).length,
        }),
        projectUID,
      ),
    ),
  );
  await fs.writeFile(
    `${failoverSignal}.ready`,
    JSON.stringify({ pages: pages.length }),
  );
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    try {
      await fs.access(`${failoverSignal}.recovered`);
      break;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  await fs.access(`${failoverSignal}.recovered`);
  await new Promise((resolve) => setTimeout(resolve, 1000));
  const after = await Promise.all(
    pages.map((page) =>
      page.evaluate(
        (uid) => ({
          closes: window.__socketFrames.filter(
            (frame) => frame.event === "close" && frame.json,
          ).length,
          subscriptions: window.__socketFrames.filter(
            (frame) =>
              frame.event === "subscribed" &&
              frame.topic === "board" &&
              frame.topic_id?.includes(uid),
          ).length,
          connected: window.__editorAISockets.some(
            (socket) => socket.readyState === WebSocket.OPEN,
          ),
        }),
        projectUID,
      ),
    ),
  );
  after.forEach((state, index) => {
    assert.equal(state.closes, before[index].closes);
    assert.equal(state.subscriptions, before[index].subscriptions);
    assert.equal(state.connected, true);
  });
}

async function reconnectEditorAISockets(owner, projectUID, taskID) {
  const ownerBefore = await owner.evaluate(
    ({ uid, id }) => ({
      closes: window.__socketFrames.filter(
        (frame) => frame.event === "close" && frame.json,
      ).length,
      sockets: window.__editorAISockets.length,
      subscriptions: window.__socketFrames.filter(
        (frame) =>
          frame.event === "subscribed" &&
          frame.topic === "board" &&
          frame.topic_id?.includes(uid),
      ).length,
      statusRequests: window.__editorAIFrames.filter(
        (frame) =>
          frame.direction === "out" &&
          frame.event === "board:editor:ai:status" &&
          frame.data.task_id === id,
      ).length,
      statusResults: window.__editorAIFrames.filter(
        (frame) =>
          frame.direction === "in" &&
          frame.event === "board:editor:ai:status:result" &&
          frame.data.task_id === id,
      ).length,
    }),
    { uid: projectUID, id: taskID },
  );
  await waitForPhoenixBrowserFailover(projectUID);
  const ownerAfter = await owner.evaluate(
    (uid) => ({
      closes: window.__socketFrames.filter(
        (frame) => frame.event === "close" && frame.json,
      ).length,
      sockets: window.__editorAISockets.length,
      subscriptions: window.__socketFrames.filter(
        (frame) =>
          frame.event === "subscribed" &&
          frame.topic === "board" &&
          frame.topic_id?.includes(uid),
      ).length,
      connected: window.__editorAISockets.some(
        (socket) => socket.readyState === WebSocket.OPEN,
      ),
    }),
    projectUID,
  );
  assert.equal(ownerAfter.closes, ownerBefore.closes + 1);
  assert.ok(ownerAfter.sockets > ownerBefore.sockets);
  assert.ok(ownerAfter.subscriptions > ownerBefore.subscriptions);
  assert.equal(ownerAfter.connected, true);
  await owner.waitForFunction(
    ({ id, requests, results }) =>
      window.__editorAIFrames.filter(
        (frame) =>
          frame.direction === "out" &&
          frame.event === "board:editor:ai:status" &&
          frame.data.task_id === id,
      ).length > requests &&
      window.__editorAIFrames.filter(
        (frame) =>
          frame.direction === "in" &&
          frame.event === "board:editor:ai:status:result" &&
          frame.data.task_id === id,
      ).length > results,
    {
      id: taskID,
      requests: ownerBefore.statusRequests,
      results: ownerBefore.statusResults,
    },
    { timeout: 30000 },
  );
  const recoveredStatus = await owner.evaluate(
    (id) =>
      window.__editorAIFrames.findLast(
        (frame) =>
          frame.direction === "in" &&
          frame.event === "board:editor:ai:status:result" &&
          frame.data.task_id === id,
      ).data.status,
    taskID,
  );
  assert.equal(recoveredStatus, "resuming");
}

async function openEditor(page, url, projectUID) {
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    (uid) =>
      window.__editorAISockets.some(
        (socket) =>
          socket.readyState === WebSocket.OPEN &&
          new URL(socket.url).pathname === "/",
      ) &&
      window.__socketFrames.some(
        (frame) =>
          frame.event === "subscribed" &&
          frame.topic === "board" &&
          frame.topic_id?.includes(uid),
      ),
    projectUID,
    { timeout: 90000 },
  );
  const mobile = page.viewportSize().width < 600;
  const editor = page.locator(
    '[data-card-description] [contenteditable="true"]',
  );
  const deadline = Date.now() + 90000;
  let lastTransitionError = "";
  while (Date.now() < deadline) {
    try {
      if (await editor.isVisible()) break;
      const save = page.getByRole("button", { name: "Save", exact: true });
      if (!(await save.isVisible())) {
        const edit = page.getByRole("button", { name: "Edit", exact: true });
        await edit.waitFor({ timeout: 10000 });
        await page.waitForTimeout(500);
        if (!(await edit.isVisible())) continue;
        if (mobile) await edit.tap({ timeout: 10000 });
        else await edit.click({ timeout: 10000 });
      }
      await save.waitFor({ timeout: 10000 });
      if (mobile) await page.locator("[data-card-description]").tap();
      else await page.locator("[data-card-description]").click();
      await editor.waitFor({ timeout: 10000 });
      await page.waitForTimeout(500);
      if (!(await editor.isVisible())) continue;
      break;
    } catch (error) {
      lastTransitionError =
        error instanceof Error ? error.message : String(error);
      // A first-load Card model replacement can remount the modal once.
      await page.waitForTimeout(250);
    }
  }
  if (!(await editor.isVisible())) {
    const editButtonCount = await page
      .getByRole("button", { name: "Edit", exact: true })
      .count();
    const saveButtonCount = await page
      .getByRole("button", { name: "Save", exact: true })
      .count();
    throw new Error(
      `Card description did not enter edit mode (edit buttons: ${editButtonCount}, save buttons: ${saveButtonCount}, editors: ${await editor.count()}): ${lastTransitionError}`,
    );
  }
  await page.waitForFunction(
    () => !document.querySelector("[data-card-description] .cursor-wait"),
  );
  return editor;
}

async function createPage(credentials, userIndex) {
  const context = await browser.newContext(
    userIndex
      ? {
          viewport: { width: 390, height: 844 },
          isMobile: true,
          hasTouch: true,
        }
      : { viewport: { width: 1360, height: 860 } },
  );
  await context.addCookies([
    {
      name: credentials.refresh_cookie_name,
      value: credentials.users[userIndex].refresh_token,
      url: origin,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  await context.addInitScript(() => {
    const NativeWebSocket = window.WebSocket;
    window.__editorAIFrames = [];
    window.__editorAISockets = [];
    window.__editorSyncSockets = [];
    window.__socketFrames = [];
    window.__editorActivation = [];
    window.__richPatchFrames = [];

    const recordRichFrame = (payload, direction) => {
      if (!(payload instanceof ArrayBuffer) && !ArrayBuffer.isView(payload))
        return;
      const bytes =
        payload instanceof ArrayBuffer
          ? new Uint8Array(payload)
          : new Uint8Array(
              payload.buffer,
              payload.byteOffset,
              payload.byteLength,
            );
      let offset = 0;
      const integer = () => {
        let value = 0;
        let shift = 0;
        for (;;) {
          if (offset >= bytes.length || shift > 28)
            throw new Error("Invalid frame");
          const byte = bytes[offset++];
          value += (byte & 127) * 2 ** shift;
          if (byte < 128) return value;
          shift += 7;
        }
      };
      const string = () => {
        const size = integer();
        const value = new TextDecoder().decode(
          bytes.subarray(offset, offset + size),
        );
        offset += size;
        return value;
      };
      try {
        const documentName = string();
        if (integer() !== 5) return;
        const message = JSON.parse(string());
        window.__richPatchFrames.push({
          direction,
          documentName,
          type: message.type,
          request_id: message.request_id,
          bytes: bytes.length,
        });
      } catch {
        // Non-diagnostic editor frames retain their normal transport behavior.
      }
    };

    for (const type of ["pointerdown", "pointerup", "click"]) {
      document.addEventListener(
        type,
        (event) => {
          const button = event.target.closest?.("button");
          if (button)
            window.__editorActivation.push({
              type,
              text: button.innerText,
              label: button.getAttribute("aria-label"),
              x: event.clientX,
              y: event.clientY,
            });
        },
        true,
      );
    }

    window.WebSocket = class extends NativeWebSocket {
      constructor(url, protocols) {
        if (protocols === undefined) super(url);
        else super(url, protocols);
        const pathname = new URL(this.url).pathname;
        if (pathname === "/editor-sync") {
          window.__editorSyncSockets.push(this);
          this.addEventListener("message", (event) =>
            recordRichFrame(event.data, "in"),
          );
          this.addEventListener("close", (event) =>
            window.__socketFrames.push({
              event: "close",
              code: event.code,
              reason: event.reason,
              editorSync: true,
            }),
          );
          return;
        }
        if (pathname !== "/") return;
        window.__editorAISockets.push(this);
        this.addEventListener("message", (event) => {
          if (typeof event.data !== "string" || !event.data.startsWith("{"))
            return;
          const frame = JSON.parse(event.data);
          window.__socketFrames.push({
            event: frame.event,
            topic: frame.topic,
            topic_id: frame.topic_id,
          });
          if (
            frame.event?.includes("editor") ||
            frame.event?.includes("graph:approval")
          )
            window.__editorAIFrames.push({ direction: "in", ...frame });
        });
        this.addEventListener("close", (event) =>
          window.__socketFrames.push({
            event: "close",
            code: event.code,
            reason: event.reason,
            json: true,
          }),
        );
      }

      send(payload) {
        if (new URL(this.url).pathname === "/editor-sync")
          recordRichFrame(payload, "out");
        if (typeof payload === "string" && payload.startsWith("{")) {
          const frame = JSON.parse(payload);
          if (frame.event?.includes("editor"))
            window.__editorAIFrames.push({ direction: "out", ...frame });
        }
        return super.send(payload);
      }
    };
  });
  await context.route(`${origin}/**`, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (
      request.resourceType() !== "document" &&
      !pathname.startsWith("/assets/")
    )
      return route.continue();
    const file = path.resolve(
      uiBuild,
      request.resourceType() === "document" ? "index.html" : pathname.slice(1),
    );
    assert.ok(file.startsWith(`${uiBuild}${path.sep}`));
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
  pages.push(page);
  page.on("pageerror", (error) =>
    errors.push({ stage, userIndex, message: redact(error.message) }),
  );
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const error = { stage, userIndex, message: redact(message.text()) };
    const expectedDisconnectError =
      ["socket-reconnect", "repeated"].includes(failoverStage) &&
      (stage === "socket-reconnect" ||
        stage.startsWith("editor-sync-reconnect-")) &&
      error.message.includes("WebSocket connection to") &&
      error.message.includes("/editor-sync?") &&
      error.message.includes("net::ERR_CONNECTION_REFUSED");
    (expectedDisconnectError ? expectedDisconnectErrors : errors).push(error);
  });
  return page;
}

async function runCopilot(owner, peer, ownerEditor, credentials) {
  await ownerEditor.press("Enter");
  await owner.keyboard.insertText("Database transactions guarantee that ");
  await ownerEditor.press("Control+Space");
  stage = "copilot-submitted";
  await owner.waitForFunction(
    () =>
      window.__editorAIFrames.some(
        (frame) =>
          frame.direction === "out" && frame.event.endsWith(":copilot:send"),
      ),
    null,
    { timeout: 30000 },
  );
  const taskID = await owner.evaluate(
    () =>
      window.__editorAIFrames.find(
        (frame) =>
          frame.direction === "out" && frame.event.endsWith(":copilot:send"),
      ).data.task_id,
  );
  await owner.waitForFunction(
    (id) =>
      window.__editorAIFrames.some(
        (frame) =>
          frame.direction === "in" &&
          frame.event.endsWith(`:copilot:receive:${id}`),
      ),
    taskID,
    { timeout: 120000 },
  );
  const generatedText = await owner.evaluate(
    (id) =>
      window.__editorAIFrames.find(
        (frame) =>
          frame.direction === "in" &&
          frame.event.endsWith(`:copilot:receive:${id}`),
      ).data.text,
    taskID,
  );
  assert.ok(
    typeof generatedText === "string" &&
      generatedText.trim().length > 2 &&
      generatedText !== "0",
  );
  assert.ok(
    !generatedText
      .trimStart()
      .startsWith("Database transactions guarantee that"),
    "Copilot repeated the supplied sentence prefix",
  );
  await owner.waitForFunction(
    (text) =>
      Array.from(
        document.querySelectorAll(
          '[data-card-description] span[contenteditable="false"]',
        ),
      ).some((node) => node.textContent.includes(text)),
    generatedText,
  );
  await owner.screenshot({ path: path.join(output, "copilot-suggestion.png") });
  await owner.keyboard.press("Tab");
  await peer.waitForFunction(
    (text) =>
      document
        .querySelector('[data-card-description] [contenteditable="true"]')
        ?.textContent.includes(text),
    generatedText,
    { timeout: 30000 },
  );
  await owner.getByRole("button", { name: "Save", exact: true }).click();
  return { taskID, generatedText, approvalUID: undefined };
}

async function runApproval(owner, peer, ownerEditor, credentials) {
  const marker = `Editor ${scenario} verified ${runId} ${Date.now()}`;
  await ownerEditor.press("Control+j");
  const input = owner.getByPlaceholder("Ask AI anything...");
  await input.fill(
    `Use change_card_details to set only the description of card ${credentials.card_uid} in project ${credentials.project_uid} to exactly "${marker}". Keep the title unchanged. Call the tool once and report its result; do not just write suggested prose.`,
  );
  await input.press("Enter");
  stage = "approval-requested";
  await owner.waitForFunction(
    () =>
      window.__editorAIFrames.some(
        (frame) =>
          frame.direction === "out" && frame.event.endsWith(":chat:send"),
      ),
    null,
    { timeout: 30000 },
  );
  const taskID = await owner.evaluate(
    () =>
      window.__editorAIFrames.find(
        (frame) =>
          frame.direction === "out" && frame.event.endsWith(":chat:send"),
      ).data.task_id,
  );
  await owner
    .getByText("Human input required", { exact: true })
    .waitFor({ timeout: 120000 });
  assert.equal(
    await peer.getByRole("button", { name: "Approve", exact: true }).count(),
    0,
  );
  assert.equal(
    await peer.getByRole("button", { name: "Reject", exact: true }).count(),
    0,
  );
  const before = await snapshot();
  const run = before.runs.find((item) => item.client_task_id === taskID);
  assert.equal(run?.status, "InternalBotRunStatus.AwaitingApproval");
  assert.ok(!JSON.stringify(before.description).includes(marker));
  assert.equal(
    before.approvals.filter((item) => item.thread_id === run.graph_thread_id)
      .length,
    1,
  );
  await owner.screenshot({
    path: path.join(output, "approval-pending-desktop.png"),
  });
  await peer.screenshot({
    path: path.join(output, "approval-pending-mobile.png"),
  });

  const url = `${origin}/board/${credentials.project_uid}/${credentials.card_uid}`;
  await openEditor(owner, url, credentials.project_uid);
  await owner
    .getByText("Human input required", { exact: true })
    .waitFor({ timeout: 30000 });
  stage = "resuming";
  await owner
    .getByRole("button", {
      name: scenario === "approve" ? "Approve" : "Reject",
      exact: true,
    })
    .click();
  await owner.waitForFunction(
    () =>
      window.__editorAIFrames.some(
        (frame) =>
          frame.direction === "out" &&
          frame.event === "board:editor:approval:resume",
      ),
    null,
    { timeout: 10000 },
  );
  const approvalUID = await owner.evaluate(
    () =>
      window.__editorAIFrames.find(
        (frame) =>
          frame.direction === "out" &&
          frame.event === "board:editor:approval:resume",
      ).data.approval_uid,
  );
  if (["socket-reconnect", "resume", "worker"].includes(failoverStage)) {
    const deadline = Date.now() + 150000;
    let held = false;
    while (Date.now() < deadline) {
      try {
        await exec("docker", [
          "exec",
          graphContainer,
          "test",
          "-f",
          "/tmp/phoenix-held-tool",
        ]);
        held = true;
        break;
      } catch {
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
    }
    assert.ok(
      held,
      "The Editor edit must reach the post-mutation response barrier",
    );
    const beforeLoss = await snapshot();
    const resumingRun = beforeLoss.runs.find(
      (item) => item.client_task_id === taskID,
    );
    assert.equal(resumingRun?.status, "InternalBotRunStatus.Resuming");
    assert.ok(!JSON.stringify(beforeLoss.description).includes(marker));
    await assertDraftPatch(owner, marker);
    await assertDraftPatch(peer, marker);

    if (failoverStage === "socket-reconnect") {
      stage = "socket-reconnect";
      await reconnectEditorAISockets(owner, credentials.project_uid, taskID);
      await assertDraftPatch(owner, marker);
      await assertDraftPatch(peer, marker);
      await exec("docker", [
        "exec",
        graphContainer,
        "touch",
        "/tmp/phoenix-release-tool",
      ]);
    } else {
      stage =
        failoverStage === "resume" ? "resume-node-loss" : "resume-worker-loss";
      if (failoverStage === "resume") {
        await waitForPhoenixBrowserFailover(credentials.project_uid);
      } else {
        await waitForPhoenixWorkerLoss(credentials.project_uid);
      }
    }
    await assertDraftPatch(owner, marker);
    await assertDraftPatch(peer, marker);
    if (failoverStage !== "socket-reconnect") {
      await openEditor(
        owner,
        `${origin}/board/${credentials.project_uid}/${credentials.card_uid}`,
        credentials.project_uid,
      );
      await owner
        .getByText("Human input required", { exact: true })
        .waitFor({ timeout: 30000 });
      assert.equal(
        await owner
          .getByRole("button", { name: "Approve", exact: true })
          .isDisabled(),
        true,
      );
      assert.equal(
        await owner
          .getByRole("button", { name: "Reject", exact: true })
          .isDisabled(),
        true,
      );

      await runDiagnostic(inspectPath, runId, "--expire");
      await exec(
        "docker",
        [
          "exec",
          apiContainer,
          "/app/.venv/bin/langboard",
          "run:internal-bot-runs:recover",
        ],
        { timeout: 180000 },
      );
      const uncertain = await snapshot();
      const uncertainRun = uncertain.runs.find(
        (item) => item.client_task_id === taskID,
      );
      assert.equal(uncertainRun?.status, "InternalBotRunStatus.Uncertain");
      assert.ok(!JSON.stringify(uncertain.description).includes(marker));
      assert.deepEqual(uncertainRun?.decision, {
        approved: true,
        rejected: false,
      });

      if (failoverStage === "resume") {
        await exec("docker", [
          "exec",
          graphContainer,
          "touch",
          "/tmp/phoenix-release-tool",
        ]);
      }
      await owner.getByRole("button", { name: "Save", exact: true }).click();
      await owner
        .getByRole("button", { name: "Edit", exact: true })
        .waitFor({ timeout: 30000 });
      const saved = await snapshot();
      assert.ok(JSON.stringify(saved.description).includes(marker));
      await peer.reload({ waitUntil: "domcontentloaded" });
      await peer.waitForFunction(
        (text) =>
          document
            .querySelector("[data-card-description]")
            ?.textContent.includes(text),
        marker,
        { timeout: 30000 },
      );
      await owner.reload({ waitUntil: "domcontentloaded" });
      await owner
        .getByText("Human input required", { exact: true })
        .waitFor({ timeout: 30000 });
      assert.equal(
        await owner
          .getByRole("button", { name: "Approve", exact: true })
          .isDisabled(),
        true,
      );
      const graphLogs = await exec("docker", ["logs", graphContainer], {
        timeout: 15000,
        maxBuffer: 2 * 1024 * 1024,
      });
      const changes = graphLogs.stdout
        .split("\n")
        .filter(
          (line) => line.startsWith("PROBE_TOOL ") && line.includes(marker),
        );
      assert.equal(changes.length, 1);
      await owner.screenshot({
        path: path.join(output, `${failoverStage}-loss-desktop.png`),
      });
      await peer.screenshot({
        path: path.join(output, `${failoverStage}-loss-mobile.png`),
      });
      return {
        taskID,
        approvalUID,
        marker,
        generatedText: undefined,
        expectedStatus: "InternalBotRunStatus.Uncertain",
      };
    }
  }
  const result =
    failoverStage === "socket-reconnect"
      ? await (async () => {
          await owner.waitForFunction(
            (id) =>
              window.__editorAIFrames.some(
                (frame) =>
                  frame.direction === "in" &&
                  frame.event === "board:editor:ai:status:result" &&
                  frame.data.task_id === id &&
                  frame.data.status === "completed",
              ),
            taskID,
            { timeout: 120000 },
          );
          return owner.evaluate(
            (id) =>
              window.__editorAIFrames.findLast(
                (frame) =>
                  frame.direction === "in" &&
                  frame.event === "board:editor:ai:status:result" &&
                  frame.data.task_id === id &&
                  frame.data.status === "completed",
              ).data,
            taskID,
          );
        })()
      : await (async () => {
          await owner.waitForFunction(
            (id) =>
              window.__editorAIFrames.some(
                (frame) =>
                  frame.direction === "in" &&
                  frame.event === "board:editor:approval:resume:result" &&
                  frame.data.approval_uid === id,
              ),
            approvalUID,
            { timeout: 120000 },
          );
          return owner.evaluate(
            (id) =>
              window.__editorAIFrames.find(
                (frame) =>
                  frame.direction === "in" &&
                  frame.event === "board:editor:approval:resume:result" &&
                  frame.data.approval_uid === id,
              ).data,
            approvalUID,
          );
        })();
  assert.equal(result.status, "completed");
  await owner
    .getByText("Human input required", { exact: true })
    .waitFor({ state: "hidden", timeout: 30000 });

  if (scenario === "approve") {
    await assertDraftPatch(owner, marker);
    await assertDraftPatch(peer, marker);
    const preparation = await owner.evaluate(() =>
      window.__richPatchFrames.find(
        (frame) =>
          frame.direction === "out" && frame.type === "rich_patch_prepared",
      ),
    );
    assert.ok(preparation, "The owner must prepare an immutable update");
    const peerPreparation = await peer.evaluate(() =>
      window.__richPatchFrames.find(
        (frame) =>
          frame.direction === "out" && frame.type === "rich_patch_prepared",
      ),
    );
    assert.equal(
      peerPreparation?.request_id,
      preparation.request_id,
      "Both editors must respond to the same owner request",
    );
  }

  await owner.evaluate(() => {
    const { event, topic, topic_id, data } = window.__editorAIFrames.find(
      (frame) =>
        frame.direction === "out" &&
        frame.event === "board:editor:approval:resume",
    );
    const socket = window.__editorAISockets.findLast(
      (candidate) => candidate.readyState === WebSocket.OPEN,
    );
    if (!socket) throw new Error("The editor socket is disconnected");
    socket.send(JSON.stringify({ event, topic, topic_id, data }));
  });
  await owner.waitForFunction(
    (id) =>
      window.__editorAIFrames.some(
        (frame) =>
          frame.direction === "in" &&
          frame.event === "board:editor:approval:resume:result" &&
          frame.data.approval_uid === id &&
          frame.data.status === "claim_failed",
      ),
    approvalUID,
    { timeout: 30000 },
  );

  const graphLogs = await exec("docker", ["logs", graphContainer], {
    timeout: 15000,
    maxBuffer: 2 * 1024 * 1024,
  });
  const changes = graphLogs.stdout
    .split("\n")
    .filter((line) => line.startsWith("PROBE_TOOL ") && line.includes(marker));
  assert.equal(changes.length, scenario === "approve" ? 1 : 0);
  if (scenario === "approve") {
    await owner.getByRole("button", { name: "Save", exact: true }).click();
    await owner
      .getByRole("button", { name: "Edit", exact: true })
      .waitFor({ timeout: 30000 });
  }
  return { taskID, approvalUID, marker, generatedText: undefined };
}

async function runRevocation(owner, peer, peerEditor, credentials) {
  const marker = `Editor revocation blocked ${runId} ${Date.now()}`;
  await peerEditor.click();
  await peerEditor.press("Control+End");
  await peerEditor.press("Control+j");
  const input = peer.getByPlaceholder("Ask AI anything...");
  await input.fill(
    `Use change_card_details to set only the description of card ${credentials.card_uid} in project ${credentials.project_uid} to exactly "${marker}". Keep the title unchanged. Call the tool once and report its result; do not just write suggested prose.`,
  );
  await input.press("Enter");
  stage = "revocation-approval-requested";
  await peer.waitForFunction(
    () =>
      window.__editorAIFrames.some(
        (frame) =>
          frame.direction === "out" && frame.event.endsWith(":chat:send"),
      ),
    null,
    { timeout: 30000 },
  );
  const taskID = await peer.evaluate(
    () =>
      window.__editorAIFrames.find(
        (frame) =>
          frame.direction === "out" && frame.event.endsWith(":chat:send"),
      ).data.task_id,
  );
  await owner
    .getByText("Human input required", { exact: true })
    .waitFor({ timeout: 120000 });
  assert.equal(
    await peer.getByRole("button", { name: "Approve", exact: true }).count(),
    0,
  );
  const awaiting = await snapshot();
  const awaitingRun = awaiting.runs.find(
    (item) => item.client_task_id === taskID,
  );
  assert.equal(awaitingRun?.status, "InternalBotRunStatus.AwaitingApproval");
  assert.ok(!JSON.stringify(awaiting.description).includes(marker));

  stage = "revocation-resuming";
  await owner.getByRole("button", { name: "Approve", exact: true }).click();
  await owner.waitForFunction(
    () =>
      window.__editorAIFrames.some(
        (frame) =>
          frame.direction === "out" &&
          frame.event === "board:editor:approval:resume",
      ),
    null,
    { timeout: 10000 },
  );
  const approvalUID = await owner.evaluate(
    () =>
      window.__editorAIFrames.find(
        (frame) =>
          frame.direction === "out" &&
          frame.event === "board:editor:approval:resume",
      ).data.approval_uid,
  );
  await waitForGraphBarrier("/tmp/phoenix-held-before-tool");
  const resuming = await snapshot();
  assert.equal(
    resuming.runs.find((item) => item.client_task_id === taskID)?.status,
    "InternalBotRunStatus.Resuming",
  );
  assert.ok(!JSON.stringify(resuming.description).includes(marker));

  stage = "revoking-editor-scope";
  const response = await fetch(
    `${apiOrigin}/board/${credentials.project_uid}/unassign/${credentials.users[1].uid}`,
    {
      method: "DELETE",
      headers: {
        Authorization: `Bearer ${credentials.users[0].access_token}`,
        Cookie: `${credentials.refresh_cookie_name}=${credentials.users[0].refresh_token}`,
      },
    },
  );
  assert.equal(
    response.ok,
    true,
    `Project member revocation failed with ${response.status}: ${await response.text()}`,
  );
  await peer.waitForFunction(
    (uid) =>
      window.__socketFrames.some(
        (frame) =>
          frame.event === "subscription:revoked" &&
          frame.topic === "board" &&
          frame.topic_id === uid,
      ),
    credentials.project_uid,
    { timeout: 30000 },
  );
  await peer.waitForFunction(
    (uid) => !window.location.pathname.startsWith(`/board/${uid}`),
    credentials.project_uid,
    { timeout: 30000 },
  );
  const failed = await waitForRunStatus(taskID, "InternalBotRunStatus.Failed");
  const failedRun = failed.runs.find((item) => item.client_task_id === taskID);
  assert.equal(failedRun?.error_message, "Editor AI scope access was revoked");
  assert.ok(!JSON.stringify(failed.description).includes(marker));
  await owner.waitForFunction(
    (id) =>
      window.__editorAIFrames.some(
        (frame) =>
          frame.direction === "in" &&
          frame.event === "board:editor:approval:resume:result" &&
          frame.data.approval_uid === id &&
          frame.data.status === "result_unknown",
      ),
    approvalUID,
    { timeout: 30000 },
  );
  await new Promise((resolve) => setTimeout(resolve, 1000));
  assert.equal(await graphToolCallCount(marker), 0);
  await owner
    .getByText("Human input required", { exact: true })
    .waitFor({ state: "hidden", timeout: 30000 });
  assert.ok(
    new URL(owner.url()).pathname.startsWith(
      `/board/${credentials.project_uid}`,
    ),
  );
  assert.ok(
    await owner.evaluate(() =>
      window.__editorAISockets.some(
        (socket) => socket.readyState === WebSocket.OPEN,
      ),
    ),
  );
  await owner.screenshot({
    path: path.join(output, "revocation-owner-desktop.png"),
  });
  await peer.screenshot({
    path: path.join(output, "revocation-peer-mobile.png"),
  });
  return {
    taskID,
    approvalUID,
    marker,
    generatedText: undefined,
    expectedStatus: "InternalBotRunStatus.Failed",
  };
}

async function runCancellation(
  foreignUser,
  runOwner,
  runOwnerEditor,
  credentials,
) {
  const marker = `Editor cancellation ownership ${runId} ${Date.now()}`;
  await runOwnerEditor.click();
  await runOwnerEditor.press("Control+End");
  await runOwnerEditor.press("Control+j");
  const input = runOwner.getByPlaceholder("Ask AI anything...");
  await input.fill(
    `Keep processing this request until it is cancelled: ${marker}`,
  );
  await input.press("Enter");
  stage = "cancellation-running";
  await runOwner.waitForFunction(
    () =>
      window.__editorAIFrames.some(
        (frame) =>
          frame.direction === "out" && frame.event.endsWith(":chat:send"),
      ),
    null,
    { timeout: 30000 },
  );
  const request = await runOwner.evaluate(() => {
    const frame = window.__editorAIFrames.find(
      (candidate) =>
        candidate.direction === "out" && candidate.event.endsWith(":chat:send"),
    );
    return {
      event: frame.event,
      topic: frame.topic,
      topic_id: frame.topic_id,
      taskID: frame.data.task_id,
    };
  });
  await waitForGraphBarrier("/tmp/phoenix-held-editor-model");
  const running = await snapshot();
  assert.equal(
    running.runs.find((item) => item.client_task_id === request.taskID)?.status,
    "InternalBotRunStatus.Streaming",
  );

  stage = "foreign-cancellation";
  await foreignUser.evaluate(
    ({ frame, projectUID }) => {
      const socket = window.__editorAISockets.findLast(
        (candidate) => candidate.readyState === WebSocket.OPEN,
      );
      if (!socket) throw new Error("The peer editor socket is disconnected");
      socket.send(
        JSON.stringify({
          event: frame.event.replace(/:send$/, ":abort"),
          topic: frame.topic,
          topic_id: frame.topic_id,
          data: { task_id: frame.taskID, project_uid: projectUID },
        }),
      );
    },
    { frame: request, projectUID: credentials.project_uid },
  );
  await foreignUser.waitForFunction(
    (id) =>
      window.__editorAIFrames.some(
        (frame) =>
          frame.direction === "in" &&
          frame.event === "board:editor:ai:status:result" &&
          frame.data.task_id === id &&
          frame.data.status === "error" &&
          frame.data.error_code === "conflict",
      ),
    request.taskID,
    { timeout: 30000 },
  );
  const afterForeignAttempt = await snapshot();
  assert.equal(
    afterForeignAttempt.runs.find(
      (item) => item.client_task_id === request.taskID,
    )?.status,
    "InternalBotRunStatus.Streaming",
  );
  assert.equal(await graphToolCallCount(marker), 0);

  stage = "owner-cancellation";
  const stop = runOwner.getByRole("button", { name: /^Stop/ });
  await stop.waitFor({ timeout: 30000 });
  await stop.tap();
  await runOwner.waitForFunction(
    (id) =>
      window.__editorAIFrames.some(
        (frame) =>
          frame.direction === "out" &&
          frame.event.endsWith(":chat:abort") &&
          frame.data.task_id === id,
      ),
    request.taskID,
    { timeout: 10000 },
  );
  await waitForRunStatus(request.taskID, "InternalBotRunStatus.Cancelled");
  await runOwner.waitForFunction(
    () =>
      Object.keys(window.sessionStorage).every(
        (key) =>
          !key.startsWith("langboard:editor-ai-run:") &&
          !key.startsWith("langboard:editor-ai-cancel:"),
      ),
    null,
    { timeout: 30000 },
  );
  await stop.waitFor({ state: "hidden", timeout: 30000 });
  await exec("docker", [
    "exec",
    graphContainer,
    "touch",
    "/tmp/phoenix-release-editor-model",
  ]);
  await new Promise((resolve) => setTimeout(resolve, 1000));
  const settled = await snapshot();
  assert.equal(
    settled.runs.find((item) => item.client_task_id === request.taskID)?.status,
    "InternalBotRunStatus.Cancelled",
  );
  assert.equal(await graphToolCallCount(marker), 0);

  await foreignUser.reload({ waitUntil: "domcontentloaded" });
  await runOwner.reload({ waitUntil: "domcontentloaded" });
  await Promise.all(
    [foreignUser, runOwner].map((page) =>
      page
        .getByRole("button", { name: "Edit", exact: true })
        .waitFor({ timeout: 30000 }),
    ),
  );
  await foreignUser.screenshot({
    path: path.join(output, "cancelled-foreign-admin-desktop.png"),
  });
  await runOwner.screenshot({
    path: path.join(output, "cancelled-run-owner-mobile.png"),
  });
  return {
    taskID: request.taskID,
    approvalUID: undefined,
    marker,
    generatedText: undefined,
    expectedStatus: "InternalBotRunStatus.Cancelled",
  };
}

async function waitForEditorText(page, expected) {
  await page.waitForFunction(
    (text) =>
      document
        .querySelector('[data-card-description] [contenteditable="true"]')
        ?.innerText.trim() === text,
    expected,
    { timeout: 30000 },
  );
}

async function appendEditorText(page, text) {
  const editor = page.locator(
    '[data-card-description] [contenteditable="true"]',
  );
  if (page.viewportSize().width < 600) await editor.tap();
  else await editor.click();
  await editor.press("Control+End");
  await page.keyboard.type(text);
}

async function assertMalformedEditorFrameRejected(page) {
  const closeCode = await page.evaluate(
    () =>
      new Promise((resolve, reject) => {
        const source = window.__editorSyncSockets.findLast(
          (socket) => socket.readyState === WebSocket.OPEN,
        );
        if (!source) {
          reject(new Error("No authenticated Editor sync socket is open"));
          return;
        }

        const socket = source.protocol
          ? new WebSocket(source.url, source.protocol)
          : new WebSocket(source.url);
        const timeout = setTimeout(() => {
          socket.close();
          reject(new Error("Malformed Editor sync socket did not close"));
        }, 30000);
        socket.addEventListener("open", () => socket.send(Uint8Array.of(0x80)));
        socket.addEventListener("close", (event) => {
          clearTimeout(timeout);
          resolve(event.code);
        });
        socket.addEventListener("error", () => {
          if (socket.readyState !== WebSocket.CLOSED) return;
          clearTimeout(timeout);
          reject(
            new Error("Malformed Editor sync socket failed without close"),
          );
        });
      }),
  );
  assert.equal(closeCode, 1007);
}

async function runEditorSyncReconnect(owner, peer, credentials) {
  let expected = `Editor sync ${runId}`;
  const ownerEditor = owner.locator(
    '[data-card-description] [contenteditable="true"]',
  );
  await ownerEditor.click();
  await ownerEditor.press("Control+End");
  await owner.keyboard.type(expected);
  await Promise.all(
    [owner, peer].map((page) => waitForEditorText(page, expected)),
  );

  for (let round = 1; round <= reconnectRounds; ++round) {
    stage = `editor-sync-reconnect-${round}`;
    await waitForPhoenixBrowserFailover(credentials.project_uid, round);
    await Promise.all(
      [owner, peer].map((page) => waitForEditorText(page, expected)),
    );

    const writer = round % 2 === 1 ? owner : peer;
    const addition = ` round-${round}`;
    await appendEditorText(writer, addition);
    expected += addition;
    await Promise.all(
      [owner, peer].map((page) => waitForEditorText(page, expected)),
    );
  }

  stage = "malformed-editor-frame";
  await assertMalformedEditorFrameRejected(owner);
  const postMalformedAddition = " malformed-frame-isolated";
  await appendEditorText(peer, postMalformedAddition);
  expected += postMalformedAddition;
  await Promise.all(
    [owner, peer].map((page) => waitForEditorText(page, expected)),
  );

  stage = "editor-sync-save";
  await owner.getByRole("button", { name: "Save", exact: true }).click();
  await owner
    .getByRole("button", { name: "Edit", exact: true })
    .waitFor({ timeout: 30000 });
  const persisted = await snapshot();
  assert.equal(persisted.description.content.trim(), expected);

  for (const page of [owner, peer]) {
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      (text) =>
        document.querySelector("[data-card-description]")?.innerText.trim() ===
        text,
      expected,
      { timeout: 30000 },
    );
  }
  await owner.screenshot({
    path: path.join(output, "sync-reconnect-desktop.png"),
  });
  await peer.screenshot({
    path: path.join(output, "sync-reconnect-mobile.png"),
  });
  assert.deepEqual(errors, []);
  await fs.writeFile(
    path.join(output, "result.json"),
    JSON.stringify(
      {
        scenario,
        rounds: reconnectRounds,
        errors,
        expectedDisconnectErrors,
        checks: [
          "two-distinct-users",
          "desktop-mobile",
          "json-socket-reconnect",
          "editor-sync-reconnect",
          "subscription-restore",
          "alternating-writes-converged-after-each-round",
          "malformed-live-frame-closed-with-1007",
          "malformed-frame-isolated-from-active-editors",
          "saved-description-persisted",
          "desktop-mobile-reload",
        ],
      },
      null,
      2,
    ),
  );
  process.stdout.write(`${output}\n`);
}

async function assertDraftPatch(page, marker) {
  await page.waitForFunction(
    (text) =>
      document
        .querySelector('[data-card-description] [contenteditable="true"]')
        ?.textContent.includes(text),
    marker,
    { timeout: 30000 },
  );
  assert.equal(
    (
      await page
        .locator('[data-card-description] [contenteditable="true"]')
        .innerText()
    ).trim(),
    marker,
    "The draft patch must be applied exactly once",
  );
}

async function main() {
  await fs.mkdir(output, { recursive: true });
  const credentials = await runDiagnostic(fixturePath, "credentials", runId);
  browser = await chromium.launch({
    headless: true,
    channel: "chrome",
    args: ["--disable-features=LocalNetworkAccessChecks"],
  });
  const owner = await createPage(credentials, 0);
  const peer = await createPage(credentials, 1);
  const url = `${origin}/board/${credentials.project_uid}/${credentials.card_uid}`;
  const ownerEditor = await openEditor(owner, url, credentials.project_uid);
  const peerEditor = await openEditor(peer, url, credentials.project_uid);
  if (scenario === "sync") {
    await runEditorSyncReconnect(owner, peer, credentials);
    return;
  }
  await ownerEditor.click();
  await ownerEditor.press("Control+End");

  const execution =
    scenario === "copilot"
      ? await runCopilot(owner, peer, ownerEditor, credentials)
      : scenario === "revocation"
        ? await runRevocation(owner, peer, peerEditor, credentials)
        : scenario === "cancel"
          ? await runCancellation(owner, peer, peerEditor, credentials)
          : await runApproval(owner, peer, ownerEditor, credentials);

  stage = "persisted";
  const persisted = await snapshot();
  const run = persisted.runs.find(
    (item) => item.client_task_id === execution.taskID,
  );
  assert.equal(
    run?.status,
    execution.expectedStatus || "InternalBotRunStatus.Completed",
  );
  assert.equal(
    persisted.runs.filter((item) => item.client_task_id === execution.taskID)
      .length,
    1,
  );
  if (scenario === "copilot") {
    assert.ok(
      JSON.stringify(persisted.description).includes(
        execution.generatedText.trim(),
      ),
    );
  } else if (scenario !== "cancel") {
    const approvals = persisted.approvals.filter(
      (item) => item.thread_id === run.graph_thread_id,
    );
    assert.equal(approvals.length, 1);
    const expectedApprovalStatus =
      scenario === "revocation"
        ? "GraphApprovalStatus.Expired"
        : ["resume", "worker"].includes(failoverStage)
          ? "GraphApprovalStatus.Pending"
          : scenario === "approve"
            ? "GraphApprovalStatus.Approved"
            : "GraphApprovalStatus.Rejected";
    assert.equal(approvals[0].status, expectedApprovalStatus);
    assert.equal(
      JSON.stringify(persisted.description).includes(execution.marker),
      scenario === "approve",
    );
    if (scenario === "approve")
      assert.equal(persisted.description.content.trim(), execution.marker);
    assert.equal(run.attempt, 2);
  }

  if (scenario !== "revocation" && scenario !== "cancel") {
    await peer.reload({ waitUntil: "domcontentloaded" });
    await peer
      .getByRole("button", { name: "Edit", exact: true })
      .waitFor({ timeout: 30000 });
  }
  if (
    scenario !== "reject" &&
    scenario !== "revocation" &&
    scenario !== "cancel"
  ) {
    const expected =
      scenario === "approve"
        ? execution.marker
        : execution.generatedText.trim();
    assert.ok(
      (await peer.locator("[data-card-description]").innerText()).includes(
        expected,
      ),
    );
  }
  await owner.screenshot({ path: path.join(output, "final-desktop.png") });
  await peer.screenshot({ path: path.join(output, "final-mobile.png") });
  await fs.writeFile(
    path.join(output, "rich-patch-frames.json"),
    JSON.stringify(
      await Promise.all(
        pages.map((page) => page.evaluate(() => window.__richPatchFrames)),
      ),
      null,
      2,
    ),
  );
  assert.deepEqual(errors, []);
  await fs.writeFile(
    path.join(output, "result.json"),
    JSON.stringify(
      {
        scenario,
        taskID: execution.taskID,
        approvalUID: execution.approvalUID,
        status: run.status,
        attempt: run.attempt,
        errors,
        expectedDisconnectErrors,
        checks: [
          "actual-editor-request",
          "real-graph-runtime",
          "deterministic-diagnostic-model",
          "two-distinct-users",
          "desktop-mobile",
          "persisted-state",
          ...(scenario === "revocation" ? [] : ["peer-reload"]),
          ...(failoverStage === "socket-reconnect"
            ? [
                "accepted-rich-patch-before-socket-loss",
                "json-socket-close",
                "socket-reconnect",
                "subscription-restore",
                "durable-run-status-reconciliation",
                "recovered-draft-save",
                "one-graph-tool-call",
              ]
            : failoverStage === "resume"
              ? [
                  "accepted-rich-patch-before-node-loss",
                  "shared-editor-storage-recovery",
                  "socket-reconnect",
                  "subscription-restore",
                  "claimed-approval-non-actionable",
                  "uncertain-recovery",
                  "recovered-draft-save",
                  "one-graph-tool-call",
                ]
              : failoverStage === "worker"
                ? [
                    "accepted-rich-patch-before-worker-loss",
                    "socket-session-preserved",
                    "subscription-preserved",
                    "claimed-approval-non-actionable",
                    "uncertain-recovery",
                    "recovered-draft-save",
                    "one-graph-tool-call",
                  ]
                : []),
          ...(scenario === "cancel"
            ? [
                "streaming-run-before-cancel",
                "foreign-cancel-rejected",
                "owner-run-preserved-after-foreign-cancel",
                "owner-stop-control",
                "cancelled-run-persisted",
                "cancellation-storage-cleared",
                "zero-graph-tool-calls",
                "cancelled-state-after-reload",
              ]
            : scenario === "revocation"
              ? [
                  "approval-before-mutation",
                  "approval-role-isolation",
                  "resume-lease-authorization-recheck",
                  "revoked-subscription-closed",
                  "owner-session-preserved",
                  "failed-run-persisted",
                  "approval-expired",
                  "zero-graph-tool-calls",
                  "realtime-banner-removal",
                ]
              : scenario === "copilot"
                ? [
                    "rendered-suggestion",
                    "no-repeated-input-prefix",
                    "tab-accept",
                    "realtime-peer-content",
                  ]
                : ["resume", "worker"].includes(failoverStage)
                  ? [
                      "approval-before-mutation",
                      "approval-role-isolation",
                      "approval-reload",
                      "approve-resume-claimed",
                      "one-run-one-approval",
                      "graph-tool-call-count",
                    ]
                  : [
                      "approval-before-mutation",
                      "approval-role-isolation",
                      "approval-reload",
                      `${scenario}-resume`,
                      "one-run-one-approval",
                      "realtime-banner-removal",
                      "duplicate-resume-rejected",
                      "graph-tool-call-count",
                    ]),
        ],
      },
      null,
      2,
    ),
  );
  process.stdout.write(`${output}\n`);
}

main()
  .catch(async (error) => {
    await fs.mkdir(output, { recursive: true });
    await fs.writeFile(
      path.join(output, "failure.json"),
      JSON.stringify(
        {
          scenario,
          stage,
          error: redact(error.stack),
          errors,
          expectedDisconnectErrors,
          frames: await Promise.all(
            pages.map((page) =>
              page.evaluate(() => window.__editorAIFrames).catch(() => []),
            ),
          ),
          socketFrames: await Promise.all(
            pages.map((page) =>
              page.evaluate(() => window.__socketFrames).catch(() => []),
            ),
          ),
        },
        null,
        2,
      ),
    );
    for (const [index, page] of pages.entries()) {
      await fs.writeFile(
        path.join(output, `activation-${index}.json`),
        JSON.stringify(
          await page.evaluate(() => window.__editorActivation),
          null,
          2,
        ),
      );
      await fs.writeFile(
        path.join(output, `rich-patch-frames-${index}.json`),
        JSON.stringify(
          await page.evaluate(() => window.__richPatchFrames),
          null,
          2,
        ),
      );
      await page
        .screenshot({ path: path.join(output, `failure-${index}.png`) })
        .catch(() => {});
      await fs.writeFile(
        path.join(output, `body-${index}.txt`),
        await page
          .locator("body")
          .innerText()
          .catch(() => ""),
      );
    }
    process.stderr.write(`${output}: ${redact(error.message)}\n`);
    process.exitCode = 1;
  })
  .finally(async () => {
    if (browser) await browser.close();
  });
