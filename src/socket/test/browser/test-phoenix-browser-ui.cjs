const assert = require("node:assert/strict");
const { createHash, randomUUID } = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { chromium } = require(
  process.env.PLAYWRIGHT_MODULE_PATH || "playwright",
);
const exec = promisify(execFile);
const runId = process.env.BOARD_CHAT_RUN_ID;
const race = process.env.BOARD_CHAT_RACE;
const failoverStage = process.env.PHOENIX_BROWSER_FAILOVER_STAGE || "connected";
const reconnectRounds = Number.parseInt(
  process.env.PHOENIX_BROWSER_RECONNECT_ROUNDS || "1",
  10,
);
const apiContainer = process.env.PHOENIX_BROWSER_API_CONTAINER;
const runtimeApiContainer = process.env.PHOENIX_BROWSER_RUNTIME_API_CONTAINER;
const fixturePath = process.env.PHOENIX_BROWSER_FIXTURE_PATH;
const inspectPath = process.env.PHOENIX_BROWSER_INSPECT_PATH;
const graphContainer = process.env.PHOENIX_BROWSER_GRAPH_CONTAINER;
const dockerNetwork = process.env.PHOENIX_BROWSER_DOCKER_NETWORK;
const socketPort = process.env.PHOENIX_BROWSER_PROXY_PORT;
const attachmentProbe = process.env.PHOENIX_BROWSER_ATTACHMENT_PROBE === "true";
const maxFileSizeMb = Number.parseInt(
  process.env.PHOENIX_BROWSER_MAX_FILE_SIZE_MB || "",
  10,
);
assert.ok(!race || ["approve", "reject"].includes(race));
assert.ok(
  [
    "connected",
    "canary",
    "card-context",
    "cancel",
    "mobile-comments",
    "concurrent-ui",
    "repeated",
    "resume",
    "accepted-api-outage",
  ].includes(failoverStage),
);
assert.ok(
  Number.isInteger(reconnectRounds) &&
    reconnectRounds > 0 &&
    reconnectRounds <= 20,
  "PHOENIX_BROWSER_RECONNECT_ROUNDS must be between 1 and 20",
);
assert.match(runId || "", /^[0-9a-f-]{36}$/);
assert.ok(
  Number.isInteger(maxFileSizeMb) && maxFileSizeMb > 0,
  "PHOENIX_BROWSER_MAX_FILE_SIZE_MB must be a positive integer",
);
assert.ok(
  apiContainer &&
    runtimeApiContainer &&
    fixturePath &&
    inspectPath &&
    graphContainer &&
    dockerNetwork,
);
assert.match(socketPort || "", /^[0-9]+$/);
const origin = process.env.PHOENIX_BROWSER_UI_ORIGIN || "http://127.0.0.1:1100";
const apiOrigin = process.env.PHOENIX_BROWSER_API_ORIGIN;
assert.ok(apiOrigin, "PHOENIX_BROWSER_API_ORIGIN is required");
const uiBuild = path.resolve(process.env.BOARD_CHAT_UI_BUILD || "");
assert.ok(process.env.BOARD_CHAT_UI_BUILD, "BOARD_CHAT_UI_BUILD is required");
const output = path.resolve("local/socket-migration", `board-chat-ui-${runId}`);
const errors = [];
const expectedOutageErrors = [];
const expectedUploadErrors = [];
const reconnectEvidence = [];
const steps = [];
const pages = [];
const browserSocketEvidence = [];
const diagnosticCommandTimeout = 180000;
let browser;
let apiOutageActive = false;
let notificationRefreshOutageActive = false;
let phoenixFailoverActive = false;
let uploadConcurrencyProbeActive = false;

function redact(value) {
  return String(value)
    .replace(/authorization=[^\s'"&]+/gi, "authorization=<redacted>")
    .replace(/Bearer\s+[^\s'"&]+/gi, "Bearer <redacted>");
}

async function snapshot() {
  const result = await exec(
    "docker",
    [
      "exec",
      apiContainer,
      "uv",
      "run",
      "--no-sync",
      "python",
      inspectPath,
      runId,
    ],
    { timeout: diagnosticCommandTimeout },
  );
  return JSON.parse(result.stdout.trim());
}

async function waitForRuntimeApi() {
  const deadline = Date.now() + 180000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${apiOrigin}/health`);
      if (response.ok) return;
    } catch {
      // The container can accept connections only after Uvicorn finishes starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  const [state, logs] = await Promise.all([
    exec("docker", [
      "inspect",
      "--format",
      "{{.State.Status}} {{.State.ExitCode}}",
      runtimeApiContainer,
    ]),
    exec("docker", ["logs", "--tail", "40", runtimeApiContainer]),
  ]);
  throw new Error(
    `The isolated browser API did not recover after restart: ${state.stdout.trim()}\n${logs.stdout}\n${logs.stderr}`,
  );
}

async function completedGraphRequestCount() {
  const logs = await exec("docker", ["logs", graphContainer], {
    maxBuffer: 8 * 1024 * 1024,
  });
  return logs.stdout
    .split("\n")
    .filter(
      (line) =>
        (line.includes("POST /api/v1/graph/run/") ||
          line.includes("POST /api/v1/graph/resume/")) &&
        line.includes('HTTP/1.1" 200 OK'),
    ).length;
}

async function waitForCompletedGraphRequest(previousCount) {
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    if ((await completedGraphRequestCount()) > previousCount) return;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("The held Graph request did not finish after release");
}

async function getLangflowFileState() {
  const code = [
    "import os",
    "import httpx",
    'response = httpx.get("http://127.0.0.1:5020/diagnostic/langflow/files", headers={"x-api-key": os.environ["PHOENIX_BROWSER_LANGFLOW_API_KEY"]}, timeout=5)',
    "response.raise_for_status()",
    "print(response.text)",
  ].join("; ");
  const result = await exec(
    "docker",
    ["exec", graphContainer, "uv", "run", "--no-sync", "python", "-c", code],
    { timeout: diagnosticCommandTimeout },
  );
  return JSON.parse(result.stdout.trim());
}

async function waitForLangflowFile(filename, deleted, timeout = 45000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const state = await getLangflowFileState();
    const record = state.files.find((value) => value.filename === filename);
    if (record?.deleted === deleted) return record;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(
    `Langflow attachment ${filename} did not reach deleted=${deleted}`,
  );
}

async function selectChatAttachment(page, filename, content) {
  const input = page.getByPlaceholder("Enter a message", { exact: true });
  const inputContainer = input.locator("xpath=..");
  let fileInput = inputContainer.locator('input[type="file"]');
  if ((await fileInput.count()) === 0) {
    await inputContainer.locator("button").first().click();
    fileInput = page.locator('input[type="file"]').last();
    await fileInput.waitFor({ state: "attached" });
  }
  await fileInput.setInputFiles(
    typeof content === "string"
      ? content
      : {
          name: filename,
          mimeType: "text/plain",
          buffer: content,
        },
  );
  await page.getByText(filename, { exact: true }).waitFor();
}

async function sendAttachment(page, filename, content, message) {
  const frameOffset = await page.evaluate(() => window.__chatFrames.length);
  const input = page.getByPlaceholder("Enter a message", { exact: true });
  await selectChatAttachment(page, filename, content);
  await input.fill(message);
  await input.press("Enter");
  await page.waitForFunction(
    (offset) =>
      window.__chatFrames
        .slice(offset)
        .some(
          (frame) =>
            frame.event === "outbound" &&
            frame.data?.event === "board:chat:send" &&
            typeof frame.data?.data?.file_token === "string" &&
            frame.data.data.file_token.length >= 32 &&
            frame.data.data.file_path === undefined,
        ),
    frameOffset,
    { timeout: 45000 },
  );
  await page.waitForFunction(
    () =>
      !document.querySelector('textarea[placeholder="Enter a message"]')
        ?.disabled,
    null,
    { timeout: 150000 },
  );
  return frameOffset;
}

async function assertLangflowAttachmentLifecycle(page) {
  const successfulFilename = `attachment-success-${runId}.txt`;
  const successfulContent = Buffer.alloc(maxFileSizeMb * 1024 * 1024, 0x61);
  const successfulPath = path.join(output, successfulFilename);
  const successfulHash = createHash("sha256")
    .update(successfulContent)
    .digest("hex");
  await fs.writeFile(successfulPath, successfulContent);
  let successOffset;
  try {
    successOffset = await sendAttachment(
      page,
      successfulFilename,
      successfulPath,
      `process:${runId}`,
    );
  } finally {
    await fs.rm(successfulPath, { force: true });
  }
  await page.waitForFunction(
    ({ offset, hash }) =>
      window.__chatFrames
        .slice(offset)
        .some(
          (frame) =>
            frame.event === "board:chat:stream:buffer" &&
            frame.data?.message?.content?.includes(hash),
        ),
    { offset: successOffset, hash: successfulHash },
    { timeout: 150000 },
  );
  const successfulRecord = await waitForLangflowFile(successfulFilename, false);
  assert.equal(successfulRecord.sha256, successfulHash);
  steps.push(
    "browser-uploaded-attachment-reached-langflow-and-streamed-through-phoenix",
  );
  steps.push("configured-maximum-size-browser-attachment-was-accepted");
  steps.push("completed-langflow-attachment-remained-available-for-history");

  const failedFilename = `attachment-failed-${runId}.txt`;
  const failedOffset = await sendAttachment(
    page,
    failedFilename,
    Buffer.from(`failed attachment ${runId}`),
    `fail:${runId}`,
  );
  await page.waitForFunction(
    (offset) =>
      window.__chatFrames
        .slice(offset)
        .some(
          (frame) =>
            frame.event === "board:chat:stream:end" &&
            frame.data?.status === "failed",
        ),
    failedOffset,
    { timeout: 150000 },
  );
  await waitForLangflowFile(failedFilename, true);
  steps.push("failed-langflow-run-deleted-its-external-attachment");
}

async function assertLangflowPartialCancel(page, credentials) {
  const filename = `attachment-partial-cancel-${runId}.txt`;
  const answer = "Partial Langflow answer";
  const offset = await page.evaluate(() => window.__chatFrames.length);
  await selectChatAttachment(page, filename, Buffer.from(`partial ${runId}`));
  const input = page.getByPlaceholder("Enter a message", { exact: true });
  await input.fill(`partial-hold:${runId}`);
  await input.press("Enter");
  await page.waitForFunction(
    ({ offset, answer }) =>
      window.__chatFrames
        .slice(offset)
        .some(
          (frame) =>
            frame.event === "board:chat:stream:buffer" &&
            frame.data?.message?.content === answer,
        ),
    { offset, answer },
    { timeout: 150000 },
  );
  const taskId = await page.evaluate(
    (offset) =>
      window.__chatFrames
        .slice(offset)
        .find(
          (frame) =>
            frame.event === "outbound" &&
            frame.data?.event === "board:chat:send",
        )?.data?.data?.task_id,
    offset,
  );
  assert.equal(typeof taskId, "string");
  const frames = await page.evaluate(
    (offset) =>
      window.__chatFrames
        .slice(offset)
        .filter((frame) => frame.event === "board:chat:stream:buffer")
        .map((frame) => frame.data?.message?.content),
    offset,
  );
  assert.deepEqual(frames, ["Draft ", "Draft Langflow answer", answer]);
  const before = await snapshot();
  assert.equal(before.runs.length, 1);
  assert.equal(before.runs[0].client_task_id, taskId);
  assert.equal(before.runs[0].status, "InternalBotRunStatus.Streaming");
  assert.equal(before.runs[0].output_text, answer);
  steps.push("visible-partial-answer-was-durable-before-cancel");

  await page
    .locator('textarea[placeholder="Enter a message"] ~ div button')
    .last()
    .click();
  await page.waitForFunction(
    (taskId) =>
      window.__chatFrames.some(
        (frame) =>
          frame.event === "task:aborted" && frame.data?.task_id === taskId,
      ),
    taskId,
    { timeout: 45000 },
  );
  const cancelled = await snapshot();
  assert.equal(cancelled.runs[0].status, "InternalBotRunStatus.Cancelled");
  assert.equal(cancelled.runs[0].output_text, answer);
  steps.push("cancellation-kept-the-durable-partial-answer");

  await page.reload({ waitUntil: "domcontentloaded" });
  await waitForBoardSocketReady(page, credentials.project_uid);
  await openBoardChat(page);
  await page.getByText(answer, { exact: true }).waitFor();
  steps.push("partial-answer-survived-browser-reload");
}

async function assertConcurrentUploadBound(owner, peer) {
  uploadConcurrencyProbeActive = true;
  const testPages = [owner, peer];
  await Promise.all(testPages.map((page) => openBoardChat(page)));
  await Promise.all(
    testPages.map((page, index) =>
      selectChatAttachment(
        page,
        `concurrency-hold-${runId}-${index}.bin`,
        Buffer.alloc(4 * 1024 * 1024),
      ),
    ),
  );
  const responses = testPages.map((page) =>
    page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname.endsWith("/chat/upload") &&
        [406, 503].includes(response.status()),
      { timeout: 45000 },
    ),
  );
  await Promise.all(
    testPages.map(async (page, index) => {
      const input = page.getByPlaceholder("Enter a message", { exact: true });
      await input.fill(`concurrency upload ${runId} ${index}`);
      await input.press("Enter");
    }),
  );
  const statuses = (await Promise.all(responses))
    .map((response) => response.status())
    .sort((left, right) => left - right);
  assert.deepEqual(statuses, [406, 503]);
  steps.push("concurrent-browser-uploads-enforced-the-api-worker-bound");
}

async function assertLangflowAttachmentProcessLoss(page) {
  const filename = `attachment-process-loss-${runId}.txt`;
  const frameOffset = await page.evaluate(() => window.__chatFrames.length);
  const input = page.getByPlaceholder("Enter a message", { exact: true });
  await selectChatAttachment(
    page,
    filename,
    Buffer.from(`process loss attachment ${runId}`),
  );
  await input.fill(`hold:${runId}`);
  await input.press("Enter");
  await page.waitForFunction(
    (offset) =>
      window.__chatFrames
        .slice(offset)
        .some((frame) => frame.event === "board:chat:stream:start"),
    frameOffset,
    { timeout: 150000 },
  );
  const clientTaskId = await page.evaluate((offset) => {
    const frame = window.__chatFrames
      .slice(offset)
      .find(
        (candidate) =>
          candidate.event === "outbound" &&
          candidate.data?.event === "board:chat:send",
      );
    return frame?.data?.data?.task_id;
  }, frameOffset);
  assert.equal(typeof clientTaskId, "string");
  await waitForLangflowFile(filename, false);

  const holdDeadline = Date.now() + 45000;
  let held = false;
  while (Date.now() < holdDeadline) {
    try {
      await exec("docker", [
        "exec",
        graphContainer,
        "test",
        "-f",
        "/tmp/phoenix-held-langflow",
      ]);
      held = true;
      break;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  assert.ok(
    held,
    "The Langflow attachment stream must be active before Phoenix process loss",
  );
  const beforeLoss = await snapshot();
  assert.equal(
    beforeLoss.runs.filter(
      (run) =>
        run.client_task_id === clientTaskId &&
        run.status === "InternalBotRunStatus.Streaming",
    ).length,
    1,
  );
  steps.push("attachment-run-was-durable-before-phoenix-process-loss");

  await waitForPhoenixBrowserFailover();
  await exec("docker", [
    "exec",
    apiContainer,
    "uv",
    "run",
    "--no-sync",
    "python",
    inspectPath,
    runId,
    "--expire-attachment",
    "--client-task-id",
    clientTaskId,
  ]);
  await exec("docker", [
    "network",
    "disconnect",
    dockerNetwork,
    graphContainer,
  ]);
  let storageReconnected = false;
  try {
    await exec("docker", [
      "exec",
      apiContainer,
      "/app/.venv/bin/langboard",
      "run:internal-bot-runs:recover",
    ]);
    const recovered = await snapshot();
    assert.equal(
      recovered.runs.filter(
        (run) =>
          run.client_task_id === clientTaskId &&
          run.status === "InternalBotRunStatus.Uncertain",
      ).length,
      1,
    );
    await new Promise((resolve) => setTimeout(resolve, 15000));
    await waitForLangflowFile(filename, false);
    steps.push(
      "external-storage-outage-preserved-the-durable-attachment-retry",
    );
    await exec("docker", ["network", "connect", dockerNetwork, graphContainer]);
    storageReconnected = true;
    await waitForLangflowFile(filename, true, 120000);
  } finally {
    if (!storageReconnected) {
      await exec("docker", [
        "network",
        "connect",
        dockerNetwork,
        graphContainer,
      ]).catch(() => undefined);
    }
  }
  steps.push(
    "process-loss-and-storage-outage-recovery-reclaimed-the-durable-external-attachment",
  );
}

async function openBoardChat(page) {
  const input = page.getByPlaceholder("Enter a message", { exact: true });
  const deadline = Date.now() + 30000;
  let lastError = "";

  while (Date.now() < deadline) {
    if (await input.isVisible()) return;

    try {
      const button = page.getByRole("button", {
        name: "Chat with AI",
        exact: true,
      });
      await button.waitFor({ timeout: 5000 });
      await button.click();
      await input.waitFor({ timeout: 5000 });
      return;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
      await page.waitForTimeout(250);
    }
  }

  throw new Error(`Board chat did not open: ${lastError}`);
}

async function assertApiOutageRejectsChatWithoutPersisting(page, credentials) {
  const before = await snapshot();
  const editorPages = [];
  for (const browserPage of pages) {
    if (
      await browserPage.evaluate(() =>
        window.__probeSockets.some(
          (socket) =>
            socket.readyState === WebSocket.OPEN &&
            new URL(socket.url).pathname === "/editor-sync",
        ),
      )
    )
      editorPages.push(browserPage);
  }
  assert.ok(
    editorPages.length > 0,
    "At least one browser must have an editor connection before the API outage",
  );
  const outageToast = page.getByText(
    "Server has been temporarily disabled. Please try again later.",
    { exact: true },
  );
  const baseline = await page.evaluate(
    (projectUID) => ({
      frameOffset: window.__chatFrames.length,
      subscriptions: window.__chatFrames.filter(
        (frame) =>
          frame.event === "subscribed" &&
          frame.topic === "board" &&
          frame.topic_id.includes(projectUID),
      ).length,
      availability: window.__chatFrames.filter(
        (frame) =>
          frame.event === "board:chat:available" &&
          frame.topic_id === projectUID &&
          frame.data?.available === true,
      ).length,
    }),
    credentials.project_uid,
  );
  apiOutageActive = true;
  await exec("docker", ["stop", "--time", "10", runtimeApiContainer], {
    timeout: diagnosticCommandTimeout,
  });

  try {
    const input = page.getByPlaceholder("Enter a message", { exact: true });
    await input.fill(`API outage probe ${runId}`);
    await input.press("Enter");
    await page.waitForFunction(
      (offset) =>
        window.__chatFrames
          .slice(offset)
          .some((frame) => frame.event === "close" && frame.code === 1011),
      baseline.frameOffset,
      { timeout: 45000 },
    );
    try {
      await outageToast.waitFor({ timeout: 45000 });
    } catch (error) {
      const state = await page.evaluate(
        (offset) => ({
          inputDisabled: document.querySelector(
            'textarea[placeholder="Enter a message"]',
          )?.disabled,
          frames: window.__chatFrames.slice(offset).map((frame) => ({
            event: frame.event,
            code: frame.code,
            topic: frame.topic,
            action: frame.data?.action,
          })),
        }),
        baseline.frameOffset,
      );
      throw new Error(
        `API outage had no visible error: ${JSON.stringify(state)}`,
        { cause: error },
      );
    }
  } finally {
    await exec("docker", ["start", runtimeApiContainer], {
      timeout: diagnosticCommandTimeout,
    });
    await waitForRuntimeApi();
  }

  await page.waitForFunction(
    ({ projectUID, subscriptions, availability }) =>
      window.__chatFrames.filter(
        (frame) =>
          frame.event === "subscribed" &&
          frame.topic === "board" &&
          frame.topic_id.includes(projectUID),
      ).length > subscriptions &&
      window.__chatFrames.filter(
        (frame) =>
          frame.event === "board:chat:available" &&
          frame.topic_id === projectUID &&
          frame.data?.available === true,
      ).length > availability,
    {
      projectUID: credentials.project_uid,
      subscriptions: baseline.subscriptions,
      availability: baseline.availability,
    },
    { timeout: 90000 },
  );
  await page.waitForFunction(
    () =>
      !document.querySelector('textarea[placeholder="Enter a message"]')
        ?.disabled,
    null,
    { timeout: 90000 },
  );
  assert.equal(
    await page.evaluate(
      ({ offset, projectUID }) =>
        window.__chatFrames
          .slice(offset)
          .filter(
            (frame) =>
              frame.event === "outbound" &&
              frame.data?.event === "subscribe" &&
              frame.data?.topic === "board" &&
              frame.data?.topic_id?.includes(projectUID),
          ).length,
      { offset: baseline.frameOffset, projectUID: credentials.project_uid },
    ),
    1,
    "API outage recovery must restore the board subscription once",
  );
  await Promise.all(
    editorPages.map((browserPage) =>
      browserPage.waitForFunction(
        () =>
          window.__probeSockets.some(
            (socket) =>
              socket.readyState === WebSocket.OPEN &&
              new URL(socket.url).pathname === "/editor-sync",
          ),
        null,
        { timeout: 90000 },
      ),
    ),
  );
  apiOutageActive = false;

  assert.deepEqual(
    await snapshot(),
    before,
    "A chat command rejected during API outage must not persist any state",
  );
  steps.push("api-outage-rejects-chat-with-zero-persisted-effects");
}

async function sendResume(page, command, expectedError) {
  const offset = await page.evaluate((data) => {
    const start = window.__chatFrames.length;
    const socket = window.__probeSockets.find(
      (socket) =>
        socket.readyState === 1 &&
        new URL(socket.url).port === window.__probeSocketPort,
    );
    if (!socket) throw new Error("Live Phoenix JSON socket not found");
    socket.send(JSON.stringify(data));
    return start;
  }, command);
  if (expectedError)
    await page.waitForFunction(
      ({ offset, code }) =>
        window.__chatFrames
          .slice(offset)
          .some((frame) => frame.data?.resume_error_code === code),
      { offset, code: expectedError },
    );
}

async function assertNonmemberChatAvailabilityDenied(
  page,
  accessToken,
  projectUID,
) {
  const result = await page.evaluate(
    ({ accessToken, projectUID }) =>
      new Promise((resolve, reject) => {
        const activeSocket = window.__probeSockets.find(
          (socket) =>
            socket.readyState === WebSocket.OPEN &&
            new URL(socket.url).port === window.__probeSocketPort,
        );
        if (!activeSocket) {
          reject(new Error("Live Phoenix JSON socket not found"));
          return;
        }

        const url = new URL(activeSocket.url);
        url.searchParams.set("authorization", accessToken);
        url.searchParams.delete("socket_route_key");
        const socket = new WebSocket(url);
        const timeout = window.setTimeout(() => {
          socket.close();
          reject(new Error("Nonmember availability probe timed out"));
        }, 15000);
        let subscriptionDenied = false;

        socket.addEventListener("open", () => {
          socket.send(
            JSON.stringify({
              event: "subscribe",
              topic: "board",
              topic_id: projectUID,
            }),
          );
        });
        socket.addEventListener("message", (event) => {
          if (typeof event.data !== "string" || !event.data) return;
          const frame = JSON.parse(event.data);
          if (frame.event !== "subscribed" || frame.topic !== "board") return;
          const accepted = Array.isArray(frame.topic_id) ? frame.topic_id : [];
          if (accepted.includes(projectUID)) {
            window.clearTimeout(timeout);
            socket.close();
            reject(new Error("Nonmember subscribed to the synthetic project"));
            return;
          }
          subscriptionDenied = true;
          socket.send(
            JSON.stringify({
              event: "board:chat:available",
              topic: "board",
              topic_id: projectUID,
              data: {},
            }),
          );
        });
        socket.addEventListener("close", (event) => {
          window.clearTimeout(timeout);
          resolve({ code: event.code, subscriptionDenied });
        });
        socket.addEventListener("error", () => {
          window.clearTimeout(timeout);
          reject(new Error("Nonmember availability socket failed"));
        });
      }),
    { accessToken, projectUID },
  );
  assert.deepEqual(result, { code: 3003, subscriptionDenied: true });
}

async function setPeerProjectRoles(owner, peer, credentials, roles) {
  const offsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  const response = await fetch(
    `${apiOrigin}/board/${credentials.project_uid}/settings/roles/user/${credentials.users[1].uid}`,
    {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${credentials.users[0].access_token}`,
        "Content-Type": "application/json",
        Cookie: `${credentials.refresh_cookie_name}=${credentials.users[0].refresh_token}`,
      },
      body: JSON.stringify({ roles }),
    },
  );
  assert.equal(
    response.ok,
    true,
    `Project role update failed with ${response.status}: ${await response.text()}`,
  );
  await owner.waitForFunction(
    ({ offset, projectUID, userUID, roles }) =>
      window.__chatFrames
        .slice(offset)
        .some(
          (frame) =>
            frame.event === `board:roles:user:updated:${projectUID}` &&
            frame.topic_id === projectUID &&
            frame.data?.user_uid === userUID &&
            JSON.stringify(frame.data.roles) === JSON.stringify(roles),
        ),
    {
      offset: offsets[0],
      projectUID: credentials.project_uid,
      userUID: credentials.users[1].uid,
      roles,
    },
  );
  await peer.waitForFunction(
    ({ offset, projectUID, roles }) =>
      window.__chatFrames
        .slice(offset)
        .some(
          (frame) =>
            frame.event === "user:project-roles:updated" &&
            frame.data?.project_uid === projectUID &&
            JSON.stringify(frame.data.roles) === JSON.stringify(roles),
        ),
    { offset: offsets[1], projectUID: credentials.project_uid, roles },
  );
}

async function openPeerCardDocument(peer, credentials) {
  await peer.goto(
    `${origin}/board/${credentials.project_uid}/${credentials.card_uid}`,
    { waitUntil: "domcontentloaded" },
  );
  await peer.getByText("No description", { exact: true }).waitFor();
  await peer.waitForFunction(
    () =>
      window.__probeSockets.some(
        (socket) =>
          socket.readyState === WebSocket.OPEN &&
          new URL(socket.url).pathname === "/editor-sync",
      ),
    null,
    { timeout: 90000 },
  );
}

async function sendEditorUpdateFromOpenConnection(peer, credentials) {
  return peer.evaluate(
    ({ cardUID, encodedUpdate }) => {
      const socket = window.__probeSockets.find(
        (candidate) =>
          candidate.readyState === WebSocket.OPEN &&
          new URL(candidate.url).pathname === "/editor-sync",
      );
      if (!socket) throw new Error("Live Phoenix editor socket not found");

      const encodeVarUint = (value) => {
        const bytes = [];
        let remaining = value;
        while (remaining > 127) {
          bytes.push((remaining & 127) | 128);
          remaining = Math.floor(remaining / 128);
        }
        bytes.push(remaining & 127);
        return bytes;
      };
      const name = new TextEncoder().encode(`card:${cardUID}:description`);
      const update = Uint8Array.from(atob(encodedUpdate), (char) =>
        char.charCodeAt(0),
      );
      const message = new Uint8Array([
        ...encodeVarUint(name.length),
        ...name,
        0,
        2,
        ...encodeVarUint(update.length),
        ...update,
      ]);
      const offset = window.__editorBinaryFrames.length;
      socket.send(message);
      return offset;
    },
    {
      cardUID: credentials.card_uid,
      encodedUpdate:
        "AQb4rNGRAQAEAQV0aXRsZQZCZWZvcmUHAQtkZXNjcmlwdGlvbgMBcAcA+KzRkQEGBgYA+KzRkQEHBGJvbGQEdHJ1ZYT4rNGRAQgEUmljaIb4rNGRAQwEYm9sZARudWxsAA==",
    },
  );
}

async function assertRoleDowngradeRejectsEditWithoutPersisting(
  owner,
  peer,
  credentials,
) {
  await setPeerProjectRoles(owner, peer, credentials, [
    "read",
    "card_update",
    "update",
  ]);
  await openPeerCardDocument(peer, credentials);
  const before = await snapshot();
  await setPeerProjectRoles(owner, peer, credentials, ["read"]);
  const editorFrameOffset = await sendEditorUpdateFromOpenConnection(
    peer,
    credentials,
  );
  await peer.waitForFunction(
    (offset) =>
      window.__editorBinaryFrames.slice(offset).some((frame) => {
        const length = frame.length;
        return (
          length >= 2 && frame[length - 2] === 8 && frame[length - 1] === 0
        );
      }),
    editorFrameOffset,
    { timeout: 30000 },
  );
  assert.deepEqual(
    await snapshot(),
    before,
    "A role-downgraded editor update must not persist a Card change",
  );
  await peer.reload({ waitUntil: "domcontentloaded" });
  await peer.getByText("No description", { exact: true }).waitFor();
  assert.equal(
    await peer.getByRole("button", { name: "Edit", exact: true }).count(),
    0,
    "A read-only member must not retain the Card edit action after reload",
  );
  steps.push(
    "live-role-downgrade-rejected-yjs-write-kept-read-sync-and-survived-reload",
  );
  await peer.goto(`${origin}/board/${credentials.project_uid}`, {
    waitUntil: "domcontentloaded",
  });
  await waitForBoardSocketReady(peer, credentials.project_uid);
  await openBoardChat(peer);
  await waitForBoardSocketReady(peer, credentials.project_uid);
  const taskId = randomUUID();
  const baseline = await peer.evaluate(
    ({ projectUID, taskId, runId }) => {
      const socket = window.__probeSockets.find(
        (candidate) =>
          candidate.readyState === WebSocket.OPEN &&
          new URL(candidate.url).port === window.__probeSocketPort,
      );
      if (!socket) throw new Error("Live Phoenix JSON socket not found");
      const offset = window.__chatFrames.length;
      const availability = window.__chatFrames.filter(
        (frame) =>
          frame.event === "board:chat:available" &&
          frame.topic_id === projectUID,
      ).length;
      socket.send(
        JSON.stringify({
          event: "board:chat:send",
          topic: "board",
          topic_id: projectUID,
          data: {
            task_id: taskId,
            message: `Denied role downgrade probe ${runId}`,
            scope_table: "project",
            api_permission_level: "edit",
          },
        }),
      );
      return { offset, availability };
    },
    { projectUID: credentials.project_uid, taskId, runId },
  );
  await peer.waitForFunction(
    ({ offset, taskId }) =>
      window.__chatFrames
        .slice(offset)
        .some(
          (frame) =>
            frame.event === "board:chat:send:failed" &&
            frame.data?.task_id === taskId &&
            frame.data?.already_started === false,
        ),
    { offset: baseline.offset, taskId },
    { timeout: 45000 },
  );
  assert.deepEqual(
    await snapshot(),
    before,
    "A role-downgraded edit command must not persist a message, run, approval, or Card change",
  );
  await peer.evaluate((projectUID) => {
    const socket = window.__probeSockets.find(
      (candidate) =>
        candidate.readyState === WebSocket.OPEN &&
        new URL(candidate.url).port === window.__probeSocketPort,
    );
    if (!socket) throw new Error("Live Phoenix JSON socket not found");
    socket.send(
      JSON.stringify({
        event: "board:chat:available",
        topic: "board",
        topic_id: projectUID,
        data: {},
      }),
    );
  }, credentials.project_uid);
  await peer.waitForFunction(
    ({ projectUID, availability }) =>
      window.__chatFrames.filter(
        (frame) =>
          frame.event === "board:chat:available" &&
          frame.topic_id === projectUID &&
          frame.data?.available === true,
      ).length > availability,
    {
      projectUID: credentials.project_uid,
      availability: baseline.availability,
    },
  );
  steps.push(
    "live-role-downgrade-rejected-edit-with-zero-persisted-effects-and-kept-read-access",
  );
  await setPeerProjectRoles(owner, peer, credentials, ["read", "card_update"]);
  steps.push("peer-role-restored-for-following-browser-scenarios");
}

async function assertRevokedMemberCannotResumeProjectAccess(
  owner,
  peer,
  credentials,
) {
  const projectTitle = `Migration editor access probe ${runId}`;
  const dashboardPeer = await peer.context().newPage();
  dashboardPeer.on("pageerror", (error) =>
    errors.push({ index: "peer-dashboard", message: error.message }),
  );
  dashboardPeer.on("console", (message) => {
    if (message.type() === "error")
      errors.push({ index: "peer-dashboard", message: redact(message.text()) });
  });
  dashboardPeer.on("response", (response) => {
    if (new URL(response.url()).port === "15694" && response.status() >= 400)
      errors.push({
        index: "peer-dashboard",
        path: new URL(response.url()).pathname,
        status: response.status(),
      });
  });
  await dashboardPeer.goto(`${origin}/dashboard/projects/all`, {
    waitUntil: "domcontentloaded",
  });
  await dashboardPeer
    .getByRole("heading", { name: projectTitle, exact: true })
    .waitFor();
  await dashboardPeer.waitForFunction(
    (uid) =>
      window.__chatFrames.some(
        (frame) =>
          frame.event === "subscribed" &&
          frame.topic === "dashboard" &&
          frame.topic_id.includes(uid),
      ),
    credentials.project_uid,
  );
  const dashboardOffset = await dashboardPeer.evaluate(
    () => window.__chatFrames.length,
  );
  const offsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
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
    ({ offset, uid }) =>
      window.__chatFrames
        .slice(offset)
        .some(
          (frame) =>
            frame.event === "subscription:revoked" &&
            frame.topic === "board" &&
            frame.topic_id === uid,
        ),
    { offset: offsets[1], uid: credentials.project_uid },
  );
  await peer.waitForFunction(
    (uid) => !window.location.pathname.startsWith(`/board/${uid}`),
    credentials.project_uid,
  );
  await peer
    .getByRole("heading", { name: projectTitle, exact: true })
    .waitFor({ state: "hidden" });
  await dashboardPeer.waitForFunction(
    ({ offset, uid }) =>
      window.__chatFrames
        .slice(offset)
        .some(
          (frame) =>
            frame.event === "subscription:revoked" &&
            frame.topic === "dashboard" &&
            frame.topic_id === uid,
        ),
    { offset: dashboardOffset, uid: credentials.project_uid },
  );
  await dashboardPeer
    .getByRole("heading", { name: projectTitle, exact: true })
    .waitFor({ state: "hidden" });
  await dashboardPeer.screenshot({
    path: path.join(output, "peer-dashboard-after-access-revocation.png"),
  });
  await dashboardPeer.close();
  steps.push("open-mobile-dashboard-lost-project-after-live-access-revocation");
  await owner.waitForFunction(
    ({ offset, uid }) =>
      window.__chatFrames
        .slice(offset)
        .some(
          (frame) =>
            frame.event === `board:assigned-users:updated:${uid}` &&
            frame.topic === "board" &&
            frame.topic_id === uid,
        ),
    { offset: offsets[0], uid: credentials.project_uid },
  );
  steps.push(
    "connected-peer-received-subscription-revocation-and-left-project",
  );

  const status = await exec(
    "docker",
    [
      "exec",
      apiContainer,
      "uv",
      "run",
      "--no-sync",
      "python",
      fixturePath,
      "status",
      runId,
    ],
    { timeout: diagnosticCommandTimeout },
  );
  assert.equal(JSON.parse(status.stdout.trim()).peer_assigned, false);

  await waitForBoardSocketReady(pages[0], credentials.project_uid);
  await assertNonmemberChatAvailabilityDenied(
    owner,
    credentials.users[1].access_token,
    credentials.project_uid,
  );
  assert.ok(
    new URL(owner.url()).pathname.startsWith(
      `/board/${credentials.project_uid}`,
    ),
  );
  steps.push("revoked-peer-could-not-resubscribe-or-run-chat-command");
  steps.push("owner-remained-connected-after-peer-revocation");

  await owner.screenshot({
    path: path.join(output, "owner-after-peer-revocation.png"),
  });
  await peer.screenshot({
    path: path.join(output, "peer-after-access-revocation.png"),
  });

  const restore = await exec(
    "docker",
    [
      "exec",
      apiContainer,
      "uv",
      "run",
      "--no-sync",
      "python",
      fixturePath,
      "restore",
      runId,
    ],
    { timeout: diagnosticCommandTimeout },
  );
  assert.deepEqual(JSON.parse(restore.stdout.trim()), { restored: true });
  await peer.goto(`${origin}/dashboard/projects/all`, {
    waitUntil: "domcontentloaded",
  });
  await peer
    .getByRole("heading", { name: projectTitle, exact: true })
    .waitFor();
  steps.push(
    "dashboard-project-disappeared-after-revocation-and-returned-after-restore",
  );
  await peer.goto(
    `${origin}/board/${credentials.project_uid}/${credentials.card_uid}`,
    { waitUntil: "domcontentloaded" },
  );
  await peer.waitForFunction(
    (uid) =>
      window.__chatFrames.some(
        (frame) =>
          frame.event === "subscribed" &&
          frame.topic === "board" &&
          frame.topic_id.includes(uid),
      ),
    credentials.project_uid,
  );
  await peer.waitForFunction(
    (uid) =>
      window.__chatFrames.some(
        (frame) =>
          frame.event === "board:chat:available" &&
          frame.topic_id === uid &&
          frame.data?.available === true,
      ),
    credentials.project_uid,
  );
  steps.push("revoked-peer-restored-for-following-browser-scenarios");
}

