import { dropTargetForElements } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import { type RefObject, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import Toast from "@/components/base/Toast";
import { api } from "@/core/helpers/Api";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { ProjectCard } from "@/core/models";
import { useBoard } from "@/core/providers/BoardProvider";
import { draggedBoardMember } from "@/pages/BoardPage/components/board/BoardGestureData";
import { Routing } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";

export default function useBoardMemberDrop(ref: RefObject<HTMLDivElement | null>, card: ProjectCard.TModel) {
    const { project, canDragCards } = useBoard();
    const members = project.useForeignFieldArray("all_members");
    const invited = project.useField("invited_member_uids");
    const pending = useRef(false);
    const [t] = useTranslation();

    useEffect(() => {
        const element = ref.current;
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
                const base = Utils.String.format(Routing.API.BOARD.CARD.UPDATE_ASSIGNED_USERS, { uid: project.uid, card_uid: card.uid });
                // The additive endpoint preserves assignments made by other sessions.
                const promise = api
                    .put<{
                        member_uids: string[];
                    }>(`${base}/${encodeURIComponent(member.uid)}`, undefined, { env: { interceptToast: true } as never })
                    .then((response) => {
                        card.member_uids = response.data.member_uids;
                    });
                Toast.Add.promise(promise, {
                    loading: t("common.Updating..."),
                    success: t("board.Member assigned"),
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
    }, [canDragCards, card, invited, members, project, ref, t]);
}
