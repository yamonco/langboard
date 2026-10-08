import { ProjectCard } from "@/core/models";
import { ProjectRole } from "@/core/models/roles";
import { useBoard } from "@/core/providers/BoardProvider";
import { useQueryClient } from "@tanstack/react-query";
import SignalInboxPanel from "./SignalInboxPanel";

export default function BoardSignalInbox({ projectUID }: { projectUID: string }) {
    const { socket, hasRoleAction } = useBoard();
    const client = useQueryClient();
    const cards = ProjectCard.Model.useModels(
        (card) => card.project_uid === projectUID && !card.archived_at && card.source_type !== "project_wiki",
        [projectUID]
    );
    return (
        <SignalInboxPanel
            projectUID={projectUID}
            socket={socket}
            cards={cards}
            canEdit={hasRoleAction(ProjectRole.EAction.CardUpdate)}
            onLinked={(cardUID) => {
                void client.invalidateQueries({ queryKey: [`get-card-details-${projectUID}-${cardUID}`] });
            }}
        />
    );
}