function observeBrowserSockets(page, projectUID) {
  const evidence = {
    json_connections: 0,
    open_json_sockets: 0,
    json_closes: 0,
    board_subscriptions: 0,
    chat_availability: 0,
    sockets: [],
  };
  page.on("websocket", (socket) => {
    if (new URL(socket.url()).pathname !== "/") return;
    const socketEvidence = {
      id: evidence.json_connections + 1,
      closed: false,
      board_subscriptions: 0,
      chat_availability: 0,
    };
    evidence.sockets.push(socketEvidence);
    evidence.json_connections += 1;
    evidence.open_json_sockets += 1;
    socket.on("framereceived", ({ payload }) => {
      const text =
        typeof payload === "string"
          ? payload
          : Buffer.isBuffer(payload)
            ? payload.toString("utf8")
            : "";
      if (!text.startsWith("{")) return;
      let frame;
      try {
        frame = JSON.parse(text);
      } catch {
        return;
      }
      if (
        frame.event === "subscribed" &&
        frame.topic === "board" &&
        frame.topic_id.includes(projectUID)
      ) {
        socketEvidence.board_subscriptions += 1;
        evidence.board_subscriptions += 1;
      }
      if (
        frame.event === "board:chat:available" &&
        frame.topic_id === projectUID &&
        frame.data?.available === true
      ) {
        socketEvidence.chat_availability += 1;
        evidence.chat_availability += 1;
      }
    });
    socket.on("close", () => {
      socketEvidence.closed = true;
      evidence.open_json_sockets -= 1;
      evidence.json_closes += 1;
    });
  });
  return evidence;
}

function snapshotBrowserSocketEvidence(index) {
  const evidence = browserSocketEvidence[index];
  return {
    ...evidence,
    sockets: evidence.sockets.map((socket) => ({ ...socket })),
  };
}

function latestActiveBoardSocketId(evidence) {
  for (let i = evidence.sockets.length - 1; i >= 0; --i) {
    const socket = evidence.sockets[i];
    if (
      !socket.closed &&
      socket.board_subscriptions > 0 &&
      socket.chat_availability > 0
    )
      return socket.id;
  }
  return undefined;
}

async function waitForBrowserSocketClose(index, baseline) {
  const socketId = latestActiveBoardSocketId(baseline);
  assert.notEqual(
    socketId,
    undefined,
    `Browser ${index} has no active Board socket`,
  );
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    const sockets = browserSocketEvidence[index].sockets;
    if (sockets.some((socket) => socket.id === socketId && socket.closed))
      return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Browser ${index} did not close its active Board socket`);
}

async function waitForBrowserSocketRecovery(
  index,
  baseline,
  requirePreviousClose = true,
) {
  const previousSocketIds = new Set(
    baseline.sockets.map((socket) => socket.id),
  );
  const activeSocketId = latestActiveBoardSocketId(baseline);
  assert.notEqual(
    activeSocketId,
    undefined,
    `Browser ${index} has no active Board socket`,
  );
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    const evidence = browserSocketEvidence[index];
    if (
      (!requirePreviousClose ||
        evidence.sockets.some(
          (socket) => socket.id === activeSocketId && socket.closed,
        )) &&
      evidence.sockets.some(
        (socket) =>
          !previousSocketIds.has(socket.id) &&
          !socket.closed &&
          socket.board_subscriptions > 0 &&
          socket.chat_availability > 0,
      )
    )
      return snapshotBrowserSocketEvidence(index);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Browser ${index} did not restore its Board socket state`);
}

async function waitForPhoenixBrowserFailoverRound(round) {
  const signalPath = process.env.PHOENIX_BROWSER_FAILOVER_SIGNAL;
  if (!signalPath) return;
  const signalSuffix = round === 1 ? "" : `.${round}`;
  const baseline = pages.map((_page, index) =>
    snapshotBrowserSocketEvidence(index),
  );
  const evidence = { round, baseline, pages: [], stage: "waiting-for-close" };
  if (failoverStage === "repeated") reconnectEvidence.push(evidence);
  phoenixFailoverActive = true;
  await fs.writeFile(
    `${signalPath}.ready${signalSuffix}`,
    JSON.stringify({ pages: pages.length, round }),
  );
  await Promise.all(
    pages.map((_page, index) =>
      waitForBrowserSocketClose(index, baseline[index]),
    ),
  );
  await fs.writeFile(
    `${signalPath}.disconnected${signalSuffix}`,
    JSON.stringify({ pages: pages.length, round }),
  );
  evidence.stage = "waiting-for-recovery";
  evidence.pages = await Promise.all(
    pages.map((_page, index) =>
      waitForBrowserSocketRecovery(index, baseline[index]),
    ),
  );
  evidence.stage = "recovered";
  return evidence;
}

async function waitForPhoenixBrowserFailover() {
  const signalPath = process.env.PHOENIX_BROWSER_FAILOVER_SIGNAL;
  if (!signalPath) return;
  const rounds = failoverStage === "repeated" ? reconnectRounds : 1;
  for (let round = 1; round <= rounds; ++round) {
    const evidence = await waitForPhoenixBrowserFailoverRound(round);
    if (failoverStage === "repeated") {
      const reloadBaseline = pages.map((_page, index) =>
        snapshotBrowserSocketEvidence(index),
      );
      evidence.reload = await Promise.all(
        pages.map(async (page, index) => {
          await page.reload({ waitUntil: "domcontentloaded" });
          const state = await waitForBrowserSocketRecovery(
            index,
            reloadBaseline[index],
            false,
          );
          const input = page.getByPlaceholder("Enter a message", {
            exact: true,
          });
          if (!(await input.isVisible())) {
            await page
              .getByRole("button", { name: "Chat with AI", exact: true })
              .click();
            await input.waitFor();
          }
          const activeSockets = await page.evaluate(
            () =>
              window.__probeSockets.filter(
                (socket) =>
                  socket.readyState === WebSocket.OPEN &&
                  new URL(socket.url).pathname === "/",
              ).length,
          );
          assert.equal(
            activeSockets,
            1,
            `Browser ${index} leaked a live JSON socket after reload`,
          );
          return state;
        }),
      );
    }

    const signalSuffix = round === 1 ? "" : `.${round}`;
    await fs.writeFile(
      `${signalPath}.recovered${signalSuffix}`,
      JSON.stringify({ pages: pages.length, round }),
    );
    await new Promise((resolve) => setTimeout(resolve, 1000));
    phoenixFailoverActive = false;
  }
  steps.push(
    failoverStage === "repeated"
      ? `browser-sockets-survived-${rounds}-node-reconnect-and-reload-rounds`
      : "browser-sockets-reconnected-restored-board-subscriptions-and-refreshed-chat-availability",
  );
}

async function assertApprovalIsNonActionable(page, message) {
  await page.getByText("Human input required", { exact: true }).waitFor();
  assert.equal(
    await page.getByRole("button", { name: "Approve", exact: true }).count(),
    0,
    message,
  );
}

async function waitForBoardSocketReady(page, projectUID) {
  await page.waitForTimeout(500);
  await page.waitForFunction(
    (uid) => {
      const boardLifecycle = window.__chatFrames.filter(
        (frame) =>
          ["subscribed", "unsubscribed"].includes(frame.event) &&
          frame.topic === "board" &&
          frame.topic_id.includes(uid),
      );
      return (
        window.__probeSockets.some(
          (socket) =>
            socket.readyState === WebSocket.OPEN &&
            new URL(socket.url).pathname === "/",
        ) && boardLifecycle.at(-1)?.event === "subscribed"
      );
    },
    projectUID,
    { timeout: 90000 },
  );
}

async function requestApi(credentials, user, pathname, options = {}) {
  const response = await fetch(`${apiOrigin}${pathname}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${user.access_token}`,
      Cookie: `${credentials.refresh_cookie_name}=${user.refresh_token}`,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    assert.fail(
      `${options.method || "GET"} ${pathname} failed with ${response.status}: ${await response.text()}`,
    );
  }
  return response;
}

