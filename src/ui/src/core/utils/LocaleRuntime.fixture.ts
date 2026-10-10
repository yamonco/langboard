import i18n from "@/i18n";
import { normalizeLocale } from "./LocalePolicy";

const root = document.getElementById("root")!;
const output = document.createElement("output");
root.append(output);
function render() {
    output.textContent = JSON.stringify({
        language: i18n.language,
        document: document.documentElement.lang,
        cached: localStorage.getItem("lang"),
        close: i18n.t("common.Close"),
        signIn: i18n.t("auth.Sign in"),
        welcome: i18n.t("auth.activate.Welcome to {app}!", { app: "Langboard" }),
        recovery: i18n.t("accountRecovery.Password recovery"),
        languageLabel: i18n.t("myAccount.Language"),
        emailLabel: i18n.t("user.Email"),
        deleteApiKey: i18n.t("ask.Are you sure you want to delete this API key?"),
        fallbackExample: i18n.t("fixtureFallback.English fallback"),
        board: i18n.t("board.Board"),
        availableTools: i18n.t("mcp.Available Tools ({count})", { count: 3 }),
        fallback: i18n.options.fallbackLng,
        supported: i18n.options.supportedLngs,
    });
}
for (const language of ["en-US", "ko-KR", "ja-JP", "zh-CN", "zh-Hant"]) {
    const button = document.createElement("button");
    button.textContent = language;
    button.onclick = async () => {
        await i18n.changeLanguage(normalizeLocale(language));
        render();
    };
    root.append(button);
}
function initializeFixture() {
    i18n.addResourceBundle("en-US", "translation", { fixtureFallback: { "English fallback": "English fallback" } }, true, true);
    render();
}
if (i18n.isInitialized) initializeFixture();
else i18n.on("initialized", initializeFixture);
