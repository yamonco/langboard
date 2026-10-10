import BoardSettingsMetadataConnection from "./BoardSettingsMetadataConnection";
export default function BoardSettingsGlitchTip(props: { onStatusChange?: () => void }) {
    return <BoardSettingsMetadataConnection provider="glitchtip" {...props} />;
}