async function waitForCheckitemOrder(
  credentials,
  user,
  checklistPath,
  checklistUID,
  expectedUIDs,
) {
  const deadline = Date.now() + 15000;
  let actualUIDs;
  while (Date.now() < deadline) {
    const response = await requestApi(credentials, user, checklistPath);
    const data = await response.json();
    actualUIDs = data.checklists
      .find((checklist) => checklist.uid === checklistUID)
      ?.checkitems.map((item) => item.uid);
    if (JSON.stringify(actualUIDs) === JSON.stringify(expectedUIDs)) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  assert.deepEqual(actualUIDs, expectedUIDs);
}

async function waitForCardColumn(credentials, expectedColumnUID) {
  const pathname = `/board/${credentials.project_uid}/card/${credentials.card_uid}`;
  const deadline = Date.now() + 15000;
  let actualColumnUID;
  while (Date.now() < deadline) {
    const response = await requestApi(
      credentials,
      credentials.users[1],
      pathname,
    );
    actualColumnUID = (await response.json()).card.project_column_uid;
    if (actualColumnUID === expectedColumnUID) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  assert.equal(actualColumnUID, expectedColumnUID);
}

async function waitForCardArchiveState(credentials, columnUID, archived) {
  const pathname = `/board/${credentials.project_uid}/card/${credentials.card_uid}`;
  const deadline = Date.now() + 15000;
  let card;
  while (Date.now() < deadline) {
    card = (
      await (
        await requestApi(credentials, credentials.users[1], pathname)
      ).json()
    ).card;
    if (
      card.project_column_uid === columnUID &&
      Boolean(card.archived_at) === archived
    )
      return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  assert.equal(card.project_column_uid, columnUID);
  assert.equal(Boolean(card.archived_at), archived);
}

async function waitForCardCommentEvent(
  page,
  offset,
  event,
  cardUID,
  commentUID,
) {
  await page.waitForFunction(
    ({ offset, event, cardUID, commentUID }) =>
      window.__chatFrames
        .slice(offset)
        .some(
          (frame) =>
            frame.event === `${event}:${cardUID}` &&
            (!commentUID ||
              frame.data?.comment?.uid === commentUID ||
              frame.data?.uid === commentUID ||
              frame.data?.comment_uid === commentUID),
        ),
    { offset, event, cardUID, commentUID },
    { timeout: 30000 },
  );
}

async function waitForVisibleSlateText(page, text, visible = true) {
  await page.waitForFunction(
    ({ expected, visible }) => {
      const matches = [
        ...document.querySelectorAll('[data-slate-string="true"]'),
      ].filter((element) => {
        const box = element.getBoundingClientRect();
        const style = window.getComputedStyle(element);
        return (
          element.textContent === expected &&
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          box.width > 0 &&
          box.height > 0
        );
      });
      return matches.length === (visible ? 1 : 0);
    },
    { expected: text, visible },
    { timeout: 30000 },
  );
}

async function waitForNotificationState(credentials, user, uid, state) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    const response = await requestApi(
      credentials,
      user,
      "/notifications?time_range=3d&page=1&limit=20",
    );
    const data = await response.json();
    const notification = data.notifications.find(
      (candidate) => candidate.uid === uid,
    );
    if (
      (state === "read" && notification?.read_at) ||
      (state === "deleted" && !notification)
    )
      return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Notification ${uid} did not become ${state}`);
}

function notificationButton(page) {
  return page.locator("button:has(svg.lucide-bell)").first();
}

function readAllNotificationsButton(page) {
  return page.locator("button:has(svg.lucide-check-check)").first();
}

function deleteAllNotificationsButton(page) {
  return page.locator("button:has(svg.lucide-trash-2)").first();
}

function readNotificationButton(page) {
  return page.locator("button:has(svg.lucide-check)").first();
}

function deleteNotificationButtons(page) {
  return page.locator("button:has(svg.lucide-trash-2)");
}

async function closeOpenCard(page) {
  const closeButton = page.getByRole("button", { name: "Close", exact: true });
  if (await closeButton.isVisible().catch(() => false)) {
    await closeButton.click();
    await closeButton.waitFor({ state: "hidden" });
  }
}

async function assertNotificationRealtimeAndCommands(owner, peer, credentials) {
  await Promise.all([closeOpenCard(owner), closeOpenCard(peer)]);
  for (const user of credentials.users) {
    const response = await requestApi(credentials, user, "/notifications", {
      method: "DELETE",
    });
    assert.equal((await response.json()).unread_count, 0);
  }
  const ownerMirror = await owner.context().newPage();
  ownerMirror.on("pageerror", (error) =>
    errors.push({
      index: "owner-notification-mirror",
      message: error.message,
      stack: error.stack,
    }),
  );
  ownerMirror.on("console", (message) => {
    if (message.type() === "error") {
      errors.push({
        index: "owner-notification-mirror",
        message: redact(message.text()),
      });
    }
  });
  await ownerMirror.goto(`${origin}/board/${credentials.project_uid}`, {
    waitUntil: "domcontentloaded",
  });
  await ownerMirror.waitForFunction(
    (userUID) =>
      window.__chatFrames.some(
        (frame) =>
          frame.event === "subscribed" &&
          frame.topic === "user_private" &&
          frame.topic_id.includes(userUID),
      ),
    credentials.users[0].uid,
  );
  await notificationButton(ownerMirror).waitFor();
  const offsets = await Promise.all(
    [owner, peer, ownerMirror].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  const result = await exec(
    "docker",
    [
      "exec",
      apiContainer,
      "uv",
      "run",
      "--no-sync",
      "python",
      fixturePath,
      "notify",
      runId,
    ],
    { timeout: diagnosticCommandTimeout },
  );
  const notificationUIDs = JSON.parse(result.stdout.trim()).notification_uids;
  const expected = [
    {
      page: owner,
      offset: offsets[0],
      user: credentials.users[0],
      uids: [notificationUIDs.owner_read, notificationUIDs.owner_bulk],
      foreignUIDs: [notificationUIDs.peer],
    },
    {
      page: peer,
      offset: offsets[1],
      user: credentials.users[1],
      uids: [notificationUIDs.peer],
      foreignUIDs: [notificationUIDs.owner_read, notificationUIDs.owner_bulk],
    },
  ];
  await Promise.all(
    expected.map(({ page, offset, user, uids }) =>
      page.waitForFunction(
        ({ offset, userUID, notificationUIDs }) =>
          notificationUIDs.every((notificationUID) =>
            window.__chatFrames
              .slice(offset)
              .some(
                (frame) =>
                  frame.event === "user:notified" &&
                  frame.topic === "user_private" &&
                  frame.topic_id === userUID &&
                  frame.data?.notification?.uid === notificationUID,
              ),
          ),
        { offset, userUID: user.uid, notificationUIDs: uids },
        { timeout: 30000 },
      ),
    ),
  );
  await ownerMirror.waitForFunction(
    ({ offset, userUID, notificationUIDs }) =>
      notificationUIDs.every((notificationUID) =>
        window.__chatFrames
          .slice(offset)
          .some(
            (frame) =>
              frame.event === "user:notified" &&
              frame.topic === "user_private" &&
              frame.topic_id === userUID &&
              frame.data?.notification?.uid === notificationUID,
          ),
      ),
    {
      offset: offsets[2],
      userUID: credentials.users[0].uid,
      notificationUIDs: [
        notificationUIDs.owner_read,
        notificationUIDs.owner_bulk,
      ],
    },
    { timeout: 30000 },
  );
  await new Promise((resolve) => setTimeout(resolve, 500));
  for (const { page, offset, foreignUIDs, uids } of expected) {
    assert.equal(
      await page.evaluate(
        ({ offset, foreignUIDs }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event === "user:notified" &&
                foreignUIDs.includes(frame.data?.notification?.uid),
            ),
        { offset, foreignUIDs },
      ),
      false,
      "A private notification must not reach another user",
    );
    await notificationButton(page)
      .getByText(String(uids.length), { exact: true })
      .waitFor();
  }
  await notificationButton(ownerMirror)
    .getByText("2", { exact: true })
    .waitFor();
  steps.push(
    "post-failover-user-notifications-fanned-out-and-rendered-with-private-isolation",
  );

  const replayOffsets = await Promise.all(
    [owner, ownerMirror].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  const replay = await exec(
    "docker",
    [
      "exec",
      apiContainer,
      "uv",
      "run",
      "--no-sync",
      "python",
      fixturePath,
      "replay-notify",
      runId,
    ],
    { timeout: diagnosticCommandTimeout },
  );
  assert.equal(
    JSON.parse(replay.stdout.trim()).notification_uid,
    notificationUIDs.owner_read,
  );
  await Promise.all(
    [owner, ownerMirror].map((page, index) =>
      page.waitForFunction(
        ({ offset, uid }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event === "user:notified" &&
                frame.data?.notification?.uid === uid,
            ),
        { offset: replayOffsets[index], uid: notificationUIDs.owner_read },
        { timeout: 30000 },
      ),
    ),
  );
  await new Promise((resolve) => setTimeout(resolve, 500));
  for (const page of [owner, ownerMirror]) {
    await notificationButton(page).getByText("2", { exact: true }).waitFor();
  }
  steps.push("replayed-user-notification-did-not-increment-unread-badge");

  await notificationButton(ownerMirror).click();
  await readAllNotificationsButton(ownerMirror).waitFor();
  let releaseRangeRequest;
  let markRangeRequestStarted;
  const rangeRequestStarted = new Promise(
    (resolve) => (markRangeRequestStarted = resolve),
  );
  const rangeRequestGate = new Promise(
    (resolve) => (releaseRangeRequest = resolve),
  );
  await ownerMirror.route("**/notifications?time_range=7d*", async (route) => {
    markRangeRequestStarted();
    await rangeRequestGate;
    await route.continue();
  });
  await ownerMirror
    .getByRole("combobox")
    .filter({ hasText: "In last 3 days" })
    .click();
  await ownerMirror.getByRole("option", { name: "In last 7 days" }).click();
  await rangeRequestStarted;
  await ownerMirror
    .getByText("No notifications received.", { exact: true })
    .waitFor();
  assert.equal(await deleteNotificationButtons(ownerMirror).count(), 1);
  const rangeResponse = ownerMirror.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/notifications" &&
      new URL(response.url()).searchParams.get("time_range") === "7d" &&
      response.request().method() === "GET",
  );
  releaseRangeRequest();
  assert.equal((await rangeResponse).status(), 200);
  await ownerMirror.waitForFunction(
    () =>
      document.querySelectorAll("button:has(svg.lucide-trash-2)").length === 3,
  );
  await ownerMirror.unroute("**/notifications?time_range=7d*");
  await ownerMirror
    .getByRole("combobox")
    .filter({ hasText: "In last 7 days" })
    .click();
  const originalRangeResponse = ownerMirror.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/notifications" &&
      new URL(response.url()).searchParams.get("time_range") === "3d" &&
      response.request().method() === "GET",
  );
  await ownerMirror.getByRole("option", { name: "In last 3 days" }).click();
  assert.equal((await originalRangeResponse).status(), 200);
  await ownerMirror
    .getByRole("combobox")
    .filter({ hasText: "In last 3 days" })
    .waitFor();
  await ownerMirror.waitForFunction(
    () =>
      document.querySelectorAll("button:has(svg.lucide-trash-2)").length === 3,
  );
  steps.push("notification-time-range-cleared-stale-list-before-response");

  const ownerReadOneMutationOffsets = await Promise.all(
    [owner, ownerMirror].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await notificationButton(owner).click();
  const ownerReadOneResponse = owner.waitForResponse((response) => {
    const pathname = new URL(response.url()).pathname;
    return (
      pathname.startsWith("/notifications/") &&
      pathname.endsWith("/read") &&
      response.request().method() === "PUT"
    );
  });
  await readNotificationButton(owner).click();
  const ownerReadOneResult = await ownerReadOneResponse;
  assert.equal(ownerReadOneResult.status(), 200);
  const ownerReadOneMutation = await ownerReadOneResult.json();
  assert.equal(ownerReadOneMutation.action, "read");
  assert.equal(ownerReadOneMutation.unread_count, 1);
  assert.ok(
    [notificationUIDs.owner_read, notificationUIDs.owner_bulk].includes(
      ownerReadOneMutation.notification_uid,
    ),
  );
  await Promise.all(
    [owner, ownerMirror].map((page, index) =>
      page.waitForFunction(
        ({ offset, userUID, notificationUID }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event === "user:notification:mutated" &&
                frame.topic === "user_private" &&
                frame.topic_id === userUID &&
                frame.data?.action === "read" &&
                frame.data?.notification_uid === notificationUID &&
                frame.data?.unread_count === 1,
            ),
        {
          offset: ownerReadOneMutationOffsets[index],
          userUID: credentials.users[0].uid,
          notificationUID: ownerReadOneMutation.notification_uid,
        },
        { timeout: 30000 },
      ),
    ),
  );
  await Promise.all(
    [owner, ownerMirror].map((page) =>
      notificationButton(page).getByText("1", { exact: true }).waitFor(),
    ),
  );
  await waitForNotificationState(
    credentials,
    credentials.users[0],
    ownerReadOneMutation.notification_uid,
    "read",
  );
  steps.push(
    "notification-read-converged-across-tabs-and-persisted-through-the-python-owner",
  );

  const ownerReadMutationOffsets = await Promise.all(
    [owner, ownerMirror].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  const ownerReadResponse = owner.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/notifications/read-all" &&
      response.request().method() === "PUT",
  );
  await readAllNotificationsButton(owner).click();
  assert.equal((await ownerReadResponse).status(), 200);
  await Promise.all(
    [owner, ownerMirror].map((page, index) =>
      page.waitForFunction(
        ({ offset, userUID }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event === "user:notification:mutated" &&
                frame.topic === "user_private" &&
                frame.topic_id === userUID &&
                frame.data?.action === "read_all" &&
                frame.data?.unread_count === 0,
            ),
        {
          offset: ownerReadMutationOffsets[index],
          userUID: credentials.users[0].uid,
        },
        { timeout: 30000 },
      ),
    ),
  );
  await notificationButton(owner)
    .getByText("1", { exact: true })
    .waitFor({ state: "detached" });
  await notificationButton(ownerMirror)
    .getByText("1", { exact: true })
    .waitFor({ state: "detached" });
  await Promise.all(
    [notificationUIDs.owner_read, notificationUIDs.owner_bulk].map((uid) =>
      waitForNotificationState(credentials, credentials.users[0], uid, "read"),
    ),
  );
  const readReplayOffsets = await Promise.all(
    [owner, ownerMirror].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  const readReplay = await exec(
    "docker",
    [
      "exec",
      apiContainer,
      "uv",
      "run",
      "--no-sync",
      "python",
      fixturePath,
      "replay-notify",
      runId,
      "--notification-uid",
      notificationUIDs.owner_read,
    ],
    { timeout: diagnosticCommandTimeout },
  );
  assert.equal(
    JSON.parse(readReplay.stdout.trim()).notification_uid,
    notificationUIDs.owner_read,
  );
  await Promise.all(
    [owner, ownerMirror].map((page, index) =>
      page.waitForFunction(
        ({ offset, uid }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event === "user:notified" &&
                frame.data?.notification?.uid === uid,
            ),
        { offset: readReplayOffsets[index], uid: notificationUIDs.owner_read },
        { timeout: 30000 },
      ),
    ),
  );
  await new Promise((resolve) => setTimeout(resolve, 500));
  for (const page of [owner, ownerMirror]) {
    await page
      .getByText("No notifications received.", { exact: true })
      .waitFor();
    assert.equal(
      await notificationButton(page).getByText("1", { exact: true }).count(),
      0,
    );
  }
  steps.push("replayed-unread-notification-did-not-revert-read-all");
  await owner.reload({ waitUntil: "domcontentloaded" });
  await notificationButton(owner).waitFor();
  steps.push(
    "notification-read-all-converged-across-tabs-and-persisted-through-the-python-owner",
  );

  const ownerDeleteMutationOffsets = await Promise.all(
    [owner, ownerMirror].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await notificationButton(owner).click();
  await Promise.all(
    [owner, ownerMirror].map((page) =>
      page.getByText("Only show unread", { exact: true }).click(),
    ),
  );
  await Promise.all(
    [owner, ownerMirror].map(async (page) => {
      assert.equal(await deleteNotificationButtons(page).count(), 3);
    }),
  );
  const ownerDeleteOneResponse = owner.waitForResponse((response) => {
    const pathname = new URL(response.url()).pathname;
    return (
      pathname.startsWith("/notifications/") &&
      pathname.split("/").length === 3 &&
      response.request().method() === "DELETE"
    );
  });
  await deleteNotificationButtons(owner).nth(1).click();
  const ownerDeleteOneResult = await ownerDeleteOneResponse;
  assert.equal(ownerDeleteOneResult.status(), 200);
  const ownerDeleteOneMutation = await ownerDeleteOneResult.json();
  assert.equal(ownerDeleteOneMutation.action, "delete");
  assert.equal(ownerDeleteOneMutation.unread_count, 0);
  assert.ok(
    [notificationUIDs.owner_read, notificationUIDs.owner_bulk].includes(
      ownerDeleteOneMutation.notification_uid,
    ),
  );
  await Promise.all(
    [owner, ownerMirror].map((page, index) =>
      page.waitForFunction(
        ({ offset, userUID, notificationUID }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event === "user:notification:mutated" &&
                frame.topic === "user_private" &&
                frame.topic_id === userUID &&
                frame.data?.action === "delete" &&
                frame.data?.notification_uid === notificationUID &&
                frame.data?.unread_count === 0,
            ),
        {
          offset: ownerDeleteMutationOffsets[index],
          userUID: credentials.users[0].uid,
          notificationUID: ownerDeleteOneMutation.notification_uid,
        },
        { timeout: 30000 },
      ),
    ),
  );
  await Promise.all(
    [owner, ownerMirror].map(async (page) => {
      await page.waitForFunction(
        () =>
          document.querySelectorAll("button:has(svg.lucide-trash-2)").length ===
          2,
      );
    }),
  );
  await waitForNotificationState(
    credentials,
    credentials.users[0],
    ownerDeleteOneMutation.notification_uid,
    "deleted",
  );
  steps.push(
    "notification-delete-converged-across-tabs-and-persisted-through-the-python-owner",
  );

  const ownerDeleteAllMutationOffsets = await Promise.all(
    [owner, ownerMirror].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  const mirrorSocketCount = await ownerMirror.evaluate(() => {
    const socket = window.__probeSockets.find(
      (candidate) =>
        new URL(candidate.url).pathname === "/" &&
        candidate.readyState === WebSocket.OPEN,
    );
    if (!socket || !socket.onclose) {
      throw new Error("Owner mirror socket is not ready");
    }
    const onClose = socket.onclose;
    socket.onclose = () => {
      onClose.call(socket, new CloseEvent("close", { code: 1012 }));
    };
    socket.close();
    return window.__probeSockets.length;
  });
  await ownerMirror.waitForFunction(() =>
    window.__probeSockets.some(
      (socket) =>
        new URL(socket.url).pathname === "/" &&
        socket.readyState === WebSocket.CLOSED,
    ),
  );
  const ownerDeleteResponse = owner.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/notifications" &&
      response.request().method() === "DELETE",
  );
  await deleteAllNotificationsButton(owner).click();
  assert.equal((await ownerDeleteResponse).status(), 200);
  await owner.waitForFunction(
    ({ offset, userUID }) =>
      window.__chatFrames
        .slice(offset)
        .some(
          (frame) =>
            frame.event === "user:notification:mutated" &&
            frame.topic_id === userUID &&
            frame.data?.action === "delete_all",
        ),
    {
      offset: ownerDeleteAllMutationOffsets[0],
      userUID: credentials.users[0].uid,
    },
  );
  assert.equal(
    await ownerMirror.evaluate(
      (offset) =>
        window.__chatFrames
          .slice(offset)
          .some(
            (frame) =>
              frame.event === "user:notification:mutated" &&
              frame.data?.action === "delete_all",
          ),
      ownerDeleteAllMutationOffsets[1],
    ),
    false,
  );
  assert.equal(await deleteNotificationButtons(ownerMirror).count(), 2);
  await ownerMirror.waitForFunction(
    (previousCount) =>
      window.__probeSockets.length > previousCount &&
      window.__probeSockets.some(
        (socket, index) =>
          index >= previousCount &&
          new URL(socket.url).pathname === "/" &&
          socket.readyState === WebSocket.OPEN,
      ),
    mirrorSocketCount,
    { timeout: 30000 },
  );
  await ownerMirror
    .getByText("No notifications received.", { exact: true })
    .waitFor();
  steps.push("notification-missed-delete-all-reconciled-on-socket-open");

  const restoredMutationOffsets = await Promise.all(
    [owner, ownerMirror].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  const restoredDeleteResponse = owner.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/notifications" &&
      response.request().method() === "DELETE",
  );
  await deleteAllNotificationsButton(owner).click();
  assert.equal((await restoredDeleteResponse).status(), 200);
  try {
    await Promise.all(
      [owner, ownerMirror].map((page, index) =>
        page.waitForFunction(
          ({ offset, userUID }) =>
            window.__chatFrames
              .slice(offset)
              .some(
                (frame) =>
                  frame.event === "user:notification:mutated" &&
                  frame.topic === "user_private" &&
                  frame.topic_id === userUID &&
                  frame.data?.action === "delete_all" &&
                  frame.data?.unread_count === 0,
              ),
          {
            offset: restoredMutationOffsets[index],
            userUID: credentials.users[0].uid,
          },
          { timeout: 30000 },
        ),
      ),
    );
  } catch (error) {
    const observed = await Promise.all(
      [owner, ownerMirror].map((page, index) =>
        page.evaluate(
          (offset) => ({
            frames: window.__chatFrames.slice(offset).map((frame) => ({
              event: frame.event,
              topic: frame.topic,
              action: frame.data?.action,
              unreadCount: frame.data?.unread_count,
              code: frame.code,
              path: frame.path,
              at: frame.at,
            })),
            sockets: window.__probeSockets.map((socket) => ({
              readyState: socket.readyState,
              path: new URL(socket.url).pathname,
            })),
          }),
          restoredMutationOffsets[index],
        ),
      ),
    );
    throw new Error(
      `Notification delete-all did not reach both browsers: ${JSON.stringify(observed)}`,
      {
        cause: error,
      },
    );
  }
  await Promise.all(
    [owner, ownerMirror].map((page) =>
      page.getByText("No notifications received.", { exact: true }).waitFor(),
    ),
  );
  await Promise.all(
    [notificationUIDs.owner_read, notificationUIDs.owner_bulk].map((uid) =>
      waitForNotificationState(
        credentials,
        credentials.users[0],
        uid,
        "deleted",
      ),
    ),
  );
  const deletedReplayOffsets = await Promise.all(
    [owner, ownerMirror].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  let rejectedNotificationRefreshes = 0;
  const notificationRefreshRoute = async (route) => {
    if (rejectedNotificationRefreshes++ === 0) {
      await route.fulfill({
        status: 503,
        body: "Temporary notification outage",
      });
      return;
    }
    await route.continue();
  };
  const notificationRefreshUrl = (url) =>
    url.port === "15694" && url.pathname === "/notifications";
  await owner.route(notificationRefreshUrl, notificationRefreshRoute);
  notificationRefreshOutageActive = true;
  const rejectedRefresh = owner.waitForResponse(
    (response) =>
      notificationRefreshUrl(new URL(response.url())) &&
      response.request().method() === "GET" &&
      response.status() === 503,
    { timeout: diagnosticCommandTimeout + 30000 },
  );
  const refreshResponses = [[], []];
  const refreshResponseListeners = [owner, ownerMirror].map((page, index) => {
    const listener = (response) => {
      if (
        new URL(response.url()).pathname === "/notifications" &&
        response.request().method() === "GET"
      ) {
        refreshResponses[index].push(response.status());
      }
    };
    page.on("response", listener);
    return listener;
  });
  const deletedReplayRefreshes = [owner, ownerMirror].map((page, index) =>
    page
      .waitForResponse(
        (response) =>
          new URL(response.url()).pathname === "/notifications" &&
          response.request().method() === "GET" &&
          response.status() === 200,
        { timeout: diagnosticCommandTimeout + 30000 },
      )
      .catch((error) => {
        throw new Error(
          `Notification refresh timed out on tab ${index}: ${JSON.stringify(refreshResponses)}`,
          { cause: error },
        );
      }),
  );
  const deletedReplay = await exec(
    "docker",
    [
      "exec",
      apiContainer,
      "uv",
      "run",
      "--no-sync",
      "python",
      fixturePath,
      "replay-deleted-notify",
      runId,
    ],
    { timeout: diagnosticCommandTimeout },
  );
  assert.equal(
    JSON.parse(deletedReplay.stdout.trim()).notification_uid,
    notificationUIDs.owner_read,
  );
  assert.equal((await rejectedRefresh).status(), 503);
  await Promise.all(
    [owner, ownerMirror].map(async (page, index) => {
      await page.waitForFunction(
        ({ offset, uid }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event === "user:notified" &&
                frame.data?.notification?.uid === uid,
            ),
        {
          offset: deletedReplayOffsets[index],
          uid: notificationUIDs.owner_read,
        },
        { timeout: 30000 },
      );
      assert.equal((await deletedReplayRefreshes[index]).status(), 200);
      await notificationButton(page)
        .getByText("1", { exact: true })
        .waitFor({ state: "detached" });
      await page
        .getByText("No notifications received.", { exact: true })
        .waitFor();
    }),
  );
  await owner.unroute(notificationRefreshUrl, notificationRefreshRoute);
  [owner, ownerMirror].forEach((page, index) =>
    page.off("response", refreshResponseListeners[index]),
  );
  notificationRefreshOutageActive = false;
  assert.equal(rejectedNotificationRefreshes, 2);
  steps.push("deleted-notification-late-replay-reconciled-with-server-state");
  await owner.reload({ waitUntil: "domcontentloaded" });
  await notificationButton(owner).waitFor();
  await ownerMirror.close();
  steps.push(
    "notification-delete-all-converged-across-tabs-and-persisted-through-the-python-owner",
  );

  await notificationButton(peer).click();
  const peerDeleteResponse = peer.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/notifications" &&
      response.request().method() === "DELETE",
  );
  await deleteAllNotificationsButton(peer).click();
  assert.equal((await peerDeleteResponse).status(), 200);
  await notificationButton(peer)
    .getByText("1", { exact: true })
    .waitFor({ state: "detached" });
  await waitForNotificationState(
    credentials,
    credentials.users[1],
    notificationUIDs.peer,
    "deleted",
  );
  await peer.reload({ waitUntil: "domcontentloaded" });
  await notificationButton(peer).waitFor();
  steps.push("notification-delete-all-persisted-through-the-python-owner");

  await openPeerCardDocument(peer, credentials);
}

async function assertConcurrentCardComments(owner, peer, credentials) {
  assert.notEqual(credentials.users[0].uid, credentials.users[1].uid);
  const pagesUnderTest = [owner, peer];
  const commentPath = `/board/${credentials.project_uid}/card/${credentials.card_uid}/comment`;
  const texts = pagesUnderTest.map(
    (_, index) => `Concurrent comment ${index} ${runId}`,
  );
  const cardUrl = `${origin}/board/${credentials.project_uid}/${credentials.card_uid}`;
  await Promise.all(pagesUnderTest.map(async (page) => {
    await page.goto(cardUrl, { waitUntil: "networkidle" });
    await page.getByText("No description", { exact: true }).waitFor();
  }));
  await Promise.all(pagesUnderTest.map(async (page, index) => {
    const comments = page.getByRole("button", { name: "Comments", exact: true });
    const composer = page.getByText(`Add a comment as ${credentials.users[index].name}`, {
      exact: true,
    }).and(page.locator(":visible"));
    if (!(await composer.isVisible())) {
      await comments.click();
    }
    try {
      await composer.click();
    } catch (error) {
      const layout = await page.evaluate(() => ({
        width: innerWidth,
        desktopLayout: matchMedia("(min-width: 768px)").matches,
        panels: [...document.querySelectorAll("[aria-hidden]")].map((element) => ({
          hidden: element.getAttribute("aria-hidden"),
          width: element.getBoundingClientRect().width,
          text: element.textContent?.slice(0, 80),
        })),
        commentForms: document.querySelectorAll("[data-card-comment-form]").length,
        pressed: [...document.querySelectorAll("button")].filter((button) =>
          button.textContent?.trim() === "Comments").map((button) => button.getAttribute("aria-pressed")),
      }));
      throw new Error(`${error}\nComment layout: ${JSON.stringify(layout)}`);
    }
    const editor = page.locator(
      '[data-card-comment-form] [data-slate-editor="true"]:visible',
    );
    try {
      await editor.waitFor();
    } catch (error) {
      const layout = await page.evaluate(() => ({
        pressed: [...document.querySelectorAll("button")].filter((button) =>
          button.textContent?.trim() === "Comments").map((button) => button.getAttribute("aria-pressed")),
        forms: [...document.querySelectorAll("[data-card-comment-form]")].map((form) => ({
          visible: form.getClientRects().length > 0,
          text: form.textContent?.slice(0, 100),
        })),
      }));
      throw new Error(`Comment editor did not open: ${JSON.stringify(layout)}`, { cause: error });
    }
    await editor.fill(texts[index]);
    await page
      .getByRole("button", { name: "Save", exact: true })
      .and(page.locator(":visible"))
      .waitFor();
  }));

  const offsets = await Promise.all(
    pagesUnderTest.map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  let arrivals = 0;
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const holdBothPosts = async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    arrivals += 1;
    if (arrivals === 2) release();
    await gate;
    await route.continue();
  };
  for (const page of pagesUnderTest) {
    await page.route(`**${commentPath}`, holdBothPosts);
  }
  let timeout;
  try {
    await Promise.all(
      pagesUnderTest.map((page) =>
        page
          .getByRole("button", { name: "Save", exact: true })
          .and(page.locator(":visible"))
          .click(),
      ),
    );
    await Promise.race([
      gate,
      new Promise((_, reject) => {
        timeout = setTimeout(
          () => reject(new Error(`Only ${arrivals}/2 comment POSTs arrived`)),
          15000,
        );
      }),
    ]);
  } finally {
    clearTimeout(timeout);
    release();
    for (const page of pagesUnderTest) {
      await page.unroute(`**${commentPath}`, holdBothPosts);
    }
  }
  assert.equal(arrivals, 2);
  for (const [index, page] of pagesUnderTest.entries()) {
    await page.waitForFunction(
      ({ offset, cardUID }) =>
        window.__chatFrames
          .slice(offset)
          .filter(
            (frame) => frame.event === `board:card:comment:added:${cardUID}`,
          ).length >= 2,
      { offset: offsets[index], cardUID: credentials.card_uid },
      { timeout: 30000 },
    );
    for (const content of texts) await waitForVisibleSlateText(page, content);
    const events = await page.evaluate(
      ({ offset, cardUID }) =>
        window.__chatFrames
          .slice(offset)
          .filter(
            (frame) => frame.event === `board:card:comment:added:${cardUID}`,
          ),
      { offset: offsets[index], cardUID: credentials.card_uid },
    );
    assert.equal(events.length, 2);
    assert.equal(new Set(events.map((event) => event.data?.comment?.uid)).size, 2);
  }
  const response = await requestApi(
    credentials,
    credentials.users[0],
    `${commentPath}s`,
  );
  const { comments } = await response.json();
  for (const content of texts) {
    assert.equal(
      comments.filter((comment) =>
        JSON.stringify(comment.content).includes(content),
      ).length,
      1,
    );
  }
  assert.equal(new Set(comments.map((comment) => comment.uid)).size, comments.length);
  for (const page of pagesUnderTest) {
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByText("No description", { exact: true }).waitFor();
    const commentsButton = page.getByRole("button", { name: "Comments", exact: true });
    if ((await commentsButton.getAttribute("aria-pressed")) !== "true") {
      await commentsButton.click();
    }
    for (const content of texts) await waitForVisibleSlateText(page, content);
  }
  steps.push("two-distinct-users-overlapping-comment-posts-persisted-once-and-fanned-out-to-both-browsers");
}

async function assertConcurrentChecklists(owner, peer, credentials) {
  const pagesUnderTest = [owner, peer];
  const checklistPath = `/board/${credentials.project_uid}/card/${credentials.card_uid}/checklist`;
  const titles = pagesUnderTest.map(
    (_, index) => `Concurrent checklist ${index} ${runId}`,
  );
  await Promise.all(pagesUnderTest.map(async (page) => {
    await page.goto(`${origin}/board/${credentials.project_uid}/${credentials.card_uid}`, { waitUntil: "networkidle" });
    await page.getByText("No description", { exact: true }).waitFor();
  }));
  for (const [index, page] of pagesUnderTest.entries()) {
    const addChecklist = page.getByRole("button", { name: "Add checklist", exact: true });
    const actions = page.getByRole("button", { name: "Actions", exact: true });
    if (!(await addChecklist.isVisible())) {
      await actions.click();
    }
    await addChecklist.click();
    await page.getByLabel("Checklist title", { exact: true }).fill(titles[index]);
    await page
      .getByRole("button", { name: "Save", exact: true })
      .and(page.locator(":visible"))
      .waitFor();
  }
  const offsets = await Promise.all(
    pagesUnderTest.map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  let arrivals = 0;
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const holdBothPosts = async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    arrivals += 1;
    if (arrivals === 2) release();
    await gate;
    await route.continue();
  };
  for (const page of pagesUnderTest) {
    await page.route(`**${checklistPath}`, holdBothPosts);
  }
  let timeout;
  try {
    await Promise.all(
      pagesUnderTest.map((page) =>
        page
          .getByRole("button", { name: "Save", exact: true })
          .and(page.locator(":visible"))
          .click(),
      ),
    );
    await Promise.race([
      gate,
      new Promise((_, reject) => {
        timeout = setTimeout(
          () => reject(new Error(`Only ${arrivals}/2 checklist POSTs arrived`)),
          15000,
        );
      }),
    ]);
  } finally {
    clearTimeout(timeout);
    release();
    for (const page of pagesUnderTest) {
      await page.unroute(`**${checklistPath}`, holdBothPosts);
    }
  }
  assert.equal(arrivals, 2);
  for (const [index, page] of pagesUnderTest.entries()) {
    await page.waitForFunction(
      ({ offset, cardUID }) =>
        window.__chatFrames
          .slice(offset)
          .filter(
            (frame) => frame.event === `board:card:checklist:created:${cardUID}`,
          ).length >= 2,
      { offset: offsets[index], cardUID: credentials.card_uid },
      { timeout: 30000 },
    );
    const events = await page.evaluate(
      ({ offset, cardUID }) =>
        window.__chatFrames
          .slice(offset)
          .filter(
            (frame) => frame.event === `board:card:checklist:created:${cardUID}`,
          ),
      { offset: offsets[index], cardUID: credentials.card_uid },
    );
    assert.equal(events.length, 2);
    assert.equal(new Set(events.map((event) => event.data?.checklist?.uid)).size, 2);
    for (const title of titles) {
      await page.getByText(title, { exact: true }).waitFor();
    }
  }
  const response = await requestApi(
    credentials,
    credentials.users[0],
    checklistPath,
  );
  const { checklists } = await response.json();
  for (const title of titles) {
    assert.equal(checklists.filter((checklist) => checklist.title === title).length, 1);
  }
  for (const page of pagesUnderTest) {
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByText("No description", { exact: true }).waitFor();
    for (const title of titles) {
      await page.getByText(title, { exact: true }).waitFor();
    }
  }
  steps.push("two-distinct-users-overlapping-checklist-posts-persisted-once-and-fanned-out-to-both-browsers");
}

async function assertConcurrentCheckitems(owner, peer, credentials) {
  const pagesUnderTest = [owner, peer];
  const checklistPath = `/board/${credentials.project_uid}/card/${credentials.card_uid}/checklist`;
  const checklistTitle = `Concurrent checkitems ${runId}`;
  const created = await requestApi(credentials, credentials.users[0], checklistPath, {
    method: "POST",
    body: JSON.stringify({ title: checklistTitle }),
  });
  assert.equal(created.status, 201);
  const checklistUID = (await created.json()).checklist.uid;
  const itemPath = `${checklistPath}/${checklistUID}/checkitem`;
  await Promise.all(pagesUnderTest.map(async (page) => {
    await page.goto(`${origin}/board/${credentials.project_uid}/${credentials.card_uid}`, { waitUntil: "networkidle" });
    const checklist = page.getByText(checklistTitle, { exact: true })
      .locator("xpath=ancestor::div[contains(@class,'snap-center')]");
    await checklist.locator("button:has(svg.lucide-plus)").waitFor();
  }));
  let arrivals = 0;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const holdBothPosts = async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    arrivals += 1;
    if (arrivals === 2) release();
    await gate;
    await route.continue();
  };
  for (const page of pagesUnderTest) await page.route(`**${itemPath}`, holdBothPosts);
  let timeout;
  try {
    await Promise.race([Promise.all(pagesUnderTest.map((page) => page.getByText(checklistTitle, { exact: true })
      .locator("xpath=ancestor::div[contains(@class,'snap-center')]")
      .locator("button:has(svg.lucide-plus)").click())),
      new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error(`Only ${arrivals}/2 checkitem POSTs arrived`)), 15000); }),
    ]);
  } finally {
    clearTimeout(timeout);
    release();
    for (const page of pagesUnderTest) await page.unroute(`**${itemPath}`, holdBothPosts);
  }
  assert.equal(arrivals, 2);
  for (const page of pagesUnderTest) {
    const checklist = page.getByText(checklistTitle, { exact: true })
      .locator("xpath=ancestor::div[contains(@class,'snap-center')]");
    const expand = checklist.getByRole("button", { name: "Expand", exact: true });
    if (await expand.count()) await expand.click();
    await page.waitForFunction((title) => {
      const checklist = [...document.querySelectorAll(".snap-center")].find((element) => element.textContent?.includes(title));
      return checklist && [...checklist.querySelectorAll("*")].filter((element) => element.textContent?.trim() === "New checkitem").length >= 2;
    }, checklistTitle);
  }
  const response = await requestApi(credentials, credentials.users[0], checklistPath);
  const { checklists } = await response.json();
  const items = checklists.find((checklist) => checklist.uid === checklistUID)?.checkitems ?? [];
  assert.equal(items.filter((item) => item.title === "New checkitem").length, 2);
  assert.equal(new Set(items.map((item) => item.uid)).size, items.length);
  for (const page of pagesUnderTest) {
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByText(checklistTitle, { exact: true }).waitFor();
    const reloaded = page.getByText(checklistTitle, { exact: true })
      .locator("xpath=ancestor::div[contains(@class,'snap-center')]");
    await reloaded.getByRole("button", { name: "Expand", exact: true }).click();
    await page.waitForFunction((title) => {
      const checklist = [...document.querySelectorAll(".snap-center")].find((element) => element.textContent?.includes(title));
      return checklist && [...checklist.querySelectorAll("*")].filter((element) => element.textContent?.trim() === "New checkitem").length >= 2;
    }, checklistTitle);
  }
  steps.push("two-distinct-users-overlapping-checkitem-posts-persisted-once-and-fanned-out-to-both-browsers");
}

async function assertConcurrentCheckitemDetails(owner, peer, credentials) {
  const pagesUnderTest = [owner, peer];
  const checklistPath = `/board/${credentials.project_uid}/card/${credentials.card_uid}/checklist`;
  const checklistTitle = `Concurrent checkitem details ${runId}`;
  const itemTitle = `Original checkitem ${runId}`;
  const newTitle = `Renamed checkitem ${runId}`;
  const checklistResponse = await requestApi(credentials, credentials.users[0], checklistPath, {
    method: "POST",
    body: JSON.stringify({ title: checklistTitle }),
  });
  assert.equal(checklistResponse.status, 201);
  const checklistUID = (await checklistResponse.json()).checklist.uid;
  const itemResponse = await requestApi(credentials, credentials.users[0], `${checklistPath}/${checklistUID}/checkitem`, {
    method: "POST",
    body: JSON.stringify({ title: itemTitle }),
  });
  assert.equal(itemResponse.status, 201);
  const itemUID = (await itemResponse.json()).checkitem.uid;
  const itemPath = `/board/${credentials.project_uid}/card/${credentials.card_uid}/checkitem/${itemUID}`;
  await Promise.all(pagesUnderTest.map(async (page) => {
    await page.goto(`${origin}/board/${credentials.project_uid}/${credentials.card_uid}`, { waitUntil: "networkidle" });
    await page.getByText(checklistTitle, { exact: true }).waitFor();
    await page.getByText(checklistTitle, { exact: true })
      .locator("xpath=ancestor::div[contains(@class,'snap-center')]")
      .getByRole("button", { name: "Expand", exact: true }).click();
    await page.getByText(itemTitle, { exact: true }).waitFor();
  }));
  const itemRow = (page) => page.getByText(itemTitle, { exact: true })
    .locator("xpath=ancestor::div[contains(@class,'border-accent')][1]");
  await itemRow(owner).getByRole("button", { name: "More", exact: true }).click();
  await owner.getByRole("menuitem", { name: "Edit title" }).click();
  await owner.getByPlaceholder("Checkitem title", { exact: true }).fill(newTitle);
  const titleResponse = owner.waitForResponse((response) => response.request().method() === "PUT" &&
    response.url().includes(`${itemPath}/title`));
  const checkedResponse = peer.waitForResponse((response) => response.request().method() === "PUT" &&
    response.url().includes(`${itemPath}/toggle-checked`));
  await Promise.all([
    owner.getByRole("button", { name: "Save", exact: true }).click(),
    itemRow(peer).getByRole("checkbox").click(),
  ]);
  assert.deepEqual((await Promise.all([titleResponse, checkedResponse])).map((response) => response.status()), [200, 200]);
  const persisted = await requestApi(credentials, credentials.users[0], checklistPath);
  const item = (await persisted.json()).checklists.find((checklist) => checklist.uid === checklistUID)
    ?.checkitems.find((checkitem) => checkitem.uid === itemUID);
  assert.equal(item?.title, newTitle);
  assert.equal(item?.is_checked, true);
  for (const page of pagesUnderTest) {
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByText(checklistTitle, { exact: true })
      .locator("xpath=ancestor::div[contains(@class,'snap-center')]")
      .getByRole("button", { name: "Expand", exact: true }).click();
    await page.getByText(newTitle, { exact: true }).waitFor({ timeout: 30000 });
    await page.getByText(newTitle, { exact: true })
      .locator("xpath=ancestor::div[contains(@class,'border-accent')][1]")
      .locator('[role="checkbox"][data-state="checked"]').waitFor();
  }
  steps.push("two-distinct-users-concurrent-same-checkitem-title-and-checked-state-preserved-after-reload");
}

async function assertConcurrentBoardChatSends(owner, peer, credentials) {
  const pagesUnderTest = [owner, peer];
  const messages = pagesUnderTest.map(
    (_, index) => `Concurrent chat ${index} ${runId}: reply with OK.`,
  );
  const before = await snapshot();
  for (const [index, page] of pagesUnderTest.entries()) {
    await page.goto(`${origin}/board/${credentials.project_uid}`, {
      waitUntil: "domcontentloaded",
    });
    await waitForBoardSocketReady(page, credentials.project_uid);
    await openBoardChat(page);
    await page
      .getByPlaceholder("Enter a message", { exact: true })
      .fill(messages[index]);
  }
  const offsets = await Promise.all(
    pagesUnderTest.map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await Promise.all(
    pagesUnderTest.map((page) =>
      page.getByPlaceholder("Enter a message", { exact: true }).press("Enter"),
    ),
  );
  const taskIds = [];
  for (const [index, page] of pagesUnderTest.entries()) {
    await page.waitForFunction(
      (offset) =>
        window.__chatFrames
          .slice(offset)
          .some(
            (frame) =>
              frame.event === "outbound" &&
              frame.data?.event === "board:chat:send",
          ),
      offsets[index],
      { timeout: 30000 },
    );
    taskIds.push(
      await page.evaluate(
        (offset) =>
          window.__chatFrames
            .slice(offset)
            .find(
              (frame) =>
                frame.event === "outbound" &&
                frame.data?.event === "board:chat:send",
            )?.data?.data?.task_id,
        offsets[index],
      ),
    );
  }
  assert.equal(new Set(taskIds).size, 2);
  for (const [index, page] of pagesUnderTest.entries()) {
    await page.waitForFunction(
      (offset) =>
        window.__chatFrames
          .slice(offset)
          .some((frame) => frame.event === "board:chat:stream:end"),
      offsets[index],
      { timeout: 150000 },
    );
    await page.getByText(messages[index], { exact: true }).waitFor();
  }
  const after = await snapshot();
  for (const [index, taskId] of taskIds.entries()) {
    const runs = after.runs.filter((run) => run.client_task_id === taskId);
    assert.equal(runs.length, 1);
    assert.ok(
      ["InternalBotRunStatus.Completed", "InternalBotRunStatus.AwaitingApproval"].includes(runs[0].status),
      `${taskId}: ${runs[0].status}`,
    );
    if (runs[0].status === "InternalBotRunStatus.AwaitingApproval") {
      await pagesUnderTest[index].getByText("Human input required", { exact: true }).waitFor();
    }
    assert.ok(!before.runs.some((run) => run.client_task_id === taskId));
  }
  for (const [index, page] of pagesUnderTest.entries()) {
    await page.reload({ waitUntil: "domcontentloaded" });
    await openBoardChat(page);
    await page.getByText(messages[index], { exact: true }).waitFor();
  }
  steps.push("two-distinct-users-concurrent-board-chat-sends-completed-or-awaiting-approval-and-survived-reload");
}

async function assertConcurrentNotificationReads(owner, peer, credentials) {
  const pagesUnderTest = [owner, peer];
  for (const user of credentials.users) {
    await requestApi(credentials, user, "/notifications", {
      method: "DELETE",
    });
  }
  const created = await exec(
    "docker",
    ["exec", apiContainer, "uv", "run", "--no-sync", "python", fixturePath, "notify", runId],
    { timeout: diagnosticCommandTimeout },
  );
  const notificationUIDs = JSON.parse(created.stdout.trim()).notification_uids;
  const expectedUIDs = [
    [notificationUIDs.owner_read, notificationUIDs.owner_bulk],
    [notificationUIDs.peer],
  ];
  for (const [index, page] of pagesUnderTest.entries()) {
    await notificationButton(page).getByText(String(expectedUIDs[index].length), { exact: true }).waitFor();
    await notificationButton(page).click();
    await readAllNotificationsButton(page).waitFor();
  }
  const offsets = await Promise.all(
    pagesUnderTest.map((page) => page.evaluate(() => window.__chatFrames.length)),
  );
  await Promise.all(pagesUnderTest.map((page) => readAllNotificationsButton(page).click()));
  for (const [index, page] of pagesUnderTest.entries()) {
    await page.waitForFunction(
      ({ offset, userUID }) =>
        window.__chatFrames.slice(offset).some(
          (frame) =>
            frame.event === "user:notification:mutated" &&
            frame.topic === "user_private" &&
            frame.topic_id === userUID &&
            frame.data?.action === "read_all" &&
            frame.data?.unread_count === 0,
        ),
      { offset: offsets[index], userUID: credentials.users[index].uid },
      { timeout: 30000 },
    );
    await notificationButton(page)
      .getByText(String(expectedUIDs[index].length), { exact: true })
      .waitFor({ state: "detached" });
    for (const uid of expectedUIDs[index]) {
      await waitForNotificationState(credentials, credentials.users[index], uid, "read");
    }
  }
  steps.push("two-distinct-users-concurrent-notification-read-all-kept-private-counts-consistent");
}

function dashboardProjectCounts(page) {
  return page.evaluate((title) => {
    const heading = [...document.querySelectorAll("h3")]
      .find((element) => element.textContent?.trim() === title);
    const project = heading?.parentElement?.parentElement;
    if (!project) return null;
    return [...project.lastElementChild.querySelectorAll("span.text-sm.font-semibold")]
      .map((element) => Number(element.textContent));
  }, `Migration editor access probe ${runId}`);
}

async function assertConcurrentCardCreation(owner, peer, credentials, dashboard) {
  const pagesUnderTest = [owner, peer];
  const createPath = `/board/${credentials.project_uid}/card`;
  const titles = pagesUnderTest.map(
    (_, index) => `Concurrent board card ${index} ${runId}`,
  );
  const dashboardBefore = dashboard ? await dashboardProjectCounts(dashboard) : null;
  if (dashboard) assert.ok(dashboardBefore);
  await Promise.all(pagesUnderTest.map(async (page) => {
    await page.goto(`${origin}/board/${credentials.project_uid}`, {
      waitUntil: "domcontentloaded",
    });
    await waitForBoardSocketReady(page, credentials.project_uid);
    await page.getByRole("button", { name: "Add a card", exact: true }).first().waitFor();
  }));
  const cancelledTitle = `Cancelled board card ${runId}`;
  const ownerColumn = owner.getByText("Editor verification", { exact: true })
    .locator("xpath=ancestor::*[contains(@class, 'snap-center')][1]");
  let cancelledRequests = 0;
  const onOwnerRequest = (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname.endsWith(createPath)) {
      cancelledRequests += 1;
    }
  };
  owner.on("request", onOwnerRequest);
  try {
    await ownerColumn.getByRole("button", { name: "Add a card", exact: true }).click();
    await ownerColumn.getByPlaceholder("Enter a title", { exact: true }).fill(cancelledTitle);
    await ownerColumn.locator("button:has(svg.lucide-x)").click();
    await owner.getByRole("button", { name: "Filters", exact: true }).click();
    assert.equal(cancelledRequests, 0);
    await owner.keyboard.press("Escape");
  } finally {
    owner.off("request", onOwnerRequest);
  }
  await Promise.all(pagesUnderTest.map(async (page, index) => {
    await page.getByRole("button", { name: "Add a card", exact: true }).first().click();
    await page.getByPlaceholder("Enter a title", { exact: true }).fill(titles[index]);
  }));
  const offsets = await Promise.all(
    pagesUnderTest.map((page) => page.evaluate(() => window.__chatFrames.length)),
  );
  let arrivals = 0;
  let release;
  const pendingRoutes = [];
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const holdBothPosts = async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    arrivals += 1;
    if (arrivals === 2) release();
    await gate;
    const pending = route.continue();
    pendingRoutes.push(pending);
    await pending;
  };
  for (const page of pagesUnderTest) {
    await page.route(`**${createPath}`, holdBothPosts);
  }
  let timeout;
  try {
    const clicks = Promise.all(
      pagesUnderTest.map((page) =>
        page.getByRole("button", { name: "Add card", exact: true }).click({ noWaitAfter: true }),
      ),
    );
    await Promise.race([
      gate,
      new Promise((_, reject) => {
        timeout = setTimeout(
          () => reject(new Error(`Only ${arrivals}/2 card POSTs arrived`)),
          15000,
        );
      }),
    ]);
    await clicks;
  } catch (error) {
    const states = await Promise.all(pagesUnderTest.map((page) => page.evaluate(() => ({
      pathname: location.pathname,
      editorValue: document.querySelector('textarea[placeholder="Enter a title"]')?.value ?? null,
      addCardButtons: [...document.querySelectorAll("button")]
        .filter((button) => button.textContent?.trim() === "Add card").length,
      visibleText: document.body.innerText.slice(-600),
    }))));
    throw new Error(`${error}\nCard editor states: ${JSON.stringify(states)}`);
  } finally {
    clearTimeout(timeout);
    release();
    await Promise.allSettled(pendingRoutes);
    for (const page of pagesUnderTest) {
      await page.unroute(`**${createPath}`, holdBothPosts);
    }
  }
  assert.equal(arrivals, 2);
  for (const [index, page] of pagesUnderTest.entries()) {
    await page.waitForFunction(
      ({ offset }) =>
        window.__chatFrames.slice(offset).filter(
          (frame) => frame.event.startsWith("board:card:created:"),
        ).length >= 2,
      { offset: offsets[index] },
      { timeout: 30000 },
    );
    const events = await page.evaluate(
      (offset) =>
        window.__chatFrames.slice(offset).filter(
          (frame) => frame.event.startsWith("board:card:created:"),
        ),
      offsets[index],
    );
    assert.equal(events.length, 2);
    assert.equal(new Set(events.map((event) => event.data?.card?.uid)).size, 2);
    await closeOpenCard(page);
    for (const title of titles) {
      await page
        .locator('[id^="board-card-"]')
        .getByRole("heading", { name: title, exact: true })
        .waitFor();
    }
  }
  const response = await requestApi(credentials, credentials.users[0], `/board/${credentials.project_uid}/cards`);
  const { cards } = await response.json();
  assert.equal(cards.filter((card) => card.title === cancelledTitle).length, 0);
  for (const title of titles) {
    assert.equal(cards.filter((card) => card.title === title).length, 1);
  }
  for (const page of pagesUnderTest) {
    await page.reload({ waitUntil: "domcontentloaded" });
    for (const title of titles) {
      await page
        .locator('[id^="board-card-"]')
        .getByRole("heading", { name: title, exact: true })
        .waitFor();
    }
  }
  if (dashboard) {
    await dashboard.waitForFunction(
      ({ title, count }) => {
        const heading = [...document.querySelectorAll("h3")]
          .find((element) => element.textContent?.trim() === title);
        const project = heading?.parentElement?.parentElement;
        const counts = [...(project?.lastElementChild?.querySelectorAll("span.text-sm.font-semibold") ?? [])]
          .map((element) => Number(element.textContent));
        return counts.reduce((sum, value) => sum + value, 0) === count + 2;
      },
      { title: `Migration editor access probe ${runId}`, count: dashboardBefore.reduce((sum, value) => sum + value, 0) },
      { timeout: 30000 },
    );
  }
  steps.push("two-distinct-users-overlapping-card-creates-persisted-once-and-fanned-out-to-both-boards");
}

async function assertConcurrentColumnCreation(owner, peer, credentials, dashboard) {
  const pagesUnderTest = [owner, peer];
  const names = pagesUnderTest.map((_, index) => `Concurrent column ${index} ${runId}`);
  const dashboardBefore = dashboard ? await dashboardProjectCounts(dashboard) : null;
  if (dashboard) assert.ok(dashboardBefore);
  await Promise.all(pagesUnderTest.map(async (page) => {
    await page.goto(`${origin}/board/${credentials.project_uid}`, { waitUntil: "domcontentloaded" });
    await waitForBoardSocketReady(page, credentials.project_uid);
    await page.getByRole("button", { name: "Add column", exact: true }).waitFor();
  }));
  await Promise.all(pagesUnderTest.map(async (page, index) => {
    await page.getByRole("button", { name: "Add column", exact: true }).click();
    await page.getByPlaceholder("Enter a name", { exact: true }).fill(names[index]);
  }));
  await Promise.all(pagesUnderTest.map((page) =>
    page.getByPlaceholder("Enter a name", { exact: true }).press("Enter"),
  ));
  for (const page of pagesUnderTest) {
    for (const name of names) {
      await page.getByText(name, { exact: true }).waitFor();
    }
  }
  const response = await requestApi(credentials, credentials.users[0], `/board/${credentials.project_uid}/columns`);
  const { columns } = await response.json();
  for (const name of names) {
    assert.equal(columns.filter((column) => column.name === name).length, 1);
  }
  for (const page of pagesUnderTest) {
    await page.reload({ waitUntil: "domcontentloaded" });
    for (const name of names) {
      await page.getByText(name, { exact: true }).waitFor();
    }
  }
  if (dashboard) {
    await dashboard.waitForFunction(
      ({ title, count }) => {
        const heading = [...document.querySelectorAll("h3")]
          .find((element) => element.textContent?.trim() === title);
        const project = heading?.parentElement?.parentElement;
        return project?.lastElementChild?.querySelectorAll("span.text-sm.font-semibold").length === count + 2;
      },
      { title: `Migration editor access probe ${runId}`, count: dashboardBefore.length },
      { timeout: 30000 },
    );
  }
  steps.push("two-distinct-users-concurrent-column-creates-persisted-once-and-fanned-out-to-both-boards");
}

async function assertConcurrentColumnRename(owner, peer, credentials) {
  const pagesUnderTest = [owner, peer];
  const originalNames = pagesUnderTest.map((_, index) => `Concurrent column ${index} ${runId}`);
  const renamedNames = originalNames.map((name) => `${name} renamed`);
  const response = await requestApi(credentials, credentials.users[0], `/board/${credentials.project_uid}/columns`);
  const { columns } = await response.json();
  const targetColumns = originalNames.map((name) => columns.find((column) => column.name === name));
  assert.ok(targetColumns.every(Boolean));
  await Promise.all(pagesUnderTest.map(async (page) => {
    await page.goto(`${origin}/board/${credentials.project_uid}`, { waitUntil: "networkidle" });
    await waitForBoardSocketReady(page, credentials.project_uid);
    for (const name of originalNames) await page.getByText(name, { exact: true }).waitFor();
  }));
  await Promise.all(pagesUnderTest.map(async (page, index) => {
    const column = page.getByText(originalNames[index], { exact: true }).locator("xpath=../..");
    await column.locator("button[aria-haspopup='menu']").click();
    await page.getByRole("menuitem", { name: "Rename", exact: true }).click();
    await page.getByPlaceholder("Enter a name", { exact: true }).fill(renamedNames[index]);
  }));
  await Promise.all(pagesUnderTest.map((page) => page.getByRole("button", { name: "Save", exact: true }).click()));
  for (const page of pagesUnderTest) {
    for (const name of renamedNames) await page.getByText(name, { exact: true }).waitFor({ timeout: 30000 });
  }
  const persistedResponse = await requestApi(credentials, credentials.users[0], `/board/${credentials.project_uid}/columns`);
  const persisted = (await persistedResponse.json()).columns;
  for (const [index, column] of targetColumns.entries()) {
    assert.equal(persisted.find((item) => item.uid === column.uid)?.name, renamedNames[index]);
  }
  for (const page of pagesUnderTest) {
    await page.reload({ waitUntil: "domcontentloaded" });
    for (const name of renamedNames) await page.getByText(name, { exact: true }).waitFor({ timeout: 30000 });
  }
  steps.push("two-distinct-users-concurrent-column-renames-persisted-and-fanned-out-to-both-boards");
}

async function assertConcurrentCardDetails(owner, peer, credentials) {
  const pagesUnderTest = [owner, peer];
  const title = `Concurrent card title ${runId}`;
  const description = `Concurrent card description ${runId}`;
  const cardUrl = `${origin}/board/${credentials.project_uid}/${credentials.card_uid}`;
  await Promise.all(pagesUnderTest.map(async (page) => {
    await page.goto(cardUrl, { waitUntil: "networkidle" });
    await page.getByText("No description", { exact: true }).waitFor();
    await page.getByRole("button", { name: "Edit", exact: true }).last().click();
    await page.getByRole("button", { name: "Save", exact: true }).waitFor();
  }));
  const cardDialog = pagesUnderTest[0].locator('[data-dialog-content="true"]');
  await cardDialog.getByText(credentials.card_title, { exact: true }).first().click();
  const titleInput = cardDialog.locator('textarea:visible').first();
  await titleInput.waitFor();
  await titleInput.fill(title);
  await pagesUnderTest[1].locator("[data-card-description]").click();
  const descriptionEditor = pagesUnderTest[1].locator('[data-card-description] [data-slate-editor="true"]:visible');
  await descriptionEditor.waitFor();
  await descriptionEditor.fill(description);
  const beforeSave = await Promise.all(pagesUnderTest.map((page) => page.evaluate(() => ({
    buttons: [...document.querySelectorAll("button")].filter((button) => ["Edit", "Save"].includes(button.textContent?.trim())).map((button) => button.textContent?.trim()),
    title: document.querySelector("textarea")?.value,
    editor: document.querySelector('[data-card-description] [data-slate-editor="true"]')?.textContent,
  }))));
  assert.ok(beforeSave.every((state) => state.buttons.includes("Save")), JSON.stringify(beforeSave));
  const detailPath = `/board/${credentials.project_uid}/card/${credentials.card_uid}/details`;
  const requests = [];
  for (const [index, page] of pagesUnderTest.entries()) {
    page.on("request", (request) => {
      if (request.method() === "PUT" && request.url().includes(detailPath)) {
        requests.push({ user: index, body: request.postDataJSON() });
      }
    });
  }
  const responsePromises = pagesUnderTest.map((page) => page.waitForResponse((response) =>
    response.request().method() === "PUT" && response.url().includes(detailPath), { timeout: 15000 })
    .catch((error) => error));
  await Promise.all(pagesUnderTest.map((page) => page.getByRole("button", { name: "Save", exact: true }).click()));
  const responses = await Promise.all(responsePromises);
  if (responses.some((response) => response instanceof Error)) {
    const states = await Promise.all(pagesUnderTest.map((page) => page.evaluate(() => ({
      editButtons: [...document.querySelectorAll("button")].filter((button) => ["Edit", "Save"].includes(button.textContent?.trim())).map((button) => button.textContent?.trim()),
      title: document.querySelector("textarea")?.value,
      editor: document.querySelector('[data-card-description] [data-slate-editor="true"]')?.textContent,
      alerts: [...document.querySelectorAll('[role="status"], [role="alert"]')].map((element) => element.textContent),
    }))));
    throw new Error(`Card save did not issue two responses: ${JSON.stringify({ requests, states, errors: responses.filter((response) => response instanceof Error).map(String) })}`);
  }
  assert.deepEqual(responses.map((response) => response.status()), [200, 200]);
  for (const page of pagesUnderTest) {
    await page.getByText(title, { exact: true }).first().waitFor({ timeout: 30000 });
    await page.getByText(description, { exact: true }).first().waitFor({ timeout: 30000 });
  }
  const persistedResponse = await requestApi(credentials, credentials.users[0], `/board/${credentials.project_uid}/card/${credentials.card_uid}`);
  const { card } = await persistedResponse.json();
  assert.equal(card.title, title);
  assert.ok(card.description?.content?.includes(description), JSON.stringify({ requests, description: card.description }));
  for (const page of pagesUnderTest) {
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByText(title, { exact: true }).first().waitFor({ timeout: 30000 });
    await page.getByText(description, { exact: true }).first().waitFor({ timeout: 30000 });
  }
  steps.push("two-distinct-users-concurrent-same-card-title-and-description-preserved-after-reload");
}

async function assertTwoUserCardDrag(owner, peer, credentials) {
  const cardPath = `/board/${credentials.project_uid}/card/${credentials.card_uid}`;
  const cardResponse = await requestApi(credentials, credentials.users[0], cardPath);
  const originalColumnUID = (await cardResponse.json()).card.project_column_uid;
  const columnResponse = await requestApi(credentials, credentials.users[0], `/board/${credentials.project_uid}/column`, {
    method: "POST",
    body: JSON.stringify({ name: `Drag destination ${runId}` }),
  });
  assert.equal(columnResponse.status, 201);
  const destinationUID = (await columnResponse.json()).column.uid;
  const card = (page) => page.locator(`[data-board-card-touch-dnd-uid="${credentials.card_uid}"]`);
  const column = (page, uid) => page.locator(`[data-board-column-touch-dnd-uid="${uid}"]`);
  await Promise.all([owner, peer].map(async (page) => {
    await page.setViewportSize({ width: 1920, height: 900 });
    await page.goto(`${origin}/board/${credentials.project_uid}`, { waitUntil: "networkidle" });
    await waitForBoardSocketReady(page, credentials.project_uid);
    if (await page.getByPlaceholder("Enter a message", { exact: true }).isVisible()) {
      await page.getByRole("button", { name: "Chat with AI", exact: true }).click();
      await page.getByPlaceholder("Enter a message", { exact: true }).waitFor({ state: "hidden" });
    }
    await card(page).waitFor();
    await column(page, destinationUID).waitFor();
  }));
  for (const [actor, observer, targetUID] of [
    [owner, peer, destinationUID],
    [peer, owner, originalColumnUID],
  ]) {
    const responsePromise = actor.waitForResponse((response) => response.request().method() === "PUT" &&
      response.url().includes(`${cardPath}/order`), { timeout: 30000 }).catch((error) => error);
    await card(actor).locator(":scope > div").first().dragTo(column(actor, targetUID), {
      sourcePosition: { x: 100, y: 30 },
      targetPosition: { x: 100, y: 60 },
    });
    const response = await responsePromise;
    if (response instanceof Error) {
      const state = await actor.evaluate(() => ({
        dragging: [...document.querySelectorAll('[data-board-card-touch-dnd-uid]')].map((element) => ({
          uid: element.getAttribute("data-board-card-touch-dnd-uid"),
          text: element.textContent?.slice(0, 80),
        })),
        alerts: [...document.querySelectorAll('[role="alert"], [role="status"]')].map((element) => element.textContent),
      }));
      throw new Error(`Card drag did not send order update to ${targetUID}: ${JSON.stringify(state)}`);
    }
    assert.equal(response.status(), 200);
    await observer.waitForFunction(({ cardUID, columnUID }) =>
      document.querySelector(`[data-board-column-touch-dnd-uid="${columnUID}"]`)
        ?.querySelector(`[data-board-card-touch-dnd-uid="${cardUID}"]`) !== null,
    { cardUID: credentials.card_uid, columnUID: targetUID }, { timeout: 30000 });
    const persisted = await requestApi(credentials, credentials.users[0], cardPath);
    assert.equal((await persisted.json()).card.project_column_uid, targetUID);
  }
  for (const page of [owner, peer]) {
    await page.reload({ waitUntil: "domcontentloaded" });
    await column(page, originalColumnUID).locator(`[data-board-card-touch-dnd-uid="${credentials.card_uid}"]`)
      .waitFor({ timeout: 30000 });
  }
  steps.push("two-distinct-users-bidirectional-card-drag-fanned-out-persisted-and-survived-reload");
}

async function assertTwoUserCardArchive(owner, peer, credentials) {
  const cardPath = `/board/${credentials.project_uid}/card/${credentials.card_uid}`;
  const boardResponse = await requestApi(credentials, credentials.users[0], `/board/${credentials.project_uid}/cards`);
  const archiveUID = (await boardResponse.json()).columns.find((column) => column.is_archive)?.uid;
  assert.ok(archiveUID);
  await Promise.all([
    owner.goto(`${origin}/board/${credentials.project_uid}/${credentials.card_uid}`, { waitUntil: "networkidle" }),
    peer.goto(`${origin}/board/${credentials.project_uid}`, { waitUntil: "networkidle" }),
  ]);
  await waitForBoardSocketReady(peer, credentials.project_uid);
  const peerCard = peer.locator(`[data-board-card-touch-dnd-uid="${credentials.card_uid}"]`);
  await peerCard.waitFor();
  await owner.getByRole("button", { name: "Actions", exact: true }).last().click();
  await owner.getByRole("button", { name: "Archive card", exact: true }).click();
  const responsePromise = owner.waitForResponse((response) => response.request().method() === "PUT" &&
    response.url().includes(`${cardPath}/archive`), { timeout: 30000 });
  await owner.getByRole("button", { name: "Archive", exact: true }).click();
  assert.equal((await responsePromise).status(), 200);
  await peer.locator(`[data-board-column-touch-dnd-uid="${archiveUID}"]`)
    .locator(`[data-board-card-touch-dnd-uid="${credentials.card_uid}"]`)
    .waitFor({ timeout: 30000 });
  const persisted = await requestApi(credentials, credentials.users[0], cardPath);
  const archived = (await persisted.json()).card;
  assert.equal(archived.project_column_uid, archiveUID);
  assert.ok(archived.archived_at);
  await peer.reload({ waitUntil: "domcontentloaded" });
  await peer.locator(`[data-board-column-touch-dnd-uid="${archiveUID}"]`)
    .locator(`[data-board-card-touch-dnd-uid="${credentials.card_uid}"]`)
    .waitFor({ timeout: 30000 });
  steps.push("two-distinct-users-card-archive-button-fanned-out-and-persisted-after-reload");
}

async function assertTwoUserCardRelationship(owner, peer, credentials) {
  const cardPath = `/board/${credentials.project_uid}/card/${credentials.card_uid}`;
  const board = await requestApi(credentials, credentials.users[0], `/board/${credentials.project_uid}/cards`);
  const columnUID = (await board.json()).columns.find((column) => column.name === "Editor verification")?.uid;
  assert.ok(columnUID);
  const candidateTitle = `Concurrent related card ${runId}`;
  const candidateResponse = await requestApi(credentials, credentials.users[0],
    `/board/${credentials.project_uid}/card`, {
      method: "POST",
      body: JSON.stringify({ title: candidateTitle, project_column_uid: columnUID }),
    });
  const candidateUID = (await candidateResponse.json()).card.uid;
  const relationshipType = credentials.relationship_type_uid;
  assert.ok(relationshipType);
  await Promise.all([owner, peer].map(async (page) => {
    await page.goto(`${origin}/board/${credentials.project_uid}/${credentials.card_uid}`, { waitUntil: "networkidle" });
    await waitForBoardSocketReady(page, credentials.project_uid);
    await page.locator('[data-dialog-content="true"] button:has(svg.lucide-git-fork)').first().waitFor();
  }));
  const parentButton = (page) => page.locator('[data-dialog-content="true"] button:has(svg.lucide-git-fork)').first();
  await parentButton(owner).click();
  await owner.getByRole("button", { name: "Select cards", exact: true }).click();
  await owner.locator(`[data-board-card-touch-dnd-uid="${candidateUID}"] #board-card-${candidateUID}`).click();
  const picker = owner.getByRole("dialog").last();
  await picker.getByRole("button", { name: `Migration parent ${runId}`, exact: true }).click();
  await picker.getByRole("button", { name: "Save", exact: true }).click();
  const saved = owner.waitForResponse((response) => response.request().method() === "PUT" &&
    response.url().includes(`${cardPath}/relationships`), { timeout: 30000 });
  await owner.getByRole("button", { name: "Save", exact: true }).click();
  assert.equal((await saved).status(), 200);
  const relatedTitle = peer.getByRole("button", { name: `Migration parent ${runId} > ${candidateTitle}` });
  await parentButton(peer).click();
  await relatedTitle.waitFor({ timeout: 30000 });
  const persisted = await requestApi(credentials, credentials.users[0], cardPath);
  const relationships = (await persisted.json()).card.relationships;
  assert.ok(relationships.some((relationship) => relationship.parent_card_uid === candidateUID &&
    relationship.child_card_uid === credentials.card_uid && relationship.relationship_type_uid === relationshipType));
  await peer.reload({ waitUntil: "domcontentloaded" });
  await parentButton(peer).click();
  await relatedTitle.waitFor({ timeout: 30000 });
  steps.push("two-distinct-users-card-relationship-selection-fanned-out-and-persisted-after-reload");
}

async function assertTwoUserCardMemberAssignment(owner, peer, credentials) {
  const cardPath = `/board/${credentials.project_uid}/card/${credentials.card_uid}`;
  await Promise.all([owner, peer].map(async (page) => {
    await page.goto(`${origin}/board/${credentials.project_uid}/${credentials.card_uid}`, { waitUntil: "networkidle" });
    await page.locator('[data-dialog-content="true"]')
      .getByText("Members", { exact: true }).waitFor();
  }));
  await owner.getByRole("button", { name: "Edit", exact: true }).last().click();
  await owner.locator('[data-dialog-content="true"]')
    .getByText("Members", { exact: true }).locator("xpath=..").locator("button").first().click();
  await owner.locator('[data-radix-popper-content-wrapper] [data-slate-editor="true"]:visible')
    .last().fill(credentials.users[1].name.split(" ").at(-1));
  const requests = [];
  owner.on("request", (request) => {
    if (request.url().includes("assigned-users")) requests.push({ method: request.method(), url: request.url(), body: request.postData() });
  });
  const responsePromise = owner.waitForResponse((response) => response.request().method() === "PUT" &&
    response.url().includes(`${cardPath}/assigned-users`), { timeout: 30000 }).catch((error) => error);
  await owner.getByRole("option", { name: credentials.users[1].name, exact: true }).click();
  const response = await responsePromise;
  if (response instanceof Error) {
    const state = await owner.evaluate(() => ({
      selected: [...document.querySelectorAll('[data-avatar-user]')].map((element) => element.getAttribute("data-avatar-user")),
      popover: [...document.querySelectorAll('[data-radix-popper-content-wrapper]')].map((element) => element.textContent?.slice(0, 200)),
    }));
    throw new Error(`Card member selection sent no update: ${JSON.stringify({ requests, state })}`);
  }
  assert.equal(response.status(), 200);
  const peerAvatar = peer.locator('[data-dialog-content="true"]')
    .locator(`[data-avatar-user="${credentials.users[1].uid}"]`).first();
  await peerAvatar.waitFor({ timeout: 30000 });
  const persisted = await requestApi(credentials, credentials.users[0], cardPath);
  assert.ok((await persisted.json()).card.member_uids.includes(credentials.users[1].uid));
  await peer.reload({ waitUntil: "domcontentloaded" });
  await peerAvatar.waitFor({ timeout: 30000 });
  steps.push("two-distinct-users-card-member-assignment-persisted-and-visible-after-reload");
}

async function assertConcurrentProjectSettings(owner, peer, credentials) {
  const pagesUnderTest = [owner, peer];
  const description = `Concurrent project description ${runId}`;
  const saveRequests = [];
  for (const [index, page] of pagesUnderTest.entries()) {
    page.on("request", (request) => {
      if (request.method() === "PUT" && request.url().includes(`/board/${credentials.project_uid}/settings/details`)) {
        saveRequests.push({ user: index, body: request.postDataJSON() });
      }
    });
  }
  await Promise.all(pagesUnderTest.map(async (page) => {
    await page.goto(`${origin}/board/${credentials.project_uid}/settings`, { waitUntil: "networkidle" });
    await page.locator('form input[name="title"]').waitFor();
  }));
  const forms = pagesUnderTest.map((page) => page.locator("form")
    .filter({ has: page.locator('input[name="title"]') }));
  const initialDays = await Promise.all(forms.map((form) =>
    form.locator('input[name="archive_visible_days"]').inputValue()));
  const originalDays = Number(initialDays[0]);
  const changedDays = originalDays + 1;
  await Promise.all(forms.map((form) => form.getByRole("button", { name: "Edit", exact: true }).click()));
  await Promise.all(forms.map((form) => form.getByRole("button", { name: "Save", exact: true }).waitFor()));
  await Promise.all(pagesUnderTest.map((page) => page.waitForFunction(() =>
    ["title", "description", "archive_visible_days"].every((name) => {
      const input = document.querySelector(`[name="${name}"]`);
      return input && !input.disabled;
    }),
  )));
  await Promise.all([
    forms[0].locator('textarea[name="description"]').fill(description),
    forms[1].locator('input[name="archive_visible_days"]').fill(String(changedDays)),
  ]);
  try {
    await Promise.all(pagesUnderTest.map((page) => page.waitForFunction(
      ({ description, days }) =>
        document.querySelector('textarea[name="description"]')?.value === description &&
        document.querySelector('input[name="archive_visible_days"]')?.value === String(days),
      { description, days: changedDays },
      { timeout: 10000 },
    )));
  } catch (error) {
    const values = await Promise.all(pagesUnderTest.map((page) => page.evaluate(() => ({
      description: document.querySelector('textarea[name="description"]')?.value,
      days: document.querySelector('input[name="archive_visible_days"]')?.value,
    }))));
    throw new Error(`${error}\nInitial days: ${JSON.stringify(initialDays)}; expected days: ${changedDays}; collaborative settings values: ${JSON.stringify(values)}`);
  }
  const saveResponses = await Promise.all(pagesUnderTest.map(async (page, index) => {
    const responsePromise = page.waitForResponse((response) => response.request().method() === "PUT" &&
      response.url().includes(`/board/${credentials.project_uid}/settings/details`));
    await forms[index].getByRole("button", { name: "Save", exact: true }).click();
    return responsePromise;
  }));
  assert.deepEqual(saveResponses.map((response) => response.status()), [200, 200]);
  const response = await requestApi(credentials, credentials.users[0], `/board/${credentials.project_uid}/details`);
  const { project } = await response.json();
  assert.equal(project.description, description, JSON.stringify({ initialDays, saveRequests, description: project.description, archive_visible_days: project.archive_visible_days }));
  assert.equal(project.archive_visible_days, changedDays, JSON.stringify({ initialDays, saveRequests, description: project.description, archive_visible_days: project.archive_visible_days }));
  for (const page of pagesUnderTest) {
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      ({ description, days }) =>
        document.querySelector('textarea[name="description"]')?.value === description &&
        document.querySelector('input[name="archive_visible_days"]')?.value === String(days),
      { description, days: changedDays },
      { timeout: 30000 },
    );
  }
  steps.push("two-distinct-users-concurrent-project-settings-preserved-both-fields-after-reload");
}

async function assertConcurrentLabelCreation(owner, peer, credentials) {
  const pagesUnderTest = [owner, peer];
  const settingsUrl = `${origin}/board/${credentials.project_uid}/settings`;
  await Promise.all(pagesUnderTest.map(async (page) => {
    await page.goto(settingsUrl, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Add a label", exact: true }).waitFor();
  }));

  const labelPath = `/board/${credentials.project_uid}/settings/label`;
  const beforeResponse = await requestApi(credentials, credentials.users[0], `/board/${credentials.project_uid}/details`);
  const beforeCount = (await beforeResponse.json()).project.labels.filter((label) => label.name === "New Label").length;
  let arrivals = 0;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const holdBothPosts = async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    arrivals += 1;
    if (arrivals === 2) release();
    await gate;
    await route.continue();
  };
  for (const page of pagesUnderTest) {
    await page.route(`**${labelPath}`, holdBothPosts);
  }
  try {
    const responses = await Promise.all(pagesUnderTest.map(async (page) => {
      const responsePromise = page.waitForResponse((response) => response.request().method() === "POST" &&
        response.url().includes(labelPath));
      await page.getByRole("button", { name: "Add a label", exact: true }).click();
      return responsePromise;
    }));
    assert.deepEqual(responses.map((response) => response.status()), [201, 201]);
    await Promise.all(pagesUnderTest.map((page) => page.getByText("New Label", { exact: true })
      .and(page.locator(":visible")).nth(beforeCount + 1).waitFor({ timeout: 30000 })));
    const afterResponse = await requestApi(credentials, credentials.users[0], `/board/${credentials.project_uid}/details`);
    const afterCount = (await afterResponse.json()).project.labels.filter((label) => label.name === "New Label").length;
    assert.equal(afterCount, beforeCount + 2);
    steps.push("two-distinct-users-concurrent-label-creates-persisted-and-fanned-out-to-both-settings-pages");
  } finally {
    for (const page of pagesUnderTest) {
      await page.unroute(`**${labelPath}`, holdBothPosts);
    }
  }
}

async function assertConcurrentLabelDetails(owner, peer, credentials) {
  const pagesUnderTest = [owner, peer];
  const labelName = `Concurrent label ${runId}`;
  const newName = `Renamed label ${runId}`;
  const newDescription = `Concurrent label description ${runId}`;
  const labelPath = `/board/${credentials.project_uid}/settings/label`;
  const created = await requestApi(credentials, credentials.users[0], labelPath, {
    method: "POST",
    body: JSON.stringify({ name: labelName, color: "#228b72", description: "Original description" }),
  });
  assert.equal(created.status, 201);
  const labelUID = (await created.json()).label.uid;
  const detailPath = `${labelPath}/${labelUID}/details`;
  await Promise.all(pagesUnderTest.map(async (page) => {
    await page.goto(`${origin}/board/${credentials.project_uid}/settings`, { waitUntil: "networkidle" });
    await page.getByText(labelName, { exact: true }).first().waitFor();
  }));
  await Promise.all(pagesUnderTest.map(async (page, index) => {
    const row = page.getByText(labelName, { exact: true }).first().locator("xpath=ancestor::div[contains(@class,'relative')][1]");
    await row.getByRole("button", { name: "More", exact: true }).click();
    await page.getByRole("menuitem", { name: index === 0 ? "Rename" : "Change description" }).click();
    await page.getByPlaceholder(index === 0 ? "Label name" : "Description", { exact: true })
      .fill(index === 0 ? newName : newDescription);
  }));
  const requests = [];
  for (const [index, page] of pagesUnderTest.entries()) {
    page.on("request", (request) => {
      if (request.method() === "PUT" && request.url().includes(detailPath)) {
        requests.push({ user: index, body: request.postDataJSON() });
      }
    });
  }
  const responses = pagesUnderTest.map((page) => page.waitForResponse((response) =>
    response.request().method() === "PUT" && response.url().includes(detailPath), { timeout: 30000 }));
  await Promise.all(pagesUnderTest.map((page) => page.getByRole("button", { name: "Save", exact: true }).click()));
  assert.deepEqual((await Promise.all(responses)).map((response) => response.status()), [200, 200]);
  assert.ok(requests.some((request) => request.user === 0 && request.body.name === newName), JSON.stringify(requests));
  assert.ok(requests.some((request) => request.user === 1 && request.body.description === newDescription), JSON.stringify(requests));
  const detailResponse = await requestApi(credentials, credentials.users[0], `/board/${credentials.project_uid}/details`);
  const label = (await detailResponse.json()).project.labels.find((item) => item.uid === labelUID);
  assert.equal(label?.name, newName);
  assert.equal(label?.description, newDescription);
  for (const page of pagesUnderTest) {
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByText(newName, { exact: true }).first().waitFor({ timeout: 30000 });
    await page.getByText(newDescription, { exact: true }).first().waitFor({ timeout: 30000 });
  }
  steps.push("two-distinct-users-concurrent-same-label-name-and-description-preserved-after-reload");
}

async function assertConcurrentWikiCreation(owner, peer, credentials) {
  const pagesUnderTest = [owner, peer];
  const createPath = `/board/${credentials.project_uid}/wiki`;
  for (const page of pagesUnderTest) {
    await page.goto(`${origin}/board/${credentials.project_uid}/wiki`, {
      waitUntil: "domcontentloaded",
    });
    await page.locator(`#board-wiki-${credentials.wiki_uid}-tab`).waitFor();
    await page.locator("button:has(svg.lucide-plus):visible").last().waitFor();
  }
  let arrivals = 0;
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const holdBothPosts = async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    arrivals += 1;
    if (arrivals === 2) release();
    await gate;
    await route.continue();
  };
  for (const page of pagesUnderTest) {
    await page.route(`**${createPath}`, holdBothPosts);
  }
  let timeout;
  try {
    await Promise.all(
      pagesUnderTest.map((page) =>
        page.locator("button:has(svg.lucide-plus):visible").last().click(),
      ),
    );
    await Promise.race([
      gate,
      new Promise((_, reject) => {
        timeout = setTimeout(
          () => reject(new Error(`Only ${arrivals}/2 wiki POSTs arrived`)),
          15000,
        );
      }),
    ]);
  } finally {
    clearTimeout(timeout);
    release();
    for (const page of pagesUnderTest) {
      await page.unroute(`**${createPath}`, holdBothPosts);
    }
  }
  assert.equal(arrivals, 2);
  for (const page of pagesUnderTest) {
    await page.waitForFunction(
      () => [...document.querySelectorAll("[id^='board-wiki-'][id$='-tab']")]
        .filter((tab) => tab.textContent?.includes("New page")).length === 2,
    );
  }
  const response = await requestApi(credentials, credentials.users[0], `/board/${credentials.project_uid}/wikis`);
  const { wikis } = await response.json();
  assert.equal(wikis.filter((wiki) => wiki.title === "New page").length, 2);
  for (const page of pagesUnderTest) {
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      () => [...document.querySelectorAll("[id^='board-wiki-'][id$='-tab']")]
        .filter((tab) => tab.textContent?.includes("New page")).length === 2,
    );
  }
  steps.push("two-distinct-users-overlapping-wiki-creates-persisted-once-and-fanned-out-to-both-tabs");
}

