import BoardSettingsMetadataConnection from "./BoardSettingsMetadataConnection";
export default function BoardSettingsDokploy(props: { onStatusChange?: () => void }) {
    return <BoardSettingsMetadataConnection provider="dokploy" {...props} />;
}
