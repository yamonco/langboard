const assert = require("node:assert/strict");
const { execFile } = require("node:child_process");
const fs = require("node:fs/promises");
const path = require("node:path");
const { promisify } = require("node:util");
const { chromium } = require(
  process.env.PLAYWRIGHT_MODULE_PATH || "playwright",
);

const exec = promisify(execFile);
const runId = process.env.PHOENIX_BROWSER_RUN_ID;
const origin = process.env.PHOENIX_BROWSER_UI_ORIGIN;
const apiOrigin = process.env.PHOENIX_BROWSER_API_ORIGIN;
const apiContainer = process.env.PHOENIX_BROWSER_API_CONTAINER;
const runtimeApiContainer = process.env.PHOENIX_BROWSER_RUNTIME_API_CONTAINER;
const fixturePath = process.env.PHOENIX_BROWSER_FIXTURE_PATH;
const nodeA = process.env.PHOENIX_BROWSER_NODE_A;
const ollamaWorker = process.env.PHOENIX_BROWSER_OLLAMA_WORKER_CONTAINER;
const workerLoss = process.env.PHOENIX_BROWSER_OLLAMA_WORKER_LOSS === "true";
const proxyModeFile = process.env.PHOENIX_BROWSER_PROXY_MODE_FILE;
const uiBuild = path.resolve(process.env.PHOENIX_BROWSER_UI_BUILD || "");
const output = path.resolve("local/socket-migration", `ollama-ui-${runId}`);
const destination = `phoenix-browser-${runId}:latest`;
const polledDestination = `phoenix-browser-polled-${runId}:latest`;
const recoveredDestination = `phoenix-browser-recovered-${runId}:latest`;
const failedPullName = `phoenix-browser-pull-${runId}:latest`;
const interruptedPullName = `phoenix-browser-worker-loss-${runId}:latest`;
const errors = [];
const steps = [];