async function assertConcurrentWikiDetails(owner, peer, credentials) {
  const pagesUnderTest = [owner, peer];
  const title = `Concurrent wiki title ${runId}`;
  const content = `Concurrent wiki content ${runId}`;
  const detailsPath = `/board/${credentials.project_uid}/wiki/${credentials.wiki_uid}/details`;
  await Promise.all(pagesUnderTest.map(async (page) => {
    await page.goto(`${origin}/board/${credentials.project_uid}/wiki`, { waitUntil: "networkidle" });
    await page.locator(`#board-wiki-${credentials.wiki_uid}-tab`).click();
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await page.getByRole("button", { name: "Save", exact: true }).waitFor();
  }));
  await owner.locator("h1 span").filter({ hasText: `Migration wiki ${runId}` }).click();
  await owner.locator("textarea:visible:enabled:not([placeholder])").fill(title);
  await peer.locator("[data-wiki-content]").click();
  const editor = peer.locator('[data-wiki-content] [data-slate-editor="true"]:visible');
  await editor.waitFor();
  await editor.click();
  await peer.keyboard.press("ControlOrMeta+A");
  await editor.pressSequentially(content, { delay: 10 });
  await peer.waitForFunction((expected) => document.querySelector('[data-wiki-content] [data-slate-editor="true"]')?.textContent?.includes(expected), content);
  const beforeSave = await Promise.all(pagesUnderTest.map((page) => page.evaluate(() => ({
    buttons: [...document.querySelectorAll("button")].filter((button) => ["Edit", "Save"].includes(button.textContent?.trim())).map((button) => button.textContent?.trim()),
    title: document.querySelector("textarea:not([placeholder])")?.value,
    content: document.querySelector('[data-wiki-content] [data-slate-editor="true"]')?.textContent,
  }))));
  assert.ok(beforeSave.every((state) => state.buttons.includes("Save")), JSON.stringify(beforeSave));
  const requests = [];
  for (const [index, page] of pagesUnderTest.entries()) {
    page.on("request", (request) => {
      if (request.method() === "PUT" && request.url().includes(detailsPath)) {
        requests.push({ user: index, body: request.postDataJSON() });
      }
    });
  }
  const responses = pagesUnderTest.map((page) => page.waitForResponse((response) =>
    response.request().method() === "PUT" && response.url().includes(detailsPath), { timeout: 30000 }).catch((error) => error));
  await Promise.all(pagesUnderTest.map((page) => page.getByRole("button", { name: "Save", exact: true }).click()));
  const results = await Promise.all(responses);
  if (results.some((result) => result instanceof Error)) {
    throw new Error(`Wiki save did not issue two responses: ${JSON.stringify({ beforeSave, requests, errors: results.filter((result) => result instanceof Error).map(String) })}`);
  }
  assert.deepEqual(results.map((response) => response.status()), [200, 200]);
  assert.ok(requests.some((request) => request.user === 0 && request.body.title === title), JSON.stringify(requests));
  assert.ok(requests.some((request) => request.user === 1 && request.body.content?.content?.includes(content)), JSON.stringify(requests));
  const response = await requestApi(credentials, credentials.users[0], `/board/${credentials.project_uid}/wiki/${credentials.wiki_uid}`);
  const { wiki } = await response.json();
  assert.equal(wiki.title, title);
  assert.ok(wiki.content?.content?.includes(content));
  for (const page of pagesUnderTest) {
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.locator(`#board-wiki-${credentials.wiki_uid}-tab`).click();
    await page.getByText(title, { exact: true }).first().waitFor();
    await page.getByText(content, { exact: true }).first().waitFor();
  }
  steps.push("two-distinct-users-concurrent-same-wiki-title-and-content-preserved-after-reload");
}

