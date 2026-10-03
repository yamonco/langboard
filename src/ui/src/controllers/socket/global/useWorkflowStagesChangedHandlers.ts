import { SocketEvents } from "@langboard/core/constants";
import { ESocketTopic } from "@langboard/core/enums";
import { useQueryClient } from "@tanstack/react-query";
import useSocketHandler from "@/core/helpers/SocketHandler";

export default function useWorkflowStagesChangedHandlers() {
    const queryClient = useQueryClient();
    return useSocketHandler<{}, {}>({
        topic: ESocketTopic.Global,
        eventKey: "workflow-stages-changed",
        onProps: {
            name: SocketEvents.SERVER.GLOBALS.WORKFLOW_STAGES_CHANGED,
            callback: () => {
                void queryClient.invalidateQueries({ queryKey: ["workflow-stages"] });
                void queryClient.invalidateQueries({ queryKey: ["project-workflow-stages"] });
            },
        },
    });
}
