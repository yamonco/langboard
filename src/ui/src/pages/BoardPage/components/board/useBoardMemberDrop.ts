import { dropTargetForElements } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import Toast from "@/components/base/Toast";
import useAddCardAssignedUser from "@/controllers/api/card/useAddCardAssignedUser";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { ProjectCard } from "@/core/models";
import { useBoard } from "@/core/providers/BoardProvider";
import { draggedBoardMember } from "@/pages/BoardPage/components/board/BoardGestureData";

export default function useBoardMemberDrop(element: HTMLDivElement | null, card: ProjectCard.TModel) {
    const { project, canDragCards } = useBoard();
    const members = project.useForeignFieldArray("all_members");
    const invited = project.useField("invited_member_uids");
    const pending = useRef(false);
    const [t] = useTranslation();
    const updatingMessage = t("common.Updating...");
    const assignedMessage = t("board.Member assigned");
    const { mutateAsync: addAssignedUser } = useAddCardAssignedUser({ interceptToast: true });

    useEffect(() => {
        if (!element || !canDragCards) return;
        const getMember = (data: Record<string | symbol, unknown>) => {
            const uid = draggedBoardMember(data, project.uid);
            return members.find((member) => member.uid === uid && member.isValidUser() && !invited.includes(member.uid));
        };
        const clear = () => element.removeAttribute("data-member-drop-target");
        const cleanup = dropTargetForElements({
            element,
            canDrop: ({ source }) => !pending.current && !!getMember(source.data),
            getData: () => ({ type: "board-member-assignment", cardUID: card.uid }),
            onDragEnter: () => element.setAttribute("data-member-drop-target", "true"),
            onDragLeave: clear,
            onDrop: ({ source }) => {
                clear();
                const member = getMember(source.data);
                if (!member || pending.current || !canDragCards) return;
                pending.current = true;
                const promise = addAssignedUser({ project_uid: project.uid, card_uid: card.uid, assignee_uid: member.uid }).then((response) => {
                    card.member_uids = response.member_uids;
                });
                Toast.Add.promise(promise, {
                    loading: updatingMessage,
                    success: assignedMessage,
                    error: (error) => {
                        const message = { message: "" };
                        setupApiErrorHandler({}, message).handle(error);
                        return message.message;
                    },
                    finally: () => {
                        pending.current = false;
                    },
                });
            },
        });
        return () => {
            cleanup();
            clear();
        };
    }, [addAssignedUser, assignedMessage, canDragCards, card, element, invited, members, project, updatingMessage]);
}