async function assertCardCommentRealtimeLifecycle(owner, peer, credentials) {
  const commentButton = peer.getByRole("button", {
    name: "Comments",
    exact: true,
  });
  if ((await commentButton.getAttribute("aria-pressed")) !== "true") {
    await commentButton.click();
  }
  try {
    await peer.waitForFunction(() =>
      [...document.querySelectorAll("button")].some(
        (button) =>
          button.textContent?.includes("Comments") &&
          button.getAttribute("aria-pressed") === "true",
      ),
    );
  } catch (error) {
    const buttons = await peer.locator("button").evaluateAll((nodes) =>
      nodes
        .filter((node) => node.textContent?.includes("Comments"))
        .map((node) => ({
          text: node.textContent,
          pressed: node.getAttribute("aria-pressed"),
        })),
    );
    throw new Error(`Comments did not open: ${JSON.stringify({ buttons })}`, {
      cause: error,
    });
  }
  await peer.evaluate(() => {
    window.__commentInitialButton = [
      ...document.querySelectorAll("button"),
    ].find((button) => button.textContent?.trim() === "Comments");
    window.__commentInitialCard = document.querySelector(
      "[data-dialog-content]",
    );
    window.__commentInitialMain = document.querySelector("main");
  });
  await peer.setViewportSize({ width: 800, height: 844 });
  try {
    await peer
      .getByText(`Add a comment as ${credentials.users[1].name}`, {
        exact: true,
      })
      .and(peer.locator(":visible"))
      .waitFor();
  } catch (error) {
    const state = await peer.evaluate(() => ({
      mainConnected: window.__commentInitialMain?.isConnected,
      cardConnected: window.__commentInitialCard?.isConnected,
      initialButtonConnected: window.__commentInitialButton?.isConnected,
      pressed: [...document.querySelectorAll("button")]
        .filter((button) => button.textContent?.trim() === "Comments")
        .map((button) => button.getAttribute("aria-pressed")),
      forms: [...document.querySelectorAll("form")].map((form) => ({
        visible: form.getClientRects().length > 0,
        text: form.textContent?.slice(0, 100),
      })),
    }));
    throw new Error(`Desktop comment composer did not render: ${JSON.stringify(state)}`, { cause: error });
  }
  await peer.setViewportSize({ width: 390, height: 844 });
  try {
    await peer
      .getByText(`Add a comment as ${credentials.users[1].name}`, {
        exact: true,
      })
      .and(peer.locator(":visible"))
      .waitFor();
  } catch (error) {
    const state = await peer.evaluate(() => ({
      viewportWidth: window.innerWidth,
      mainConnected: window.__commentInitialMain?.isConnected,
      desktopComments: window.matchMedia("(min-width: 768px)").matches,
      mobileForm: [...document.querySelectorAll("form")].map((form) => ({
        visible: form.getClientRects().length > 0,
        text: form.textContent?.slice(0, 100),
      })),
      commentSections: [...document.querySelectorAll("*")]
        .filter((element) => element.textContent?.trim() === "Comments")
        .slice(-8)
        .map((element) => ({
          tag: element.tagName,
          visible: element.getClientRects().length > 0,
        })),
    }));
    throw new Error(
      `Card comment composer did not render: ${JSON.stringify(state)}`,
      {
        cause: error,
      },
    );
  }
  try {
    await peer
      .getByText("No comments", { exact: true })
      .and(peer.locator(":visible"))
      .waitFor();
  } catch (error) {
    const state = await peer.evaluate(() => ({
      viewportWidth: window.innerWidth,
      mobileMedia: window.matchMedia("(max-width: 767px)").matches,
      mainConnected: window.__commentInitialMain?.isConnected,
      pressed: [...document.querySelectorAll("button")]
        .filter((button) => button.textContent?.trim() === "Comments")
        .map((button) => button.getAttribute("aria-pressed")),
      comments: [...document.querySelectorAll("*")]
        .filter((element) => element.textContent?.trim() === "No comments")
        .map((element) => ({
          tag: element.tagName,
          visible: element.getClientRects().length > 0,
          className: element.className,
        })),
      cardSections: [...document.querySelectorAll("*")]
        .filter((element) => element.textContent?.trim() === "Comments")
        .slice(-8)
        .map((element) => ({
          tag: element.tagName,
          visible: element.getClientRects().length > 0,
          className: element.className,
          parentClassName: element.parentElement?.className,
        })),
    }));
    throw new Error(`Comments list did not render: ${JSON.stringify(state)}`, {
      cause: error,
    });
  }
  await peer.evaluate(() => {
    window.__commentClickObserver?.disconnect();
    window.__commentClickAbortController?.abort();
    const commentsButton = [...document.querySelectorAll("button")].find(
      (button) =>
        button.textContent?.trim() === "Comments" &&
        button.hasAttribute("aria-pressed"),
    );
    window.__commentClickTrace = [];
    const controller = new AbortController();
    window.__commentClickAbortController = controller;
    const record = (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      window.__commentClickTrace.push({
        type: event.type,
        target: target.closest("button, [role='button']")?.textContent?.trim(),
        pressed: commentsButton?.getAttribute("aria-pressed"),
      });
    };
    document.addEventListener("pointerdown", record, {
      capture: true,
      once: true,
      signal: controller.signal,
    });
    document.addEventListener("click", record, {
      capture: true,
      once: true,
      signal: controller.signal,
    });
    if (commentsButton) {
      const observer = new MutationObserver(() => {
        window.__commentClickTrace.push({
          type: "comments-state",
          pressed: commentsButton.getAttribute("aria-pressed"),
          connected: commentsButton.isConnected,
        });
      });
      observer.observe(commentsButton, {
        attributes: true,
        attributeFilter: ["aria-pressed"],
      });
      window.__commentClickObserver = observer;
    }
  });
  try {
    await peer
      .getByText(`Add a comment as ${credentials.users[1].name}`, {
        exact: true,
      })
      .and(peer.locator(":visible"))
      .click();
  } catch (error) {
    const state = await peer.evaluate(() => ({
      trace: window.__commentClickTrace,
      buttonConnected: window.__commentInitialButton?.isConnected,
      cardConnected: window.__commentInitialCard?.isConnected,
      mainConnected: window.__commentInitialMain?.isConnected,
      commentsPressed: [...document.querySelectorAll("button")]
        .filter((button) => button.textContent?.trim() === "Comments")
        .map((button) => button.getAttribute("aria-pressed")),
      mobileComposer: [...document.querySelectorAll("[role='button']")]
        .filter((element) => element.textContent?.includes("Add a comment as"))
        .map((element) => ({
          visible: element.getClientRects().length > 0,
          connected: element.isConnected,
        })),
    }));
    await peer.evaluate(() => {
      window.__commentClickObserver?.disconnect();
      window.__commentClickAbortController?.abort();
    });
    throw new Error(
      `Card comment composer click failed: ${JSON.stringify(state)}`,
      { cause: error },
    );
  }
  await peer.evaluate(() => {
    window.__commentClickObserver?.disconnect();
    window.__commentClickAbortController?.abort();
  });
  const commentEditors = peer.locator(
    '[data-card-comment-form] [data-slate-editor="true"]',
  );
  try {
    await commentEditors.first().waitFor({ state: "visible" });
  } catch (error) {
    const state = await peer.evaluate(() => ({
      buttonConnected: window.__commentInitialButton?.isConnected,
      cardConnected: window.__commentInitialCard?.isConnected,
      mainConnected: window.__commentInitialMain?.isConnected,
      pressed: [...document.querySelectorAll("button")]
        .filter((button) => button.textContent?.trim() === "Comments")
        .map((button) => button.getAttribute("aria-pressed")),
    }));
    throw new Error(
      `Card comment editor did not open: ${JSON.stringify(state)}`,
      { cause: error },
    );
  }
  assert.equal(await commentEditors.count(), 1);
  await peer
    .getByRole("button", { name: "Cancel", exact: true })
    .and(peer.locator(":visible"))
    .click();

  const addedText = `Realtime comment ${runId}`;
  const updatedText = `Updated realtime comment ${runId}`;
  const addedOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await requestApi(
    credentials,
    credentials.users[0],
    `/board/${credentials.project_uid}/card/${credentials.card_uid}/comment`,
    {
      method: "POST",
      body: JSON.stringify({ content: addedText }),
    },
  );
  await Promise.all(
    [owner, peer].map((page, index) =>
      waitForCardCommentEvent(
        page,
        addedOffsets[index],
        "board:card:comment:added",
        credentials.card_uid,
      ),
    ),
  );
  const commentUID = await peer.evaluate(
    ({ offset, cardUID }) =>
      window.__chatFrames
        .slice(offset)
        .find((frame) => frame.event === `board:card:comment:added:${cardUID}`)
        ?.data?.comment?.uid,
    { offset: addedOffsets[1], cardUID: credentials.card_uid },
  );
  assert.match(commentUID || "", /^[A-Za-z0-9_-]+$/);
  if ((await commentButton.getAttribute("aria-pressed")) !== "true") {
    await commentButton.click();
  }
  try {
    await waitForVisibleSlateText(peer, addedText);
  } catch (error) {
    const diagnostics = await peer.evaluate(() => ({
      viewportWidth: window.innerWidth,
      desktopComments: window.matchMedia("(min-width: 768px)").matches,
      commentButton: [...document.querySelectorAll("button")]
        .filter((button) => button.getAttribute("aria-label") === "Comments")
        .map((button) => button.getAttribute("aria-pressed")),
      slateText: [...document.querySelectorAll('[data-slate-string="true"]')]
        .map((element) => element.textContent)
        .filter(Boolean),
      visibleText: document.body.innerText.slice(-1200),
    }));
    throw new Error(
      `Card comment did not render: ${JSON.stringify(diagnostics)}`,
      {
        cause: error,
      },
    );
  }
  steps.push("card-comment-add-fanned-out-and-rendered-without-refresh");

  const updatedOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await requestApi(
    credentials,
    credentials.users[0],
    `/board/${credentials.project_uid}/card/${credentials.card_uid}/comment/${commentUID}`,
    {
      method: "PUT",
      body: JSON.stringify({ content: updatedText }),
    },
  );
  await Promise.all(
    [owner, peer].map((page, index) =>
      waitForCardCommentEvent(
        page,
        updatedOffsets[index],
        "board:card:comment:updated",
        credentials.card_uid,
        commentUID,
      ),
    ),
  );
  await waitForVisibleSlateText(peer, updatedText);
  await waitForVisibleSlateText(peer, addedText, false);
  steps.push("card-comment-edit-fanned-out-and-rendered-without-refresh");

  const reactedOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await requestApi(
    credentials,
    credentials.users[1],
    `/board/${credentials.project_uid}/card/${credentials.card_uid}/comment/${commentUID}/react`,
    {
      method: "POST",
      body: JSON.stringify({ reaction: "thumbs-up" }),
    },
  );
  await Promise.all(
    [owner, peer].map((page, index) =>
      waitForCardCommentEvent(
        page,
        reactedOffsets[index],
        "board:card:comment:reacted",
        credentials.card_uid,
        commentUID,
      ),
    ),
  );
  await peer.waitForFunction(
    (expected) => {
      const content = [
        ...document.querySelectorAll('[data-slate-string="true"]'),
      ].find((element) => element.textContent === expected);
      const comment = content?.closest("div.grid");
      return [...(comment?.querySelectorAll("button") || [])].some(
        (button) =>
          button.textContent?.trim() === "1" &&
          button.getBoundingClientRect().height > 0,
      );
    },
    updatedText,
    { timeout: 30000 },
  );
  steps.push("card-comment-reaction-fanned-out-and-rendered-without-refresh");

  const deletedOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await requestApi(
    credentials,
    credentials.users[0],
    `/board/${credentials.project_uid}/card/${credentials.card_uid}/comment/${commentUID}`,
    { method: "DELETE" },
  );
  await Promise.all(
    [owner, peer].map((page, index) =>
      waitForCardCommentEvent(
        page,
        deletedOffsets[index],
        "board:card:comment:deleted",
        credentials.card_uid,
        commentUID,
      ),
    ),
  );
  await waitForVisibleSlateText(peer, updatedText, false);
  const persisted = await requestApi(
    credentials,
    credentials.users[1],
    `/board/${credentials.project_uid}/card/${credentials.card_uid}/comments`,
  );
  const persistedComments = await persisted.json();
  assert.deepEqual(persistedComments.comments, []);
  steps.push(
    "card-comment-delete-fanned-out-rendered-and-left-no-active-record",
  );
}

