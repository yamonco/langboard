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
const attachmentProbe = process.env.PHOENIX_BROWSER_ATTACHMENT_PROBE === "true";
const maxFileSizeMb = Number.parseInt(
  process.env.PHOENIX_BROWSER_MAX_FILE_SIZE_MB || "",
  10,
);
assert.ok(!race || ["approve", "reject"].includes(race));
assert.ok(
  ["connected", "repeated", "resume", "accepted-api-outage"].includes(
    failoverStage,
  ),
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
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${apiOrigin}/health`);
      if (response.ok) return;
    } catch {
      // The container can accept connections only after Uvicorn finishes starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("The isolated browser API did not recover after restart");
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
  const outageToast = page
    .getByText(
      "Server has been temporarily disabled. Please try again later.",
      {
        exact: true,
      },
    )
    .waitFor({ timeout: 90000 });
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
      (offset) => {
        const frames = window.__chatFrames.slice(offset);
        return (
          frames.some(
            (frame) =>
              frame.event === "outbound" &&
              frame.data?.event === "board:chat:send",
          ) &&
          frames.some((frame) => frame.event === "close" && frame.code === 1011)
        );
      },
      baseline.frameOffset,
      { timeout: 45000 },
    );
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
  await outageToast;
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
        socket.readyState === 1 && new URL(socket.url).port === "5691",
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
            new URL(socket.url).port === "5691",
        );
        if (!activeSocket) {
          reject(new Error("Live Phoenix JSON socket not found"));
          return;
        }

        const url = new URL(activeSocket.url);
        url.searchParams.set("authorization", accessToken);
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
          new URL(candidate.url).port === "5691",
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
        new URL(candidate.url).port === "5691",
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

  await notificationButton(ownerMirror).click();
  await readAllNotificationsButton(ownerMirror).waitFor();
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
  const ownerDeleteResponse = owner.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/notifications" &&
      response.request().method() === "DELETE",
  );
  await deleteAllNotificationsButton(owner).click();
  assert.equal((await ownerDeleteResponse).status(), 200);
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
          offset: ownerDeleteAllMutationOffsets[index],
          userUID: credentials.users[0].uid,
        },
        { timeout: 30000 },
      ),
    ),
  );
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

async function assertCardCommentRealtimeLifecycle(owner, peer, credentials) {
  const commentPrompt = peer.getByText(
    `Add a comment as ${credentials.users[1].name}`,
    { exact: true },
  );
  if (!(await commentPrompt.isVisible().catch(() => false))) {
    await peer.getByRole("button", { name: "Comments", exact: true }).click();
  }
  await commentPrompt.waitFor();

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
  await waitForVisibleSlateText(peer, addedText);
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
    const context = await browser.newContext({
      viewport:
        index === 1
          ? { width: 390, height: 844 }
          : { width: 1360, height: 860 },
    });
    await context.addCookies([
      {
        name: credentials.refresh_cookie_name,
        value: user.refresh_token,
        url: origin,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    await context.addInitScript(() => {
      const Native = window.WebSocket;
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
              data.event?.includes("graph:approval") ||
              data.event?.includes("roles") ||
              data.event === "user:notified" ||
              data.event === "user:notification:mutated" ||
              data.event?.startsWith("board:assigned-users:updated:") ||
              [
                "subscribed",
                "unsubscribed",
                "subscription:revoked",
                "error",
              ].includes(data.event)
            )
              window.__chatFrames.push(data);
          });
          this.addEventListener("close", (event) =>
            window.__chatFrames.push({
              event: "close",
              code: event.code,
              json: new URL(this.url).pathname === "/",
            }),
          );
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
        if (
          expectedUploadError ||
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
        else if (apiOutageActive) expectedOutageErrors.push(error);
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
  steps.push("desktop-owner-and-mobile-member-connected-to-live-phoenix");
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
  steps.push("desktop-owner-and-mobile-member-received-chat-availability");
  await assertNonmemberChatAvailabilityDenied(
    pages[0],
    credentials.outsider.access_token,
    credentials.project_uid,
  );
  steps.push("nonmember-chat-subscription-and-availability-command-denied");
  const owner = pages[0];
  const peer = pages[1];
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
        new URL(candidate.url).port === "5691",
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
        new URL(candidate.url).port === "5691",
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
      owner.getByRole("button", { name: "Approve", exact: true }).click(),
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
    assert.equal(state.approvals.length, 1);
    assert.equal(
      state.approvals[0].status,
      approved
        ? "GraphApprovalStatus.Approved"
        : "GraphApprovalStatus.Rejected",
    );
    assert.equal(state.history_count, 5);
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
    const detail = [error.message, error.stdout, error.stderr]
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
