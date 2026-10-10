import { useState } from "react";
import { createRoot } from "react-dom/client";
import { useTranslation } from "react-i18next";
import { MetadataModel, Project, ProjectCard, User } from "@/core/models";
import CardTypeBadges from "@/components/CardTypeBadges";
import { applyMetadataUpdated, applyMetadataDeleted } from "@/controllers/socket/shared/MetadataSocketHelper";
import CardPresentationBadge from "@/components/CardPresentationBadge";
import { CARD_PRESENTATION_KEY, CARD_VISIBILITY_PRESENTATIONS } from "./CardPresentation";
import "@/i18n";
import "@/assets/styles/main.css";
const visibilityProject = Project.Model.fromOne({ uid: "visibility-project", all_members: [], created_at: new Date(), updated_at: new Date() });
const visibilityCard = ProjectCard.Model.fromOne({
    uid: "visibility-card",
    project_uid: visibilityProject.uid,
    visibility: "INTERNAL",
    created_at: new Date(),
    updated_at: new Date(),
});
const privateCard = ProjectCard.Model.fromOne({
    uid: "private-card",
    project_uid: visibilityProject.uid,
    visibility: "PRIVATE",
    created_at: new Date(),
    updated_at: new Date(),
});
const externalMember = User.Model.fromOne({
    uid: "external-member",
    firstname: "External",
    lastname: "Member",
    membership_classification: "external" as const,
    type: "user",
    created_at: new Date(),
    updated_at: new Date(),
});
function VisibilityFixture() {
    const visibility = visibilityCard.useField("visibility");
    return (
        <section className="mt-8" aria-label="Member transitions">
            <div data-testid="internal-card">
                <CardTypeBadges card={visibilityCard} />
            </div>
            <div data-testid="private-card">
                <CardTypeBadges card={privateCard} />
            </div>
            <output data-testid="stored-visibility">{visibility}</output>
            <button
                onClick={() => {
                    visibilityProject.all_members = [externalMember];
                }}
            >
                Add external member
            </button>
            <button
                onClick={() =>
                    User.Model.fromOne({
                        uid: externalMember.uid,
                        type: "user" as const,
                        firstname: "External",
                        lastname: "Member",
                        created_at: new Date(),
                        updated_at: new Date(),
                        membership_classification: "internal",
                    })
                }
            >
                Classify member as internal
            </button>
            <button
                onClick={() =>
                    User.Model.fromOne({
                        uid: externalMember.uid,
                        type: "user" as const,
                        firstname: "External",
                        lastname: "Member",
                        created_at: new Date(),
                        updated_at: new Date(),
                        membership_classification: "external",
                    })
                }
            >
                Classify member as external
            </button>
            <button
                onClick={() => {
                    visibilityProject.all_members = [];
                }}
            >
                Remove external member
            </button>
        </section>
    );
}
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
    const [showVisibility, setShowVisibility] = useState(true);
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
            <button onClick={() => setShowVisibility((value) => !value)}>Toggle member view</button>
            <button
                onClick={() =>
                    User.Model.fromOne({
                        uid: externalMember.uid,
                        type: "user" as const,
                        firstname: "External",
                        lastname: "Member",
                        created_at: new Date(),
                        updated_at: new Date(),
                        membership_classification: "external",
                    })
                }
            >
                Update hidden member classification
            </button>
            {showVisibility && <VisibilityFixture />}
        </main>
    );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