async function assertCardLabelRealtimeLifecycle(owner, peer, credentials) {
  const labelName = `Realtime label ${runId}`;
  const createdOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  const labelResponse = await requestApi(
    credentials,
    credentials.users[0],
    `/board/${credentials.project_uid}/settings/label`,
    {
      method: "POST",
      body: JSON.stringify({
        name: labelName,
        color: "#228b72",
        description: "Browser realtime verification",
      }),
    },
  );
  const labelUID = (await labelResponse.json()).label.uid;
  assert.match(labelUID || "", /^[A-Za-z0-9_-]+$/);
  await Promise.all(
    [owner, peer].map((page, index) =>
      page.waitForFunction(
        ({ offset, projectUID, labelUID }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event === `board:label:created:${projectUID}` &&
                frame.data?.label?.uid === labelUID,
            ),
        {
          offset: createdOffsets[index],
          projectUID: credentials.project_uid,
          labelUID,
        },
      ),
    ),
  );
  const offsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await requestApi(
    credentials,
    credentials.users[1],
    `/board/${credentials.project_uid}/card/${credentials.card_uid}/labels`,
    { method: "PUT", body: JSON.stringify({ labels: [labelUID] }) },
  );
  await Promise.all(
    [owner, peer].map((page, index) =>
      page.waitForFunction(
        ({ offset, cardUID, labelUID }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event === `board:card:labels:updated:${cardUID}` &&
                frame.data?.labels?.some((label) => label.uid === labelUID),
            ),
        { offset: offsets[index], cardUID: credentials.card_uid, labelUID },
      ),
    ),
  );
  await peer.getByText(labelName, { exact: true }).first().waitFor();
  const cardPath = `/board/${credentials.project_uid}/card/${credentials.card_uid}`;
  const assignedCard = await (
    await requestApi(credentials, credentials.users[0], cardPath)
  ).json();
  assert.ok(assignedCard.card.labels.some((label) => label.uid === labelUID));
  steps.push("card-label-add-fanned-out-rendered-and-persisted");

  const removedOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await requestApi(credentials, credentials.users[1], `${cardPath}/labels`, {
    method: "PUT",
    body: JSON.stringify({ labels: [] }),
  });
  await Promise.all(
    [owner, peer].map((page, index) =>
      page.waitForFunction(
        ({ offset, cardUID }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event === `board:card:labels:updated:${cardUID}` &&
                frame.data?.labels?.length === 0,
            ),
        { offset: removedOffsets[index], cardUID: credentials.card_uid },
      ),
    ),
  );
  await peer
    .getByText(labelName, { exact: true })
    .first()
    .waitFor({ state: "hidden" });
  const clearedCard = await (
    await requestApi(credentials, credentials.users[0], cardPath)
  ).json();
  assert.deepEqual(clearedCard.card.labels, []);
  steps.push("card-label-remove-fanned-out-rendered-and-persisted");
}

async function assertCardColumnMoveLifecycle(owner, peer, credentials) {
  const cardPath = `/board/${credentials.project_uid}/card/${credentials.card_uid}`;
  const original = (
    await (await requestApi(credentials, credentials.users[0], cardPath)).json()
  ).card;
  const originalColumnUID = original.project_column_uid;
  const destinationName = `Realtime destination ${runId}`;
  const destination = await (
    await requestApi(
      credentials,
      credentials.users[0],
      `/board/${credentials.project_uid}/column`,
      { method: "POST", body: JSON.stringify({ name: destinationName }) },
    )
  ).json();
  const destinationUID = destination.column.uid;
  const orderPath = `${cardPath}/order`;

  const sameColumnOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await requestApi(credentials, credentials.users[0], orderPath, {
    method: "PUT",
    body: JSON.stringify({
      order: original.order,
      parent_uid: originalColumnUID,
    }),
  });
  await Promise.all(
    [owner, peer].map((page, index) =>
      page.waitForFunction(
        ({ offset, columnUID, cardUID }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event === `board:card:order:changed:${columnUID}` &&
                frame.data?.uid === cardUID &&
                frame.data?.move_type === "in_column",
            ),
        {
          offset: sameColumnOffsets[index],
          columnUID: originalColumnUID,
          cardUID: credentials.card_uid,
        },
      ),
    ),
  );
  steps.push("card-same-column-reorder-kept-in-column-event");

  const moveOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await requestApi(credentials, credentials.users[0], orderPath, {
    method: "PUT",
    body: JSON.stringify({ order: 0, parent_uid: destinationUID }),
  });
  await Promise.all(
    [owner, peer].map((page, index) =>
      page.waitForFunction(
        ({ offset, fromUID, toUID, cardUID }) => {
          const frames = window.__chatFrames.slice(offset);
          return (
            frames.some(
              (frame) =>
                frame.event === `board:card:order:changed:${toUID}` &&
                frame.data?.uid === cardUID &&
                frame.data?.move_type === "to_column",
            ) &&
            frames.some(
              (frame) =>
                frame.event === `board:card:order:changed:${fromUID}` &&
                frame.data?.move_type === "from_column",
            )
          );
        },
        {
          offset: moveOffsets[index],
          fromUID: originalColumnUID,
          toUID: destinationUID,
          cardUID: credentials.card_uid,
        },
      ),
    ),
  );
  await peer
    .getByRole("dialog")
    .getByText(destinationName, { exact: true })
    .waitFor();
  await waitForCardColumn(credentials, destinationUID);
  steps.push("card-column-move-fanned-out-rendered-and-persisted");

  await requestApi(credentials, credentials.users[0], orderPath, {
    method: "PUT",
    body: JSON.stringify({
      order: original.order,
      parent_uid: originalColumnUID,
    }),
  });
  await peer
    .getByRole("dialog")
    .getByText(original.project_column_name, { exact: true })
    .waitFor();
  await waitForCardColumn(credentials, originalColumnUID);
  steps.push("card-column-return-rendered-and-persisted");

  const board = await (
    await requestApi(
      credentials,
      credentials.users[0],
      `/board/${credentials.project_uid}/cards`,
    )
  ).json();
  const archiveColumn = board.columns.find((column) => column.is_archive);
  assert.ok(archiveColumn?.uid);
  const archiveOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await requestApi(credentials, credentials.users[0], `${cardPath}/archive`, {
    method: "PUT",
  });
  await Promise.all(
    [owner, peer].map((page, index) =>
      page.waitForFunction(
        ({ offset, columnUID, cardUID }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event === `board:card:order:changed:${columnUID}` &&
                frame.data?.uid === cardUID &&
                frame.data?.move_type === "to_column" &&
                Boolean(frame.data?.archived_at),
            ),
        {
          offset: archiveOffsets[index],
          columnUID: archiveColumn.uid,
          cardUID: credentials.card_uid,
        },
      ),
    ),
  );
  await peer
    .getByRole("dialog")
    .getByText(archiveColumn.name, { exact: true })
    .waitFor();
  await waitForCardArchiveState(credentials, archiveColumn.uid, true);
  steps.push("card-archive-fanned-out-rendered-and-persisted");

  const restoreOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await requestApi(credentials, credentials.users[0], orderPath, {
    method: "PUT",
    body: JSON.stringify({
      order: original.order,
      parent_uid: originalColumnUID,
    }),
  });
  await Promise.all(
    [owner, peer].map((page, index) =>
      page.waitForFunction(
        ({ offset, columnUID, cardUID }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event === `board:card:order:changed:${columnUID}` &&
                frame.data?.uid === cardUID &&
                frame.data?.move_type === "to_column" &&
                !frame.data?.archived_at,
            ),
        {
          offset: restoreOffsets[index],
          columnUID: originalColumnUID,
          cardUID: credentials.card_uid,
        },
      ),
    ),
  );
  await peer
    .getByRole("dialog")
    .getByText(original.project_column_name, { exact: true })
    .waitFor();
  await waitForCardArchiveState(credentials, originalColumnUID, false);
  steps.push("card-unarchive-fanned-out-rendered-and-persisted");
}

async function assertCardChecklistRealtimeLifecycle(owner, peer, credentials) {
  const checklistPath = `/board/${credentials.project_uid}/card/${credentials.card_uid}/checklist`;
  const title = `Realtime checklist ${runId}`;
  const createdOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  const created = await requestApi(
    credentials,
    credentials.users[0],
    checklistPath,
    { method: "POST", body: JSON.stringify({ title }) },
  );
  const checklistUID = (await created.json()).checklist.uid;
  assert.match(checklistUID || "", /^[A-Za-z0-9_-]+$/);
  await Promise.all(
    [owner, peer].map((page, index) =>
      page.waitForFunction(
        ({ offset, cardUID, checklistUID }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event === `board:card:checklist:created:${cardUID}` &&
                frame.data?.checklist?.uid === checklistUID,
            ),
        {
          offset: createdOffsets[index],
          cardUID: credentials.card_uid,
          checklistUID,
        },
      ),
    ),
  );
  await peer.getByText(title, { exact: true }).waitFor();
  await peer.screenshot({
    path: path.join(output, "card-checklist-mobile.png"),
  });
  const listed = await (
    await requestApi(credentials, credentials.users[1], checklistPath)
  ).json();
  assert.ok(
    listed.checklists.some((checklist) => checklist.uid === checklistUID),
  );
  steps.push("card-checklist-create-fanned-out-rendered-and-persisted");

  const subscriptionOffset = await owner.evaluate((cardUID) => {
    const socket = window.__probeSockets.find(
      (candidate) =>
        candidate.readyState === WebSocket.OPEN &&
        new URL(candidate.url).pathname === "/",
    );
    if (!socket) throw new Error("Owner JSON socket is not connected");
    const offset = window.__chatFrames.length;
    socket.send(
      JSON.stringify({
        event: "subscribe",
        topic: "board_card",
        topic_id: cardUID,
      }),
    );
    return offset;
  }, credentials.card_uid);
  await owner.waitForFunction(
    ({ offset, cardUID }) =>
      window.__chatFrames
        .slice(offset)
        .some(
          (frame) =>
            frame.event === "subscribed" &&
            frame.topic === "board_card" &&
            frame.topic_id.includes(cardUID),
        ),
    { offset: subscriptionOffset, cardUID: credentials.card_uid },
  );
  await peer
    .getByText(title, { exact: true })
    .locator("xpath=ancestor::div[contains(@class,'snap-center')]")
    .getByRole("button", { name: "Expand", exact: true })
    .click();
  const itemTitle = `Realtime item ${runId}`;
  const itemPath = `${checklistPath}/${checklistUID}/checkitem`;
  const itemOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  const itemCreated = await requestApi(
    credentials,
    credentials.users[0],
    itemPath,
    { method: "POST", body: JSON.stringify({ title: itemTitle }) },
  );
  const itemUID = (await itemCreated.json()).checkitem.uid;
  assert.match(itemUID || "", /^[A-Za-z0-9_-]+$/);
  await Promise.all(
    [owner, peer].map((page, index) =>
      page.waitForFunction(
        ({ offset, checklistUID, itemUID }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event ===
                  `board:card:checkitem:created:${checklistUID}` &&
                frame.data?.checkitem?.uid === itemUID,
            ),
        { offset: itemOffsets[index], checklistUID, itemUID },
      ),
    ),
  );
  await peer.getByText(itemTitle, { exact: true }).waitFor();
  await peer.screenshot({
    path: path.join(output, "card-checkitem-mobile.png"),
  });
  const withItem = await (
    await requestApi(credentials, credentials.users[1], checklistPath)
  ).json();
  assert.ok(
    withItem.checklists
      .find((checklist) => checklist.uid === checklistUID)
      ?.checkitems.some((item) => item.uid === itemUID),
  );
  steps.push("card-checkitem-create-fanned-out-rendered-and-persisted");

  const updatedItemTitle = `Updated realtime item ${runId}`;
  const titleOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await requestApi(
    credentials,
    credentials.users[0],
    `/board/${credentials.project_uid}/card/${credentials.card_uid}/checkitem/${itemUID}/title`,
    { method: "PUT", body: JSON.stringify({ title: updatedItemTitle }) },
  );
  await Promise.all(
    [owner, peer].map((page, index) =>
      page.waitForFunction(
        ({ offset, itemUID, title }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event ===
                  `board:card:checkitem:title:changed:${itemUID}` &&
                frame.data?.title === title,
            ),
        { offset: titleOffsets[index], itemUID, title: updatedItemTitle },
      ),
    ),
  );
  await peer.getByText(updatedItemTitle, { exact: true }).waitFor();
  const withUpdatedTitle = await (
    await requestApi(credentials, credentials.users[1], checklistPath)
  ).json();
  assert.equal(
    withUpdatedTitle.checklists
      .find((checklist) => checklist.uid === checklistUID)
      ?.checkitems.find((item) => item.uid === itemUID)?.title,
    updatedItemTitle,
  );
  steps.push("card-checkitem-title-fanned-out-rendered-and-persisted");

  const deadline = "2030-01-15T12:00:00Z";
  const deadlineOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await requestApi(
    credentials,
    credentials.users[0],
    `/board/${credentials.project_uid}/card/${credentials.card_uid}/checkitem/${itemUID}/deadline`,
    { method: "PUT", body: JSON.stringify({ deadline_at: deadline }) },
  );
  await Promise.all(
    [owner, peer].map((page, index) =>
      page.waitForFunction(
        ({ offset, itemUID, deadline }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event ===
                  `board:card:checkitem:deadline:changed:${itemUID}` &&
                Date.parse(frame.data?.deadline_at) === Date.parse(deadline),
            ),
        { offset: deadlineOffsets[index], itemUID, deadline },
      ),
    ),
  );
  await peer
    .getByText(updatedItemTitle, { exact: true })
    .locator("xpath=ancestor::div[contains(@class,'border-accent')][1]")
    .getByText("2030", { exact: false })
    .waitFor();
  const withDeadline = await (
    await requestApi(credentials, credentials.users[1], checklistPath)
  ).json();
  assert.equal(
    Date.parse(
      withDeadline.checklists
        .find((checklist) => checklist.uid === checklistUID)
        ?.checkitems.find((item) => item.uid === itemUID)?.deadline_at,
    ),
    Date.parse(deadline),
  );
  steps.push("card-checkitem-deadline-fanned-out-rendered-and-persisted");

  const itemCheckbox = peer
    .getByText(updatedItemTitle, { exact: true })
    .locator("xpath=ancestor::div[contains(@class,'border-accent')][1]")
    .getByRole("checkbox");
  const checkedOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await itemCheckbox.click();
  await Promise.all(
    [owner, peer].map((page, index) =>
      page.waitForFunction(
        ({ offset, itemUID }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event ===
                  `board:card:checkitem:checked:changed:${itemUID}` &&
                frame.data?.is_checked === true,
            ),
        { offset: checkedOffsets[index], itemUID },
      ),
    ),
  );
  await peer
    .getByText(updatedItemTitle, { exact: true })
    .locator("xpath=ancestor::div[contains(@class,'border-accent')][1]")
    .locator('[role="checkbox"][data-state="checked"]')
    .waitFor();
  const checkedList = await (
    await requestApi(credentials, credentials.users[0], checklistPath)
  ).json();
  assert.equal(
    checkedList.checklists
      .find((checklist) => checklist.uid === checklistUID)
      ?.checkitems.find((item) => item.uid === itemUID)?.is_checked,
    true,
  );
  steps.push("card-checkitem-check-fanned-out-rendered-and-persisted");

  const timerButton = peer
    .getByText(updatedItemTitle, { exact: true })
    .locator("xpath=ancestor::div[contains(@class,'border-accent')][1]")
    .getByRole("button", { name: "Manage timer" });
  for (const status of ["started", "paused"]) {
    const statusOffsets = await Promise.all(
      [owner, peer].map((page) =>
        page.evaluate(() => window.__chatFrames.length),
      ),
    );
    await requestApi(
      credentials,
      credentials.users[0],
      `/board/${credentials.project_uid}/card/${credentials.card_uid}/checkitem/${itemUID}/status`,
      { method: "PUT", body: JSON.stringify({ status }) },
    );
    await Promise.all(
      [owner, peer].map((page, index) =>
        page.waitForFunction(
          ({ offset, itemUID, status }) =>
            window.__chatFrames
              .slice(offset)
              .some(
                (frame) =>
                  frame.event ===
                    `board:card:checkitem:status:changed:${itemUID}` &&
                  frame.data?.status === status,
              ),
          { offset: statusOffsets[index], itemUID, status },
        ),
      ),
    );
    await timerButton.click();
    await peer.waitForFunction(
      (disabled) =>
        document.querySelector('button[data-value="paused"]')?.disabled ===
        disabled,
      status === "paused",
    );
    await peer.keyboard.press("Escape");
    const withStatus = await (
      await requestApi(credentials, credentials.users[1], checklistPath)
    ).json();
    assert.equal(
      withStatus.checklists
        .find((checklist) => checklist.uid === checklistUID)
        ?.checkitems.find((item) => item.uid === itemUID)?.status,
      status,
    );
    steps.push(`card-checkitem-${status}-fanned-out-rendered-and-persisted`);
  }

  const secondItemTitle = `Second realtime item ${runId}`;
  const secondItem = await (
    await requestApi(credentials, credentials.users[0], itemPath, {
      method: "POST",
      body: JSON.stringify({ title: secondItemTitle }),
    })
  ).json();
  const secondItemUID = secondItem.checkitem.uid;
  await peer.getByText(secondItemTitle, { exact: true }).waitFor();

  const orderOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await requestApi(
    credentials,
    credentials.users[0],
    `/board/${credentials.project_uid}/card/${credentials.card_uid}/checkitem/${itemUID}/order`,
    { method: "PUT", body: JSON.stringify({ order: 1 }) },
  );
  await Promise.all(
    [owner, peer].map((page, index) =>
      page.waitForFunction(
        ({ offset, checklistUID, itemUID }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event ===
                  `board:card:checkitem:order:changed:${checklistUID}` &&
                frame.data?.uid === itemUID &&
                frame.data?.order === 1 &&
                frame.data?.move_type === "in_column",
            ),
        { offset: orderOffsets[index], checklistUID, itemUID },
      ),
    ),
  );
  await waitForCheckitemOrder(
    credentials,
    credentials.users[1],
    checklistPath,
    checklistUID,
    [secondItemUID, itemUID],
  );
  steps.push("card-checkitem-reorder-fanned-out-and-persisted");

  const destinationTitle = `Destination checklist ${runId}`;
  const destination = await (
    await requestApi(credentials, credentials.users[0], checklistPath, {
      method: "POST",
      body: JSON.stringify({ title: destinationTitle }),
    })
  ).json();
  const destinationUID = destination.checklist.uid;
  const destinationPanel = peer
    .getByText(destinationTitle, { exact: true })
    .locator("xpath=ancestor::div[contains(@class,'snap-center')][1]");
  await destinationPanel
    .getByRole("button", { name: "Expand", exact: true })
    .click();

  const moveOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await requestApi(
    credentials,
    credentials.users[0],
    `/board/${credentials.project_uid}/card/${credentials.card_uid}/checkitem/${itemUID}/order`,
    {
      method: "PUT",
      body: JSON.stringify({ order: 0, parent_uid: destinationUID }),
    },
  );
  await Promise.all(
    [owner, peer].map((page, index) =>
      page.waitForFunction(
        ({ offset, destinationUID, checklistUID, itemUID }) => {
          const frames = window.__chatFrames.slice(offset);
          return (
            frames.some(
              (frame) =>
                frame.event ===
                  `board:card:checkitem:order:changed:${destinationUID}` &&
                frame.data?.uid === itemUID &&
                frame.data?.move_type === "to_column",
            ) &&
            frames.some(
              (frame) =>
                frame.event ===
                  `board:card:checkitem:order:changed:${checklistUID}` &&
                frame.data?.uid === itemUID &&
                frame.data?.move_type === "from_column",
            )
          );
        },
        {
          offset: moveOffsets[index],
          destinationUID,
          checklistUID,
          itemUID,
        },
      ),
    ),
  );
  await destinationPanel.getByText(updatedItemTitle, { exact: true }).waitFor();
  const moved = await (
    await requestApi(credentials, credentials.users[1], checklistPath)
  ).json();
  assert.ok(
    moved.checklists
      .find((checklist) => checklist.uid === destinationUID)
      ?.checkitems.some((item) => item.uid === itemUID),
  );
  assert.ok(
    !moved.checklists
      .find((checklist) => checklist.uid === checklistUID)
      ?.checkitems.some((item) => item.uid === itemUID),
  );
  steps.push("card-checkitem-move-fanned-out-rendered-and-persisted");

  await requestApi(
    credentials,
    credentials.users[0],
    `/board/${credentials.project_uid}/card/${credentials.card_uid}/checkitem/${itemUID}/order`,
    {
      method: "PUT",
      body: JSON.stringify({ order: 0, parent_uid: checklistUID }),
    },
  );
  await peer
    .getByText(title, { exact: true })
    .locator("xpath=ancestor::div[contains(@class,'snap-center')][1]")
    .getByText(updatedItemTitle, { exact: true })
    .waitFor();
  await waitForCheckitemOrder(
    credentials,
    credentials.users[1],
    checklistPath,
    checklistUID,
    [itemUID, secondItemUID],
  );
  steps.push("card-checkitem-move-back-rendered-and-persisted");

  await requestApi(
    credentials,
    credentials.users[0],
    `/board/${credentials.project_uid}/card/${credentials.card_uid}/checkitem/${secondItemUID}`,
    { method: "DELETE" },
  );
  await peer
    .getByText(secondItemTitle, { exact: true })
    .waitFor({ state: "hidden" });
  await requestApi(
    credentials,
    credentials.users[0],
    `${checklistPath}/${destinationUID}`,
    { method: "DELETE" },
  );
  await peer
    .getByText(destinationTitle, { exact: true })
    .waitFor({ state: "hidden" });

  const itemDeletedOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await requestApi(
    credentials,
    credentials.users[0],
    `/board/${credentials.project_uid}/card/${credentials.card_uid}/checkitem/${itemUID}`,
    { method: "DELETE" },
  );
  await Promise.all(
    [owner, peer].map((page, index) =>
      page.waitForFunction(
        ({ offset, checklistUID, itemUID }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event ===
                  `board:card:checkitem:deleted:${checklistUID}` &&
                frame.data?.uid === itemUID,
            ),
        { offset: itemDeletedOffsets[index], checklistUID, itemUID },
      ),
    ),
  );
  await peer
    .getByText(updatedItemTitle, { exact: true })
    .waitFor({ state: "hidden" });
  const withoutItem = await (
    await requestApi(credentials, credentials.users[1], checklistPath)
  ).json();
  assert.ok(
    !withoutItem.checklists
      .find((checklist) => checklist.uid === checklistUID)
      ?.checkitems.some((item) => item.uid === itemUID),
  );
  steps.push("card-checkitem-delete-fanned-out-rendered-and-persisted");

  await owner.evaluate((cardUID) => {
    const socket = window.__probeSockets.find(
      (candidate) =>
        candidate.readyState === WebSocket.OPEN &&
        new URL(candidate.url).pathname === "/",
    );
    if (socket) {
      socket.send(
        JSON.stringify({
          event: "unsubscribe",
          topic: "board_card",
          topic_id: cardUID,
        }),
      );
    }
  }, credentials.card_uid);

  const deletedOffsets = await Promise.all(
    [owner, peer].map((page) =>
      page.evaluate(() => window.__chatFrames.length),
    ),
  );
  await requestApi(
    credentials,
    credentials.users[0],
    `${checklistPath}/${checklistUID}`,
    {
      method: "DELETE",
    },
  );
  await Promise.all(
    [owner, peer].map((page, index) =>
      page.waitForFunction(
        ({ offset, cardUID, checklistUID }) =>
          window.__chatFrames
            .slice(offset)
            .some(
              (frame) =>
                frame.event === `board:card:checklist:deleted:${cardUID}` &&
                frame.data?.uid === checklistUID,
            ),
        {
          offset: deletedOffsets[index],
          cardUID: credentials.card_uid,
          checklistUID,
        },
      ),
    ),
  );
  await peer.getByText(title, { exact: true }).waitFor({ state: "hidden" });
  const remaining = await (
    await requestApi(credentials, credentials.users[1], checklistPath)
  ).json();
  assert.ok(
    !remaining.checklists.some((checklist) => checklist.uid === checklistUID),
  );
  steps.push("card-checklist-delete-fanned-out-rendered-and-persisted");
}

