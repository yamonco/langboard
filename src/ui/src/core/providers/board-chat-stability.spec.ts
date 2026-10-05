import { expect, test } from "@playwright/test";
test("chat availability retains page state and avoids inactive session reads", async ({ page }) => {
    const navigations: string[] = [];
    const updates: string[] = [];
    page.on("console", (message) => {
        if (message.text().startsWith("Fixture page")) console.log(message.text());
    });
    page.on("websocket", (socket) =>
        socket.on("framereceived", ({ payload }) => {
            const message = JSON.parse(String(payload));
            if (message.type === "update" || message.type === "full-reload") updates.push(JSON.stringify(message));
        })
    );
    page.on("framenavigated", (frame) => {
        if (frame === page.mainFrame()) navigations.push(frame.url());
    });
    try {
        await page.goto("/src/core/providers/board-chat-stability.fixture.html");
        await expect(page.getByTestId("mounts")).toHaveText("1");
        await page.getByRole("button", { name: "Read requests" }).click();
        await expect(page.getByRole("textbox", { name: "Draft" })).toHaveValue("0");
        await page.getByRole("textbox", { name: "Draft" }).fill("unsaved draft");
        await expect(page.getByRole("textbox", { name: "Draft" })).toHaveValue("unsaved draft");
        await expect(page.getByTestId("draft-state")).toHaveText("unsaved draft");
        await page.getByRole("button", { name: "Enable chat" }).click();
        await expect(page.getByTestId("chat")).toHaveText("bot");
        await expect(page.getByTestId("mounts")).toHaveText("1");
        console.log("Navigation receipts", navigations);
        expect(navigations).toHaveLength(1);
        await expect(page.getByRole("textbox", { name: "Draft" })).toHaveValue("unsaved draft");
        await page.getByRole("button", { name: "Read requests" }).click();
        await expect(page.getByRole("textbox", { name: "Draft" })).toHaveValue("0");
        await page.getByRole("button", { name: "Open chat panel" }).click();
        await page.getByRole("button", { name: "Open chat panel" }).click();
        await page.getByRole("button", { name: "Disable chat" }).click();
        await expect(page.getByTestId("chat")).toHaveText("disabled");
        await expect(page.getByTestId("mounts")).toHaveText("1");
        await expect(page.getByRole("textbox", { name: "Draft" })).toHaveValue("0");
        await page.getByRole("button", { name: "Read requests" }).click();
        await expect(page.getByRole("textbox", { name: "Draft" })).toHaveValue("1");
    } finally {
        console.log("Final navigation and Vite update receipts", { navigations, updates });
    }
});
