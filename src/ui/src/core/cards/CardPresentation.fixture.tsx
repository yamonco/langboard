import { createRoot } from "react-dom/client";
import { useTranslation } from "react-i18next";
import { MetadataModel, ProjectCard } from "@/core/models";
import CardTypeBadges from "@/components/CardTypeBadges";
import { applyMetadataUpdated, applyMetadataDeleted } from "@/controllers/socket/shared/MetadataSocketHelper";
import CardPresentationBadge from "@/components/CardPresentationBadge";
import { CARD_PRESENTATION_KEY, CARD_VISIBILITY_PRESENTATIONS } from "./CardPresentation";
import "@/i18n";
import "@/assets/styles/main.css";
const appCard = ProjectCard.Model.fromOne({ uid: "app-card", project_uid: "test-project", created_at: new Date(), updated_at: new Date() });
MetadataModel.Model.fromOne({ uid: appCard.uid, type: "card", metadata: {}, created_at: new Date(), updated_at: new Date() });
const appPresentation = {
    version: 1,
    key: "app.github.issue",
    axis: "origin",
    name: "GitHub issue",
    description: "App-reported origin.",
    icon: "🔗",
    translations: { "ko-KR": { name: "깃허브 이슈", description: "앱에서 제공한 출처입니다." } },
};
function Fixture() {
    const [t, i18n] = useTranslation();
    const definition = CARD_VISIBILITY_PRESENTATIONS.whisper;
    return (
        <main className="p-6">
            <label>
                Language
                <select aria-label="Language" value={i18n.language} onChange={(event) => void i18n.changeLanguage(event.target.value)}>
                    {["en-US", "ko-KR", "ja-JP", "zh-CN"].map((language) => (
                        <option key={language}>{language}</option>
                    ))}
                </select>
            </label>
            <section className="mt-8">
                <CardPresentationBadge
                    presentationKey={definition.key}
                    axis="visibility"
                    icon={definition.icon}
                    name={t(definition.nameKey)}
                    description={t(definition.descriptionKey)}
                />
                <CardTypeBadges card={appCard} />
                <button
                    onClick={() => applyMetadataUpdated("card", appCard.uid, { key: CARD_PRESENTATION_KEY, value: JSON.stringify(appPresentation) })}
                >
                    Attach app type
                </button>
                <button onClick={() => applyMetadataDeleted("card", appCard.uid, { keys: [CARD_PRESENTATION_KEY] })}>Remove app type</button>
            </section>
        </main>
    );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