assert.match(runId || "", /^[0-9a-f-]{36}$/);
assert.ok(
  origin &&
    apiOrigin &&
    apiContainer &&
    runtimeApiContainer &&
    fixturePath &&
    nodeA &&
    proxyModeFile &&
    ollamaWorker &&
    process.env.PHOENIX_BROWSER_UI_BUILD,
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

async function fixtureAction(action, ...args) {
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
      action,
      runId,
      ...args,
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
    window.__ollamaFrames = [];
    window.WebSocket = class extends Native {
      constructor(url, protocols) {
        if (protocols === undefined) super(url);
        else super(url, protocols);
        this.addEventListener("message", (event) => {
          if (typeof event.data !== "string") return;
          try {
            const frame = JSON.parse(event.data);
            if (frame.topic === "ollama_manager")
              window.__ollamaFrames.push(frame);
          } catch {
            // Ignore non-JSON editor frames.
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
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  return page;
}

async function waitForEvent(page, event, model, copyTo) {
  await page.waitForFunction(
    ({ name, model, copyTo }) =>
      window.__ollamaFrames.some(
        (frame) =>
          frame.event === name &&
          frame.data?.model === model &&
          (copyTo === undefined || frame.data?.copy_to === copyTo),
      ),
    { name: event, model, copyTo },
    { timeout: 30000 },
  );
}

async function hasModel(name) {
  const response = await fetch("http://127.0.0.1:11434/api/tags");
  assert.equal(response.status, 200);
  const { models } = await response.json();
  return models.some((model) => model.name === name);
}

async function getPull(fixture, name) {
  const response = await fetch(`${apiOrigin}/settings/ollama/models/pull`, {
    headers: {
      Authorization: `Bearer ${fixture.users[0].access_token}`,
      Cookie: `${fixture.refresh_cookie_name}=${fixture.users[0].refresh_token}`,
    },
  });
  assert.equal(response.status, 200);
  return (await response.json()).pulls.find((pull) => pull.model === name);
}

async function testWorkerLoss(desktop, mobile, fixture) {
  await fixtureAction(
    "prepare-ollama-pull",
    "--model-name",
    interruptedPullName,
  );
  await desktop.getByRole("button", { name: "Pull a model" }).click();
  await desktop
    .getByRole("textbox", { name: "Model name" })
    .fill(interruptedPullName);
  await desktop.getByRole("button", { name: "Pull", exact: true }).click();

  let pull;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    pull = await getPull(fixture, interruptedPullName);
    if (pull?.status === "running" && pull.percent === 37) break;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  assert.equal(pull?.status, "running");
  assert.equal(pull.percent, 37);
  await fixtureAction(
    "track-ollama-pull",
    "--model-name",
    interruptedPullName,
    "--pull-uid",
    pull.uid,
  );
  await waitForEvent(
    mobile,
    "settings:ollama:model:pull:status",
    interruptedPullName,
  );
  steps.push("pull-progress-persisted-and-published-to-peer");

  await exec("docker", ["kill", ollamaWorker], { timeout: 30000 });
  await fixtureAction("age-ollama-pull", "--model-name", interruptedPullName);
  await exec(
    "docker",
    [
      "exec",
      runtimeApiContainer,
      "uv",
      "run",
      "--no-sync",
      "langboard",
      "run:ollama-pulls:recover",
    ],
    { timeout: 60000 },
  );
  for (const page of [desktop, mobile]) {
    await page.waitForFunction(
      (name) =>
        window.__ollamaFrames.some(
          (frame) =>
            frame.event === "settings:ollama:model:pull:status" &&
            frame.data?.model === name &&
            frame.data?.status === "error",
        ),
      interruptedPullName,
      { timeout: 30000 },
    );
    await page
      .getByRole("progressbar")
      .waitFor({ state: "detached", timeout: 30000 });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page
      .getByRole("button", { name: "Pull a model" })
      .waitFor({ timeout: 30000 });
    assert.equal(await page.getByRole("progressbar").count(), 0);
  }
  const recovered = await getPull(fixture, interruptedPullName);
  assert.equal(recovered?.uid, pull.uid);
  assert.equal(recovered.status, "uncertain");
  assert.equal(recovered.attempt, pull.attempt);
  assert.ok(recovered.error);
  steps.push("worker-loss-recovered-as-uncertain-without-retry");
}

async function deleteFixtureModel(name) {
  const response = await fetch("http://127.0.0.1:11434/api/delete", {
    method: "DELETE",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ model: name }),
  });
  assert.ok([200, 404].includes(response.status));
}

async function main() {
  let completed = false;
  await fs.mkdir(output, { recursive: true });
  const fixture = await credentials();
  const tagsResponse = await fetch("http://127.0.0.1:11434/api/tags");
  assert.equal(tagsResponse.status, 200);
  const { models } = await tagsResponse.json();
  assert.ok(models.length > 0, "Ollama must already have a source model");
  const source = models[0].name;
  const pullSource = workerLoss
    ? undefined
    : models.reduce((smallest, model) =>
        model.size < smallest.size ? model : smallest,
      ).name;
  if (pullSource) {
    await fixtureAction("prepare-ollama-pull", "--model-name", pullSource);
  }
  assert.ok(models.every((model) => model.name !== destination));
  const denied = await fetch(`${apiOrigin}/settings/ollama/models`, {
    headers: {
      Authorization: `Bearer ${fixture.outsider.access_token}`,
      Cookie: `${fixture.refresh_cookie_name}=${fixture.outsider.refresh_token}`,
    },
  });
  assert.equal(denied.status, 403, "Non-admin must not read Ollama models");
  steps.push("non-admin-request-denied");

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
      fixture.users[0],
      fixture.refresh_cookie_name,
      true,
    );
    for (const page of [desktop, mobile]) {
      await page.goto(`${origin}/settings/ollama`, {
        waitUntil: "domcontentloaded",
      });
      await page.getByText(source, { exact: true }).waitFor({ timeout: 30000 });
      await page.waitForFunction(
        () =>
          window.__ollamaFrames.some((frame) => frame.event === "subscribed"),
        undefined,
        { timeout: 30000 },
      );
    }
    steps.push("desktop-and-mobile-subscribed");

    if (workerLoss) {
      await testWorkerLoss(desktop, mobile, fixture);
      assert.deepEqual(errors, []);
      completed = true;
      return;
    }
    assert.ok(pullSource);

    const sourceRow = desktop
      .getByText(source, { exact: true })
      .locator('xpath=ancestor::div[.//button[@aria-label="Copy"]][1]');
    await sourceRow.getByRole("button", { name: "Copy", exact: true }).click();
    const copyDialog = desktop.getByRole("dialog");
    await copyDialog.locator("input").fill(destination);
    await copyDialog.getByRole("button", { name: "Copy", exact: true }).click();
    await waitForEvent(
      mobile,
      "settings:ollama:model:copied",
      source,
      destination,
    );
    await mobile
      .getByText(destination, { exact: true })
      .waitFor({ timeout: 30000 });
    assert.equal(await hasModel(destination), true);
    steps.push("copy-published-and-rendered-on-peer");

    await mobile.reload({ waitUntil: "domcontentloaded" });
    await mobile
      .getByText(destination, { exact: true })
      .waitFor({ timeout: 30000 });
    steps.push("copy-survived-peer-reload");

    const pollingCopy = await fetch("http://127.0.0.1:11434/api/copy", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ source, destination: polledDestination }),
    });
    assert.equal(pollingCopy.status, 200);
    await mobile
      .getByText(polledDestination, { exact: true })
      .waitFor({ timeout: 45000 });
    steps.push("missed-model-change-reconciled-while-socket-stays-open");

    const externalCopy = await fetch("http://127.0.0.1:11434/api/copy", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ source, destination: recoveredDestination }),
    });
    assert.equal(externalCopy.status, 200);
    assert.equal(
      await mobile.getByText(recoveredDestination, { exact: true }).count(),
      0,
      "A model copied without a broker event should initially be absent from the peer",
    );
    const subscriptionsBeforeReconnect = await mobile.evaluate(
      () =>
        window.__ollamaFrames.filter((frame) => frame.event === "subscribed")
          .length,
    );
    await fs.writeFile(proxyModeFile, "b\n");
    await exec("docker", ["stop", "--time", "20", nodeA], {
      timeout: 60000,
    });
    await mobile.waitForFunction(
      (previousCount) =>
        window.__ollamaFrames.filter((frame) => frame.event === "subscribed")
          .length > previousCount,
      subscriptionsBeforeReconnect,
      { timeout: 30000 },
    );
    await mobile
      .getByText(recoveredDestination, { exact: true })
      .waitFor({ timeout: 30000 });
    steps.push("missed-model-change-reconciled-after-socket-reconnect");

    const copiedRow = mobile
      .getByText(destination, { exact: true })
      .locator('xpath=ancestor::div[.//button[@aria-label="Delete"]][1]');
    await copiedRow
      .getByRole("button", { name: "Delete", exact: true })
      .click();
    await mobile
      .getByRole("dialog")
      .getByRole("button", { name: "Delete", exact: true })
      .click();
    await waitForEvent(desktop, "settings:ollama:model:deleted", destination);
    await desktop
      .getByText(destination, { exact: true })
      .waitFor({ state: "detached", timeout: 30000 });
    assert.equal(await hasModel(destination), false);
    steps.push("delete-published-and-removed-on-peer");

    await mobile.getByRole("button", { name: "Pull a model" }).click();
    await mobile
      .getByRole("textbox", { name: "Model name" })
      .fill(failedPullName);
    await mobile.getByRole("button", { name: "Pull", exact: true }).click();
    await waitForEvent(
      desktop,
      "settings:ollama:model:pull:status",
      failedPullName,
    );
    await desktop.waitForFunction(
      (name) =>
        window.__ollamaFrames.some(
          (frame) =>
            frame.event === "settings:ollama:model:pull:status" &&
            frame.data?.model === name &&
            frame.data?.status === "error",
        ),
      failedPullName,
      { timeout: 60000 },
    );
    let failedPull;
    for (let attempt = 0; attempt < 30; attempt += 1) {
      const response = await fetch(`${apiOrigin}/settings/ollama/models/pull`, {
        headers: {
          Authorization: `Bearer ${fixture.users[0].access_token}`,
          Cookie: `${fixture.refresh_cookie_name}=${fixture.users[0].refresh_token}`,
        },
      });
      assert.equal(response.status, 200);
      failedPull = (await response.json()).pulls.find(
        (pull) => pull.model === failedPullName,
      );
      if (failedPull?.status === "failed") break;
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    assert.equal(failedPull?.status, "failed");
    assert.ok(failedPull.error);
    steps.push("pull-failure-persisted-and-published-to-peer");

    await desktop.getByRole("button", { name: "Pull a model" }).click();
    await desktop.getByRole("textbox", { name: "Model name" }).fill(pullSource);
    await desktop.getByRole("button", { name: "Pull", exact: true }).click();
    let acceptedPull;
    for (let attempt = 0; attempt < 30; attempt += 1) {
      const response = await fetch(`${apiOrigin}/settings/ollama/models/pull`, {
        headers: {
          Authorization: `Bearer ${fixture.users[0].access_token}`,
          Cookie: `${fixture.refresh_cookie_name}=${fixture.users[0].refresh_token}`,
        },
      });
      assert.equal(response.status, 200);
      acceptedPull = (await response.json()).pulls.find(
        (pull) => pull.model === pullSource,
      );
      if (acceptedPull) break;
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    assert.ok(acceptedPull?.uid);
    await fixtureAction(
      "track-ollama-pull",
      "--model-name",
      pullSource,
      "--pull-uid",
      acceptedPull.uid,
    );
    await desktop.waitForFunction(
      (name) =>
        window.__ollamaFrames.some(
          (frame) =>
            frame.event === "settings:ollama:model:pull:status" &&
            frame.data?.model === name &&
            frame.data?.status === "success",
        ),
      pullSource,
      { timeout: 90000 },
    );
    await mobile.waitForFunction(
      (name) =>
        window.__ollamaFrames.some(
          (frame) =>
            frame.event === "settings:ollama:model:pull:status" &&
            frame.data?.model === name &&
            frame.data?.status === "success",
        ),
      pullSource,
      { timeout: 30000 },
    );
    const successfulPullResponse = await fetch(
      `${apiOrigin}/settings/ollama/models/pull`,
      {
        headers: {
          Authorization: `Bearer ${fixture.users[0].access_token}`,
          Cookie: `${fixture.refresh_cookie_name}=${fixture.users[0].refresh_token}`,
        },
      },
    );
    assert.equal(successfulPullResponse.status, 200);
    const successfulPull = (await successfulPullResponse.json()).pulls.find(
      (pull) => pull.uid === acceptedPull.uid,
    );
    assert.equal(successfulPull?.status, "success");
    for (const page of [desktop, mobile]) {
      await page
        .getByRole("progressbar")
        .waitFor({ state: "detached", timeout: 30000 });
      await page.reload({ waitUntil: "domcontentloaded" });
      await page
        .getByText(pullSource, { exact: true })
        .first()
        .waitFor({ timeout: 30000 });
      assert.equal(await page.getByRole("progressbar").count(), 0);
    }
    steps.push("pull-success-persisted-and-published-to-peer");
    assert.deepEqual(errors, []);
    completed = true;
  } finally {
    await browser.close();
    for (const name of [destination, polledDestination, recoveredDestination]) {
      try {
        await deleteFixtureModel(name);
      } catch (error) {
        errors.push(`Fixture cleanup failed for ${name}: ${error}`);
      }
    }
    await fs.writeFile(
      path.join(output, "report.json"),
      JSON.stringify(
        {
          success: completed && errors.length === 0,
          source,
          destination,
          steps,
          errors,
        },
        null,
        2,
      ),
    );
    if (errors.length > 0) {
      process.exitCode = 1;
    }
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