async function assertDeletedDocumentsLoseAccess(owner) {
  const created = await exec(
    "docker",
    [
      "exec",
      apiContainer,
      "uv",
      "run",
      "--no-sync",
      "python",
      fixturePath,
      "create-authz-targets",
      runId,
    ],
    { timeout: diagnosticCommandTimeout },
  );
  const targets = JSON.parse(created.stdout.trim());
  const documents = [
    {
      name: `card:${targets.card_uid}:description`,
      topic: "board_card",
      uid: targets.card_uid,
    },
    {
      name: `wiki:${targets.wiki_uid}:content`,
      topic: "board_wiki_private",
      uid: targets.wiki_uid,
    },
  ];
  await owner.evaluate(async (items) => {
    const source = window.__probeSockets.find(
      (socket) =>
        socket.readyState === WebSocket.OPEN &&
        new URL(socket.url).pathname === "/",
    );
    if (!source) throw new Error("Live Phoenix JSON socket not found");
    window.__authzSockets = {};
    window.__authzCloses = {};
    for (const item of items) {
      source.send(
        JSON.stringify({
          event: "subscribe",
          topic: item.topic,
          topic_id: item.uid,
        }),
      );
      const routeKey = [...new TextEncoder().encode(item.name)].reduce(
        (hash, byte) => Math.imul(hash ^ byte, 0x01000193),
        0x811c9dc5,
      );
      const url = new URL(source.url);
      url.pathname = "/editor-sync";
      url.searchParams.set(
        "route_key",
        (routeKey >>> 0).toString(16).padStart(8, "0"),
      );
      const nameBytes = new TextEncoder().encode(item.name);
      if (nameBytes.length > 127)
        throw new Error("Probe document name is too long");
      const socket = new WebSocket(url.toString());
      socket.binaryType = "arraybuffer";
      window.__authzSockets[item.name] = socket;
      socket.addEventListener("close", (event) => {
        window.__authzCloses[item.name] = event.code;
      });
      await new Promise((resolve, reject) => {
        const timeout = setTimeout(
          () => reject(new Error(`Editor auth timed out for ${item.name}`)),
          30000,
        );
        socket.addEventListener("open", () =>
          socket.send(
            new Uint8Array([nameBytes.length, ...nameBytes, 2, 0, 0]),
          ),
        );
        socket.addEventListener(
          "message",
          (event) => {
            if (event.data instanceof ArrayBuffer) {
              clearTimeout(timeout);
              resolve();
            }
          },
          { once: true },
        );
        socket.addEventListener(
          "close",
          (event) => {
            clearTimeout(timeout);
            reject(
              new Error(
                `Editor auth closed with ${event.code} for ${item.name}`,
              ),
            );
          },
          { once: true },
        );
      });
    }
  }, documents);
  await owner.waitForFunction(
    (items) =>
      items.every((item) =>
        window.__chatFrames.some(
          (frame) =>
            frame.event === "subscribed" &&
            frame.topic === item.topic &&
            frame.topic_id.includes(item.uid),
        ),
      ),
    documents,
  );
  steps.push("live-card-and-wiki-authorized-before-deletion");

  const deleted = await exec(
    "docker",
    [
      "exec",
      apiContainer,
      "uv",
      "run",
      "--no-sync",
      "python",
      fixturePath,
      "delete-authz-targets",
      runId,
    ],
    { timeout: diagnosticCommandTimeout },
  );
  assert.deepEqual(JSON.parse(deleted.stdout.trim()), { deleted: true });
  const offset = await owner.evaluate((items) => {
    const start = window.__chatFrames.length;
    const source = window.__probeSockets.find(
      (socket) =>
        socket.readyState === WebSocket.OPEN &&
        new URL(socket.url).pathname === "/",
    );
    if (!source)
      throw new Error("Live Phoenix JSON socket not found after deletion");
    for (const item of items) {
      const socket = window.__authzSockets[item.name];
      if (socket.readyState === WebSocket.OPEN) {
        const nameBytes = new TextEncoder().encode(item.name);
        socket.send(new Uint8Array([nameBytes.length, ...nameBytes, 2, 0, 0]));
      }
      source.send(
        JSON.stringify({
          event: "subscribe",
          topic: item.topic,
          topic_id: item.uid,
        }),
      );
    }
    return start;
  }, documents);
  await owner.waitForFunction(
    ({ items, start }) =>
      items.every(
        (item) =>
          window.__authzCloses[item.name] === 4403 &&
          window.__chatFrames
            .slice(start)
            .some(
              (frame) =>
                frame.event === "subscribed" &&
                frame.topic === item.topic &&
                !frame.topic_id.includes(item.uid),
            ),
      ),
    { items: documents, start: offset },
    { timeout: 30000 },
  );
  steps.push(
    "deleted-card-and-wiki-rejected-live-editor-reauth-and-json-resubscription",
  );
}

