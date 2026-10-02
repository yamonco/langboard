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
if (i18n.isInitialized) render();
else i18n.on("initialized", render);
