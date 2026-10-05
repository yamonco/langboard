import { expect, test } from "@playwright/test";
test("chat availability retains page state and avoids inactive session reads", async ({ page }) => {
 await page.goto("/src/core/providers/board-chat-stability.fixture.html");
 await expect(page.getByTestId("mounts")).toHaveText("1");
 await page.getByRole("button", { name: "Read requests" }).click();
 await expect(page.getByRole("textbox", { name: "Draft" })).toHaveValue("0");
 await page.getByRole("textbox", { name: "Draft" }).fill("unsaved draft");
 await page.getByRole("button", { name: "Enable chat" }).click();
 await expect(page.getByTestId("chat")).toHaveText("bot");
 await expect(page.getByTestId("mounts")).toHaveText("1");
 await expect(page.getByRole("textbox", { name: "Draft" })).toHaveValue("unsaved draft");
 await page.getByRole("button", { name: "Disable chat" }).click();
 await expect(page.getByTestId("chat")).toHaveText("disabled");
 await expect(page.getByTestId("mounts")).toHaveText("1");
 await expect(page.getByRole("textbox", { name: "Draft" })).toHaveValue("unsaved draft");
 await page.getByRole("button", { name: "Read requests" }).click();
 await expect(page.getByRole("textbox", { name: "Draft" })).toHaveValue("1");
});