async function main() {
  await fs.mkdir(output, { recursive: true });
  const result = await exec(
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
    { timeout: diagnosticCommandTimeout },
  );
  const credentials = JSON.parse(result.stdout.trim());
  browser = await chromium.launch({
    headless: true,
    channel: "chrome",
    args: ["--disable-features=LocalNetworkAccessChecks"],
  });
  const users = race
    ? [...credentials.users, credentials.users[0]]
    : credentials.users;
  for (const [index, user] of users.entries()) {
    const context = await browser.newContext(
      index === 1 && failoverStage !== "concurrent-ui"
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
        value: user.refresh_token,
        url: origin,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    await context.addInitScript((port) => {
      const Native = window.WebSocket;
      window.__probeSocketPort = port;
      window.__chatFrames = [];
      window.__editorBinaryFrames = [];
      window.__probeSockets = [];
      window.WebSocket = class extends Native {
        send(payload) {
          if (typeof payload === "string" && payload.startsWith("{")) {
            const data = JSON.parse(payload);
            if (
              [
                "subscribe",
                "unsubscribe",
                "board:chat:send",
                "board:chat:cancel",
                "board:chat:resume",
              ].includes(data.event)
            ) {
              window.__chatFrames.push({
                event: "outbound",
                data,
                at: Date.now(),
              });
            }
          }
          return super.send(payload);
        }
        constructor(url, protocols) {
          if (protocols === undefined) super(url);
          else super(url, protocols);
          window.__probeSockets.push(this);
          this.addEventListener("open", () =>
            window.__chatFrames.push({
              event: "open",
              path: new URL(this.url).pathname,
              at: Date.now(),
            }),
          );
          this.addEventListener("message", (event) => {
            if (typeof event.data !== "string") {
              const binary =
                event.data instanceof Blob
                  ? event.data.arrayBuffer()
                  : Promise.resolve(event.data);
              Promise.resolve(binary).then((buffer) => {
                if (buffer instanceof ArrayBuffer) {
                  window.__editorBinaryFrames.push([...new Uint8Array(buffer)]);
                }
              });
              return;
            }
            if (!event.data) return;
            const data = JSON.parse(event.data);
            if (
              data.event?.includes("chat") ||
              data.event?.includes("card") ||
              data.event?.includes("label") ||
              data.event?.includes("graph:approval") ||
              data.event?.includes("roles") ||
              data.event === "user:notified" ||
              data.event === "user:notification:mutated" ||
              data.event === "task:aborted" ||
              data.event?.startsWith("board:assigned-users:updated:") ||
              [
                "subscribed",
                "unsubscribed",
                "subscription:revoked",
                "error",
              ].includes(data.event)
            )
              window.__chatFrames.push({ ...data, at: Date.now() });
          });
          this.addEventListener("close", (event) =>
            window.__chatFrames.push({
              event: "close",
              code: event.code,
              path: new URL(this.url).pathname,
              json: new URL(this.url).pathname === "/",
              at: Date.now(),
            }),
          );
        }
      };
    }, socketPort);
    await context.route(`${origin}/**`, async (route) => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      if (
        request.resourceType() !== "document" &&
        !pathname.startsWith("/assets/") &&
        !pathname.startsWith("/images/")
      )
        return route.continue();
      const file = path.resolve(
        uiBuild,
        request.resourceType() === "document"
          ? "index.html"
          : pathname.slice(1),
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
    pages.push(page);
    browserSocketEvidence.push(
      observeBrowserSockets(page, credentials.project_uid),
    );
    page.on("pageerror", (error) =>
      errors.push({ index, message: error.message, stack: error.stack }),
    );
    page.on("console", (message) => {
      if (message.type() === "error") {
        const error = {
          index,
          message: redact(message.text()),
        };
        const expectedFailoverError =
          phoenixFailoverActive &&
          error.message.includes("WebSocket connection to") &&
          (error.message.includes(
            "Connection closed before receiving a handshake response",
          ) ||
            error.message.includes("Unexpected response code: 503"));
        const expectedUploadError =
          uploadConcurrencyProbeActive &&
          error.message.startsWith("Failed to load resource:") &&
          (error.message.includes("406") || error.message.includes("503"));
        const expectedNotificationRefreshError =
          notificationRefreshOutageActive &&
          index === 0 &&
          error.message.startsWith("Failed to load resource:") &&
          error.message.includes("503");
        if (
          expectedUploadError ||
          expectedNotificationRefreshError ||
          expectedFailoverError ||
          (apiOutageActive &&
            (error.message.includes("net::ERR_CONNECTION_REFUSED") ||
              error.message.includes("net::ERR_EMPTY_RESPONSE") ||
              (error.message.includes("WebSocket connection to") &&
                error.message.includes("Unexpected response code: 503")) ||
              error.message ===
                "Failed to load resource: the server responded with a status of 404 (Not Found)"))
        )
          (expectedUploadError
            ? expectedUploadErrors
            : expectedOutageErrors
          ).push(error);
        else errors.push(error);
      }
    });
    page.on("response", (response) => {
      const url = new URL(response.url());
      if (url.port === "15694" && response.status() >= 400) {
        const error = {
          index,
          path: url.pathname,
          status: response.status(),
        };
        if (
          uploadConcurrencyProbeActive &&
          url.pathname.endsWith("/chat/upload") &&
          [406, 503].includes(response.status())
        )
          expectedUploadErrors.push(error);
        else if (
          apiOutageActive ||
          (notificationRefreshOutageActive &&
            index === 0 &&
            url.pathname === "/notifications" &&
            response.status() === 503)
        )
          expectedOutageErrors.push(error);
        else errors.push(error);
      }
    });
    await page.goto(`${origin}/board/${credentials.project_uid}`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForFunction(
      (uid) =>
        window.__chatFrames.some(
          (frame) =>
            frame.event === "subscribed" &&
            frame.topic === "board" &&
            frame.topic_id.includes(uid),
        ),
      credentials.project_uid,
    );
    await openBoardChat(page);
  }
  if (failoverStage === "canary") {
    for (const [index, page] of pages.entries()) {
      const routeKey = await page.evaluate(() => {
        const socket = window.__probeSockets.find(
          (candidate) =>
            candidate.readyState === WebSocket.OPEN &&
            new URL(candidate.url).pathname === "/",
        );
        return socket
          ? new URL(socket.url).searchParams.get("socket_route_key")
          : null;
      });
      assert.equal(routeKey, users[index].uid);
    }
    steps.push("owner-and-member-browser-sockets-use-authenticated-route-keys");
  } else {
  steps.push(
    failoverStage === "concurrent-ui"
      ? "desktop-owner-and-desktop-member-connected-to-live-phoenix"
      : "desktop-owner-and-mobile-member-connected-to-live-phoenix",
  );
  }
  for (const page of pages) {
    await page.waitForFunction(
      (uid) =>
        window.__chatFrames.some(
          (frame) =>
            frame.event === "board:chat:available" &&
            frame.topic_id === uid &&
            frame.data?.available === true &&
            frame.data?.bot,
        ),
      credentials.project_uid,
    );
  }
  steps.push("owner-and-member-received-chat-availability");
  if (failoverStage === "canary") {
    const owner = pages[0];
    const peer = pages[1];
    await peer.goto(
      `${origin}/board/${credentials.project_uid}/${credentials.card_uid}`,
      { waitUntil: "domcontentloaded" },
    );
    await peer.getByText("No description", { exact: true }).waitFor();
    await assertCardCommentRealtimeLifecycle(owner, peer, credentials);
    await assertCardLabelRealtimeLifecycle(owner, peer, credentials);
    await assertCardColumnMoveLifecycle(owner, peer, credentials);
    await assertCardChecklistRealtimeLifecycle(owner, peer, credentials);
    const input = owner.getByPlaceholder("Enter a message", { exact: true });
    await input.fill(
      `Look up card ${credentials.card_uid} in project ${credentials.project_uid}. Report its exact title. Do not change anything.`,
    );
    await input.press("Enter");
    await owner.waitForFunction(
      (title) =>
        window.__chatFrames
          .filter((frame) => frame.event === "board:chat:stream:buffer")
          .map((frame) => frame.data?.message?.content || "")
          .join("")
          .includes(title),
      credentials.card_title,
      { timeout: 150000 },
    );
    await owner.waitForFunction(
      () =>
        !document.querySelector('textarea[placeholder="Enter a message"]')
          ?.disabled,
      null,
      { timeout: 150000 },
    );
    steps.push("canary-chat-read-the-card-through-live-graph-and-model");
    await owner.reload({ waitUntil: "domcontentloaded" });
    await waitForBoardSocketReady(owner, credentials.project_uid);
    await openBoardChat(owner);
    await owner
      .getByText(credentials.card_title, { exact: false })
      .first()
      .waitFor();
    steps.push(
      "canary-browser-reload-restored-board-subscriptions-and-chat-history",
    );
    for (const [index, page] of pages.entries()) {
      await page.screenshot({ path: path.join(output, `page-${index}.png`) });
    }
    assert.deepEqual(errors, []);
    return;
  }
  if (failoverStage === "card-context") {
    const owner = pages[0];
    await owner.goto(
      `${origin}/board/${credentials.project_uid}/${credentials.card_uid}`,
      { waitUntil: "domcontentloaded" },
    );
    await owner.waitForFunction(
      (projectUID) =>
        window.__chatFrames.some(
          (frame) =>
            frame.event === "board:chat:available" &&
            frame.topic_id === projectUID &&
            frame.data?.available === true,
        ),
      credentials.project_uid,
    );
    const cardDialog = owner
      .locator('[data-dialog-content="true"]')
      .filter({ hasText: credentials.card_title });
    await cardDialog.getByRole("button", { name: "Expand" }).click();
    await cardDialog.getByRole("button", { name: "Collapse" }).waitFor();
    await openBoardChat(owner);
    await owner.getByText("Card", { exact: true }).last().waitFor();
    await owner.getByRole("button", { name: "Session list" }).click();
    await owner.getByRole("button", { name: "New chat" }).click();
    await owner.getByRole("button", { name: "Session list" }).click();
    const scopedInput = owner.getByPlaceholder("Enter a message", {
      exact: true,
    });
    const scopedFrameOffset = await owner.evaluate(
      () => window.__chatFrames.length,
    );
    await scopedInput.fill(
      "Report the title of the card in context. Do not change anything.",
    );
    await cardDialog.getByRole("button", { name: "Collapse" }).waitFor();
    await scopedInput.press("Enter");
    await owner.waitForFunction(
      ({ offset, cardUID }) =>
        window.__chatFrames
          .slice(offset)
          .some(
            (frame) =>
              frame.event === "outbound" &&
              frame.data?.event === "board:chat:send" &&
              frame.data?.data?.scope_table === "card" &&
              frame.data?.data?.scope_uid === cardUID &&
              !frame.data?.data?.session_uid,
          ),
      { offset: scopedFrameOffset, cardUID: credentials.card_uid },
    );
    await owner.waitForFunction(
      ({ offset, title }) =>
        window.__chatFrames
          .slice(offset)
          .filter((frame) => frame.event === "board:chat:stream:buffer")
          .map((frame) => frame.data?.message?.content || "")
          .join("")
          .includes(title),
      { offset: scopedFrameOffset, title: credentials.card_title },
      { timeout: 150000 },
    );
    await owner.waitForFunction(
      () =>
        !document.querySelector('textarea[placeholder="Enter a message"]')
          ?.disabled,
      null,
      { timeout: 150000 },
    );
    await cardDialog.getByRole("button", { name: "Collapse" }).waitFor();
    steps.push("expanded-card-chat-sent-locked-card-context-in-new-session");
    for (const [index, page] of pages.entries()) {
      await page.screenshot({ path: path.join(output, `page-${index}.png`) });
    }
    assert.deepEqual(errors, []);
    return;
  }
  if (failoverStage === "cancel") {
    const owner = pages[0];
    if (attachmentProbe) {
      await assertLangflowPartialCancel(owner, credentials);
      await owner.screenshot({ path: path.join(output, "page-0.png") });
      assert.deepEqual(errors, []);
      return;
    }
    const input = owner.getByPlaceholder("Enter a message", { exact: true });
    await input.fill(
      `Hold this Board chat response ${runId}. Do not call tools.`,
    );
    await input.press("Enter");
    await owner.waitForFunction(() =>
      window.__chatFrames.some(
        (frame) =>
          frame.event === "outbound" && frame.data?.event === "board:chat:send",
      ),
    );
    const taskId = await owner.evaluate(
      () =>
        window.__chatFrames.find(
          (frame) =>
            frame.event === "outbound" &&
            frame.data?.event === "board:chat:send",
        ).data.data.task_id,
    );
    const deadline = Date.now() + 90000;
    let held = false;
    while (Date.now() < deadline) {
      try {
        await exec("docker", [
          "exec",
          graphContainer,
          "test",
          "-f",
          "/tmp/phoenix-held-editor-model",
        ]);
        held = true;
        break;
      } catch {
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
    }
    assert.ok(held, "The Board chat run must reach the held Graph model");
    const before = await snapshot();
    assert.equal(before.runs.length, 1);
    assert.equal(before.runs[0].client_task_id, taskId);
    assert.equal(before.runs[0].status, "InternalBotRunStatus.Streaming");
    steps.push("accepted-board-chat-run-reached-held-graph-model");

    await owner
      .locator('textarea[placeholder="Enter a message"] ~ div button')
      .last()
      .click();
    await owner.waitForFunction(
      (taskId) =>
        window.__chatFrames.some(
          (frame) =>
            frame.event === "outbound" &&
            frame.data?.event === "board:chat:cancel" &&
            frame.data?.data?.task_id === taskId,
        ),
      taskId,
    );
    await owner.waitForFunction(
      (taskId) =>
        window.__chatFrames.some(
          (frame) =>
            frame.event === "task:aborted" && frame.data?.task_id === taskId,
        ),
      taskId,
      { timeout: 45000 },
    );
    const cancelled = await snapshot();
    assert.equal(cancelled.runs.length, 1);
    assert.equal(cancelled.runs[0].status, "InternalBotRunStatus.Cancelled");
    assert.equal(cancelled.approvals.length, 0);
    steps.push("browser-stop-acknowledged-only-after-durable-cancellation");

    await exec("docker", [
      "exec",
      graphContainer,
      "touch",
      "/tmp/phoenix-release-editor-model",
    ]);
    await owner.reload({ waitUntil: "domcontentloaded" });
    await waitForBoardSocketReady(owner, credentials.project_uid);
    await openBoardChat(owner);
    await owner
      .getByText(`Hold this Board chat response ${runId}.`, { exact: false })
      .first()
      .waitFor();
    const after = await snapshot();
    assert.equal(after.runs.length, 1);
    assert.equal(after.runs[0].status, "InternalBotRunStatus.Cancelled");
    steps.push("cancelled-run-and-user-message-survived-browser-reload");
    for (const [index, page] of pages.entries()) {
      await page.screenshot({ path: path.join(output, `page-${index}.png`) });
    }
    assert.deepEqual(errors, []);
    return;
  }
  await assertNonmemberChatAvailabilityDenied(
    pages[0],
    credentials.outsider.access_token,
    credentials.project_uid,
  );
  steps.push("nonmember-chat-subscription-and-availability-command-denied");
  const owner = pages[0];
  const peer = pages[1];
  if (failoverStage === "concurrent-ui") {
    if (process.env.PHOENIX_CONCURRENT_UI_ONLY === "comment") {
      await assertConcurrentCardComments(owner, peer, credentials);
      assert.deepEqual(errors, []);
      return;
    }
    if (process.env.PHOENIX_CONCURRENT_UI_ONLY === "card") {
      await assertConcurrentCardCreation(owner, peer, credentials);
      assert.deepEqual(errors, []);
      return;
    }
    if (process.env.PHOENIX_CONCURRENT_UI_ONLY === "column") {
      await assertConcurrentColumnCreation(owner, peer, credentials);
      assert.deepEqual(errors, []);
      return;
    }
    if (process.env.PHOENIX_CONCURRENT_UI_ONLY === "column-rename") {
      await assertConcurrentColumnCreation(owner, peer, credentials);
      await assertConcurrentColumnRename(owner, peer, credentials);
      assert.deepEqual(errors, []);
      return;
    }
    if (process.env.PHOENIX_CONCURRENT_UI_ONLY === "card-details") {
      await assertConcurrentCardDetails(owner, peer, credentials);
      assert.deepEqual(errors, []);
      return;
    }
    if (process.env.PHOENIX_CONCURRENT_UI_ONLY === "card-drag") {
      await assertTwoUserCardDrag(owner, peer, credentials);
      assert.deepEqual(errors, []);
      return;
    }
    if (process.env.PHOENIX_CONCURRENT_UI_ONLY === "card-archive") {
      await assertTwoUserCardArchive(owner, peer, credentials);
      assert.deepEqual(errors, []);
      return;
    }
    if (process.env.PHOENIX_CONCURRENT_UI_ONLY === "card-member") {
      await assertTwoUserCardMemberAssignment(owner, peer, credentials);
      assert.deepEqual(errors, []);
      return;
    }
    if (process.env.PHOENIX_CONCURRENT_UI_ONLY === "relationship") {
      await assertTwoUserCardRelationship(owner, peer, credentials);
      assert.deepEqual(errors, []);
      return;
    }
    if (process.env.PHOENIX_CONCURRENT_UI_ONLY === "wiki-details") {
      await assertConcurrentWikiDetails(owner, peer, credentials);
      assert.deepEqual(errors, []);
      return;
    }
    if (process.env.PHOENIX_CONCURRENT_UI_ONLY === "checklist") {
      await assertConcurrentChecklists(owner, peer, credentials);
      assert.deepEqual(errors, []);
      return;
    }
    if (process.env.PHOENIX_CONCURRENT_UI_ONLY === "checkitem") {
      await assertConcurrentCheckitems(owner, peer, credentials);
      assert.deepEqual(errors, []);
      return;
    }
    if (process.env.PHOENIX_CONCURRENT_UI_ONLY === "checkitem-details") {
      await assertConcurrentCheckitemDetails(owner, peer, credentials);
      assert.deepEqual(errors, []);
      return;
    }
    if (process.env.PHOENIX_CONCURRENT_UI_ONLY === "settings") {
      await assertConcurrentProjectSettings(owner, peer, credentials);
      assert.deepEqual(errors, []);
      return;
    }
    if (process.env.PHOENIX_CONCURRENT_UI_ONLY === "label") {
      await assertConcurrentLabelCreation(owner, peer, credentials);
      assert.deepEqual(errors, []);
      return;
    }
    if (process.env.PHOENIX_CONCURRENT_UI_ONLY === "label-details") {
      await assertConcurrentLabelDetails(owner, peer, credentials);
      assert.deepEqual(errors, []);
      return;
    }
    await assertConcurrentCardComments(owner, peer, credentials);
    await assertConcurrentChecklists(owner, peer, credentials);
    await assertConcurrentCheckitems(owner, peer, credentials);
    await assertConcurrentCheckitemDetails(owner, peer, credentials);
    await assertConcurrentBoardChatSends(owner, peer, credentials);
    await assertConcurrentNotificationReads(owner, peer, credentials);
    await assertConcurrentWikiCreation(owner, peer, credentials);
    await assertConcurrentWikiDetails(owner, peer, credentials);
    const dashboard = await owner.context().newPage();
    await dashboard.goto(`${origin}/dashboard/projects/all`, { waitUntil: "domcontentloaded" });
    await dashboard.getByRole("heading", {
      name: `Migration editor access probe ${runId}`,
      exact: true,
    }).waitFor();
    await assertConcurrentCardCreation(owner, peer, credentials, dashboard);
    await assertConcurrentColumnCreation(owner, peer, credentials, dashboard);
    await assertConcurrentColumnRename(owner, peer, credentials);
    await dashboard.close();
    steps.push("open-dashboard-reflected-concurrent-card-and-column-creates-without-reload");
    await assertConcurrentProjectSettings(owner, peer, credentials);
    await assertConcurrentLabelCreation(owner, peer, credentials);
    await assertConcurrentLabelDetails(owner, peer, credentials);
    await assertConcurrentCardDetails(owner, peer, credentials);
    await assertTwoUserCardDrag(owner, peer, credentials);
    await assertTwoUserCardMemberAssignment(owner, peer, credentials);
    await assertTwoUserCardRelationship(owner, peer, credentials);
    await assertTwoUserCardArchive(owner, peer, credentials);
    assert.deepEqual(errors, []);
    return;
  }
  if (failoverStage === "mobile-comments") {
    await peer.goto(
      `${origin}/board/${credentials.project_uid}/${credentials.card_uid}`,
      { waitUntil: "domcontentloaded" },
    );
    await peer.getByText("No description", { exact: true }).waitFor();
    for (let attempt = 0; attempt < 6; attempt += 1) {
      await assertCardCommentRealtimeLifecycle(owner, peer, credentials);
      await peer.reload({ waitUntil: "domcontentloaded" });
      await peer.getByText("No description", { exact: true }).waitFor();
    }
    steps.push("mobile-card-comments-survived-six-reloads-and-resizes");
    assert.deepEqual(errors, []);
    return;
  }
  if (attachmentProbe) {
    if (failoverStage === "resume") {
      await assertLangflowAttachmentProcessLoss(owner);
    } else {
      await assertLangflowAttachmentLifecycle(owner);
      await assertConcurrentUploadBound(owner, peer);
    }
    for (const [index, page] of pages.entries()) {
      await page.screenshot({ path: path.join(output, `page-${index}.png`) });
    }
    assert.deepEqual(errors, []);
    return;
  }
  await assertRoleDowngradeRejectsEditWithoutPersisting(
    owner,
    peer,
    credentials,
  );
  await assertRevokedMemberCannotResumeProjectAccess(owner, peer, credentials);
  if (["connected", "repeated"].includes(failoverStage)) {
    if (failoverStage === "repeated") {
      await peer.goto(`${origin}/board/${credentials.project_uid}`, {
        waitUntil: "domcontentloaded",
      });
      await waitForBoardSocketReady(peer, credentials.project_uid);
      await openBoardChat(peer);
    }
    await waitForPhoenixBrowserFailover();
    await assertNotificationRealtimeAndCommands(owner, peer, credentials);
  }
  await assertApiOutageRejectsChatWithoutPersisting(owner, credentials);
  await peer.goto(
    `${origin}/board/${credentials.project_uid}/${credentials.card_uid}`,
    { waitUntil: "domcontentloaded" },
  );
  await peer.getByText("No description", { exact: true }).waitFor();
  await assertCardCommentRealtimeLifecycle(owner, peer, credentials);
  await assertCardLabelRealtimeLifecycle(owner, peer, credentials);
  await assertCardColumnMoveLifecycle(owner, peer, credentials);
  await assertCardChecklistRealtimeLifecycle(owner, peer, credentials);
  const input = owner.getByPlaceholder("Enter a message", { exact: true });
  await input.fill(
    `Look up the card whose UID is ${credentials.card_uid} in project ${credentials.project_uid} using the available card lookup tool. Report its exact title and UID. Do not change anything.`,
  );
  await input.press("Enter");
  await owner.waitForFunction(
    () =>
      window.__chatFrames.some(
        (frame) =>
          frame.event === "board:chat:sent" ||
          frame.event === "board:chat:send:failed",
      ),
    null,
    { timeout: 45000 },
  );
  await owner.waitForFunction(
    () =>
      !document.querySelector('textarea[placeholder="Enter a message"]')
        ?.disabled,
    null,
    { timeout: 150000 },
  );
  await fs.writeFile(
    path.join(output, "owner-text.txt"),
    await owner.locator("body").innerText(),
  );
  const readFrames = await owner.evaluate(() => window.__chatFrames);
  const readText = readFrames
    .filter((frame) => frame.event === "board:chat:stream:buffer")
    .map((frame) => frame.data?.message?.content || "")
    .join("");
  assert.ok(
    readText.includes(credentials.card_title),
    "The real AI response must identify the actual card title",
  );
  steps.push("real-graph-and-model-read-the-synthetic-card");
  await owner.getByRole("combobox").click();
  await owner.getByRole("option", { name: "Edit access", exact: true }).click();
  const marker = `Phoenix approval verified ${runId}`;
  await input.fill(
    `Set only the description of card ${credentials.card_uid} in project ${credentials.project_uid} to exactly: ${marker}. Use the editing tool now. Do not change its title, labels, or any other card.`,
  );
  await input.press("Enter");
  await owner
    .getByRole("button", { name: "Approve", exact: true })
    .waitFor({ timeout: 150000 });
  const beforeResult = await exec(
    "docker",
    [
      "exec",
      apiContainer,
      "uv",
      "run",
      "--no-sync",
      "python",
      fixturePath,
      "status",
      runId,
    ],
    { timeout: diagnosticCommandTimeout },
  );
  assert.ok(
    !JSON.stringify(JSON.parse(beforeResult.stdout).description).includes(
      marker,
    ),
  );
  steps.push("real-tool-call-pauses-before-changing-the-card");
  const frames = await owner.evaluate(() => window.__chatFrames);
  const pending = frames.findLast(
    (frame) => frame.data?.interrupt || frame.data?.message?.graph_interrupt,
  );
  const interrupt =
    pending.data.interrupt || pending.data.message.graph_interrupt;
  const value = interrupt.value || interrupt;
  const command = {
    event: "board:chat:resume",
    topic: "board",
    topic_id: credentials.project_uid,
    data: {
      message_uid: pending.data.uid,
      thread_id: value.thread_id,
      session_id: value.session_id,
      approval_uid: value.approval_uid,
      resume: { approved: true, rejected: false },
    },
  };
  assert.ok(command.data.message_uid && command.data.approval_uid);
  const beforeDeniedResumes = await snapshot();
  await sendResume(peer, command, 3003);
  await sendResume(
    owner,
    {
      ...command,
      data: { ...command.data, session_id: credentials.card_uid },
    },
    3003,
  );

  const isolationSubscriptionOffset = await owner.evaluate((projectUID) => {
    const start = window.__chatFrames.length;
    const socket = window.__probeSockets.find(
      (candidate) =>
        candidate.readyState === WebSocket.OPEN &&
        new URL(candidate.url).port === window.__probeSocketPort,
    );
    if (!socket) throw new Error("Live Phoenix JSON socket not found");
    socket.send(
      JSON.stringify({
        event: "subscribe",
        topic: "board",
        topic_id: projectUID,
      }),
    );
    return start;
  }, credentials.isolation_project_uid);
  await owner.waitForFunction(
    ({ offset, projectUID }) =>
      window.__chatFrames
        .slice(offset)
        .some(
          (frame) =>
            frame.event === "subscribed" &&
            frame.topic === "board" &&
            frame.topic_id.includes(projectUID),
        ),
    {
      offset: isolationSubscriptionOffset,
      projectUID: credentials.isolation_project_uid,
    },
  );
  await sendResume(
    owner,
    { ...command, topic_id: credentials.isolation_project_uid },
    3003,
  );
  await owner.evaluate((projectUID) => {
    const socket = window.__probeSockets.find(
      (candidate) =>
        candidate.readyState === WebSocket.OPEN &&
        new URL(candidate.url).port === window.__probeSocketPort,
    );
    if (!socket) throw new Error("Live Phoenix JSON socket not found");
    socket.send(
      JSON.stringify({
        event: "unsubscribe",
        topic: "board",
        topic_id: projectUID,
      }),
    );
  }, credentials.isolation_project_uid);
  assert.deepEqual(
    await snapshot(),
    beforeDeniedResumes,
    "Denied resumes must not change history, approval, run, or Card state",
  );
  steps.push(
    "foreign-user-wrong-session-and-wrong-project-resumes-have-zero-persisted-effects",
  );

  if (race) {
    await pages[2].reload({ waitUntil: "domcontentloaded" });
    await pages[2]
      .getByRole("button", { name: "Approve", exact: true })
      .waitFor();
  }
  await owner.screenshot({ path: path.join(output, "approval-pending.png") });
  await owner.reload({ waitUntil: "domcontentloaded" });
  await waitForBoardSocketReady(owner, credentials.project_uid);
  await owner.getByRole("button", { name: "Approve", exact: true }).waitFor();
  steps.push("pending-approval-survives-browser-reload");
  const resumeStart = await owner.evaluate(() => window.__chatFrames.length);
  let approved = true;
  if (["resume", "accepted-api-outage"].includes(failoverStage)) {
    await owner.getByRole("button", { name: "Approve", exact: true }).click();
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
      "The real edit must reach the post-mutation response barrier",
    );
    const beforeCrash = await snapshot();
    assert.ok(JSON.stringify(beforeCrash.description).includes(marker));
    assert.equal(
      beforeCrash.runs.filter(
        (run) => run.status === "InternalBotRunStatus.Resuming",
      ).length,
      1,
    );
    steps.push(
      failoverStage === "resume"
        ? "real-card-edit-persisted-before-phoenix-loss-with-response-held"
        : "real-card-edit-persisted-before-api-outage-with-response-held",
    );
    if (failoverStage === "resume") {
      await waitForPhoenixBrowserFailover(credentials.project_uid);
    } else {
      const graphRequestCount = await completedGraphRequestCount();
      apiOutageActive = true;
      await exec("docker", ["stop", "--time", "10", runtimeApiContainer], {
        timeout: diagnosticCommandTimeout,
      });
      try {
        await exec("docker", [
          "exec",
          graphContainer,
          "touch",
          "/tmp/phoenix-release-tool",
        ]);
        await waitForCompletedGraphRequest(graphRequestCount);
        await new Promise((resolve) => setTimeout(resolve, 1000));
        const duringOutage = await snapshot();
        assert.equal(
          duringOutage.runs.filter(
            (run) => run.status === "InternalBotRunStatus.Resuming",
          ).length,
          1,
          "A completed provider response must remain recoverable while the API is unavailable",
        );
      } finally {
        await exec("docker", ["start", runtimeApiContainer], {
          timeout: diagnosticCommandTimeout,
        });
        await waitForRuntimeApi();
        apiOutageActive = false;
      }
      steps.push(
        "accepted-work-finish-failure-remains-reconcilable-after-api-recovery",
      );
    }
    await owner.reload({ waitUntil: "domcontentloaded" });
    await assertApprovalIsNonActionable(
      owner,
      "A claimed approval must stay non-actionable after failure and reload",
    );
    await exec("docker", [
      "exec",
      apiContainer,
      "uv",
      "run",
      "--no-sync",
      "python",
      inspectPath,
      runId,
      "--expire",
    ]);
    await exec("docker", [
      "exec",
      apiContainer,
      "/app/.venv/bin/langboard",
      "run:internal-bot-runs:recover",
    ]);
    const uncertain = await snapshot();
    assert.ok(JSON.stringify(uncertain.description).includes(marker));
    assert.equal(
      uncertain.runs.filter(
        (run) => run.status === "InternalBotRunStatus.Uncertain",
      ).length,
      1,
    );
    assert.deepEqual(
      uncertain.runs
        .filter((run) => run.decision)
        .map((run) => ({ id: run.id, decision: run.decision })),
      beforeCrash.runs
        .filter((run) => run.decision)
        .map((run) => ({ id: run.id, decision: run.decision })),
      "Node loss must preserve the accepted approval decision",
    );
    steps.push(
      failoverStage === "resume"
        ? "claimed-approval-remains-non-actionable-after-node-loss-and-reload"
        : "claimed-approval-remains-non-actionable-after-api-outage-and-reload",
    );
    await owner.screenshot({
      path: path.join(
        output,
        failoverStage === "resume"
          ? "resume-after-crash.png"
          : "resume-after-api-outage.png",
      ),
    });
    if (failoverStage === "resume") {
      await exec("docker", [
        "exec",
        graphContainer,
        "touch",
        "/tmp/phoenix-release-tool",
      ]);
    }
    await peer.reload({ waitUntil: "domcontentloaded" });
    await peer.getByText(marker, { exact: true }).waitFor();
    assert.equal(
      await peer.evaluate(() =>
        window.__chatFrames.some(
          (frame) =>
            frame.event === "board:chat:sent" ||
            frame.event === "board:chat:stream:buffer",
        ),
      ),
      false,
    );
    await owner.reload({ waitUntil: "domcontentloaded" });
    await assertApprovalIsNonActionable(
      owner,
      "An uncertain run must not allow a duplicate approval",
    );
    await owner.getByText("Outcome unknown", { exact: true }).waitFor();
    assert.equal(
      await owner.getByText("Resuming...", { exact: true }).count(),
      0,
    );
    await owner.screenshot({ path: path.join(output, "resume-uncertain.png") });
    steps.push(
      "uncertain-outcome-renders-after-reload-without-an-active-resume",
    );
    const logs = await exec("docker", ["logs", graphContainer], {
      maxBuffer: 8 * 1024 * 1024,
    });
    const edits = logs.stdout
      .split("\n")
      .filter((line) => line.startsWith("PROBE_TOOL "))
      .map((line) => JSON.parse(line.slice("PROBE_TOOL ".length)))
      .filter(
        (entry) =>
          entry.name === "change_card_details" &&
          entry.arguments.card_uid === credentials.card_uid,
      );
    assert.equal(
      edits.length,
      1,
      failoverStage === "resume"
        ? "Node loss must not repeat the external card edit"
        : "API outage must not repeat the external card edit",
    );
    steps.push(
      failoverStage === "resume"
        ? "one-external-edit-and-preserved-accepted-decision-after-node-loss"
        : "one-external-edit-and-preserved-accepted-decision-after-api-outage",
    );
    await peer.screenshot({
      path: path.join(
        output,
        failoverStage === "resume"
          ? "resume-peer-after-crash.png"
          : "resume-peer-after-api-outage.png",
      ),
    });
    await fs.writeFile(
      path.join(
        output,
        failoverStage === "resume"
          ? "crash-state.json"
          : "api-outage-state.json",
      ),
      JSON.stringify(await snapshot(), null, 2),
    );
    assert.deepEqual(errors, []);
    return;
  }
  if (race) {
    await Promise.all([
      owner
        .getByRole("button", { name: race === "approve" ? "Approve" : "Reject", exact: true })
        .click(),
      pages[2]
        .getByRole("button", {
          name: race === "approve" ? "Approve" : "Reject",
          exact: true,
        })
        .click(),
    ]);
    const deadline = Date.now() + 150000;
    let state;
    do {
      state = await snapshot();
      if (
        state.runs.every(
          (run) => run.status === "InternalBotRunStatus.Completed",
        )
      )
        break;
      await new Promise((resolve) => setTimeout(resolve, 500));
    } while (Date.now() < deadline);
    const resumed = state.runs.filter((run) => run.decision);
    assert.equal(resumed.length, 1);
    assert.equal(resumed[0].attempt, 2);
    assert.equal(resumed[0].status, "InternalBotRunStatus.Completed");
    approved = resumed[0].decision.approved;
    assert.equal(approved, race === "approve");
    assert.equal(state.approvals.length, 1);
    assert.equal(
      state.approvals[0].status,
      approved
        ? "GraphApprovalStatus.Approved"
        : "GraphApprovalStatus.Rejected",
    );
    assert.equal(state.history_count, approved ? 5 : 4);
    await fs.writeFile(
      path.join(output, "race-state.json"),
      JSON.stringify(state, null, 2),
    );
    steps.push("concurrent-decisions-have-one-durable-winner-and-one-result");
    const logs = await exec("docker", ["logs", graphContainer], {
      maxBuffer: 8 * 1024 * 1024,
    });
    const edits = logs.stdout
      .split("\n")
      .filter((line) => line.startsWith("PROBE_TOOL "))
      .map((line) => JSON.parse(line.slice("PROBE_TOOL ".length)))
      .filter(
        (entry) =>
          entry.name === "change_card_details" &&
          entry.arguments.card_uid === credentials.card_uid,
      );
    assert.equal(
      edits.length,
      approved ? 1 : 0,
      "Graph must not execute a losing or duplicated edit",
    );
    await sendResume(owner, command, 4001);
    assert.deepEqual(
      await snapshot(),
      state,
      "A replay after completion must not mutate state",
    );
    steps.push(
      "completed-approval-replay-is-rejected-without-another-tool-call",
    );
    for (const page of [owner, pages[2]]) {
      await page
        .getByText(approved ? "Approved" : "Rejected", { exact: true })
        .waitFor({ timeout: 15000 });
      assert.equal(
        await page
          .getByRole("button", { name: "Approve", exact: true })
          .count(),
        0,
      );
    }
    steps.push("both-owner-tabs-converge-without-refresh");
  } else {
    await owner.getByRole("button", { name: "Approve", exact: true }).click();
    await owner.waitForFunction(
      (offset) => {
        const frames = window.__chatFrames.slice(offset);
        const resumed = frames.find(
          (frame) => frame.event === "board:chat:stream:start",
        );
        return (
          resumed &&
          frames.some(
            (frame) =>
              frame.event === "board:chat:stream:end" &&
              frame.data.uid === resumed.data.ai_message.uid,
          )
        );
      },
      resumeStart,
      { timeout: 150000 },
    );
    await owner
      .getByText("Approved", { exact: true })
      .waitFor({ timeout: 15000 });
    assert.equal(
      await owner.getByRole("button", { name: "Approve", exact: true }).count(),
      0,
    );
    assert.equal(
      await owner.getByRole("button", { name: "Reject", exact: true }).count(),
      0,
    );
    steps.push("approval-status-updates-in-owner-browser-without-refresh");
  }
  const afterResult = await exec(
    "docker",
    [
      "exec",
      apiContainer,
      "uv",
      "run",
      "--no-sync",
      "python",
      fixturePath,
      "status",
      runId,
    ],
    { timeout: diagnosticCommandTimeout },
  );
  assert.equal(
    JSON.stringify(JSON.parse(afterResult.stdout).description).includes(marker),
    approved,
    "Only the winning approval may persist the description",
  );
  steps.push("approval-resumes-real-graph-and-persists-the-card-edit");
  await peer.reload({ waitUntil: "domcontentloaded" });
  await peer
    .getByText(approved ? marker : "No description", { exact: true })
    .waitFor();
  assert.equal(
    await peer.evaluate(() =>
      window.__chatFrames.some(
        (frame) =>
          frame.event === "board:chat:sent" ||
          (frame.event === "board:chat:stream:buffer" &&
            !frame.data?.resume_error_code),
      ),
    ),
    false,
    "Private chat must not leak to another project member",
  );
  steps.push(
    "mobile-peer-sees-card-edit-after-reload-without-receiving-private-chat",
  );
  steps.push("saved-card-edit-survives-peer-reload");
  for (const [index, page] of pages.entries()) {
    await page
      .locator('[data-dialog-content="true"]:visible .animate-pulse:visible')
      .first()
      .waitFor({ state: "hidden" });
    if (index === 1)
      await page
        .getByText(approved ? marker : "No description", { exact: true })
        .waitFor();
    await page.screenshot({ path: path.join(output, `page-${index}.png`) });
    await fs.writeFile(
      path.join(output, `frames-${index}.json`),
      JSON.stringify(await page.evaluate(() => window.__chatFrames), null, 2),
    );
  }
  if (!race && failoverStage !== "repeated") {
    await assertDeletedDocumentsLoseAccess(owner);
  }
  assert.deepEqual(errors, []);
}

main()
  .then(async () => {
    for (const [index, page] of pages.entries()) {
      await fs.writeFile(
        path.join(output, `frames-${index}.json`),
        JSON.stringify(await page.evaluate(() => window.__chatFrames), null, 2),
      );
    }
    await fs.writeFile(
      path.join(output, "report.json"),
      JSON.stringify(
        {
          success: true,
          steps,
          errors,
          expected_outage_errors: expectedOutageErrors,
          expected_upload_errors: expectedUploadErrors,
          reconnect_rounds:
            failoverStage === "repeated" ? reconnectRounds : undefined,
          reconnect_evidence:
            failoverStage === "repeated" ? reconnectEvidence : undefined,
          browser_socket_evidence:
            failoverStage === "repeated" ? browserSocketEvidence : undefined,
        },
        null,
        2,
      ),
    );
    console.log(JSON.stringify({ success: true, steps, output }));
    await browser?.close();
    process.exit(0);
  })
  .catch(async (error) => {
    const detail = [error.stack || error.message, error.stdout, error.stderr]
      .filter(Boolean)
      .map(redact)
      .join("\n");
    for (const [index, page] of pages.entries()) {
      await page
        .screenshot({ path: path.join(output, `failure-${index}.png`) })
        .catch(() => {});
      await fs
        .writeFile(
          path.join(output, `failure-text-${index}.txt`),
          await page.locator("body").innerText(),
        )
        .catch(() => {});
      await fs
        .writeFile(
          path.join(output, `frames-${index}.json`),
          JSON.stringify(
            await page.evaluate(() => window.__chatFrames),
            null,
            2,
          ),
        )
        .catch(() => {});
    }
    await fs.writeFile(
      path.join(output, "report.json"),
      JSON.stringify(
        {
          success: false,
          steps,
          errors,
          expected_outage_errors: expectedOutageErrors,
          expected_upload_errors: expectedUploadErrors,
          reconnect_rounds:
            failoverStage === "repeated" ? reconnectRounds : undefined,
          reconnect_evidence:
            failoverStage === "repeated" ? reconnectEvidence : undefined,
          browser_socket_evidence:
            failoverStage === "repeated" ? browserSocketEvidence : undefined,
          error: detail,
        },
        null,
        2,
      ),
    );
    console.error(detail);
    await browser?.close();
    process.exit(1);
  });
