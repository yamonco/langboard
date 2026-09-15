import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { dropTargetForElements, monitorForElements } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import { combine } from "@atlaskit/pragmatic-drag-and-drop/combine";
import Floating from "@/components/base/Floating";
import { IFloatingNavItem } from "@/components/base/Floating/Nav";
import IconComponent from "@/components/base/IconComponent";
import Toast from "@/components/base/Toast";
import useArchiveCard from "@/controllers/api/card/useArchiveCard";
import useRoleActionFilter from "@/core/hooks/useRoleActionFilter";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { AuthUser, Project, ProjectCard } from "@/core/models";
import { ProjectRole } from "@/core/models/roles";
import { cn } from "@/core/utils/ComponentUtils";
import { BOARD_DND_SYMBOL_SET } from "@/pages/BoardPage/components/board/BoardConstants";
import { draggedBoardCard } from "@/pages/BoardPage/components/board/BoardGestureData";

export default function BoardFloatingNavigation({
    project,
    currentUser,
    items,
}: {
    project: Project.TModel;
    currentUser: AuthUser.TModel;
    items: IFloatingNavItem[];
}) {
    const roles = project.useField("current_auth_role_actions");
    const isAdmin = currentUser.useField("is_admin");
    const { hasRoleAction } = useRoleActionFilter(roles);
    const enabled = isAdmin || hasRoleAction(ProjectRole.EAction.CardUpdate);
    const target = useRef<HTMLDivElement>(null);
    const pending = useRef(false);
    const [dragging, setDragging] = useState(false);
    const [over, setOver] = useState(false);
    const [t] = useTranslation();
    const queryClient = useQueryClient();
    const { mutateAsync } = useArchiveCard({ interceptToast: true });

    useEffect(() => {
        if (!enabled || !target.current) return;
        const cardFrom = (data: Record<string | symbol, unknown>) => {
            const uid = draggedBoardCard(data, BOARD_DND_SYMBOL_SET.row, project.uid);
            return ProjectCard.Model.getModels((card) => card.uid === uid && card.project_uid === project.uid && !card.archived_at)[0];
        };
        const accepts = ({ source }: { source: { data: Record<string | symbol, unknown> } }) =>
            !pending.current && window.matchMedia("(min-width: 768px) and (pointer: fine)").matches && !!cardFrom(source.data);
        return combine(
            monitorForElements({
                canMonitor: accepts,
                onDragStart: () => setDragging(true),
                onDrop: () => {
                    setDragging(false);
                    setOver(false);
                },
            }),
            dropTargetForElements({
                element: target.current,
                canDrop: accepts,
                getData: () => ({ type: "board-card-archive" }),
                onDragEnter: () => setOver(true),
                onDragLeave: () => setOver(false),
                onDrop: ({ source }) => {
                    const card = cardFrom(source.data);
                    if (!card || pending.current) return;
                    pending.current = true;
                    const promise = mutateAsync({ project_uid: project.uid, card_uid: card.uid }).then(() =>
                        queryClient.invalidateQueries({ queryKey: [`get-cards-${project.uid}`] })
                    );
                    Toast.Add.promise(promise, {
                        loading: t("common.Updating..."),
                        success: t("successes.Card archived successfully."),
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
            })
        );
    }, [enabled, mutateAsync, project, queryClient, t]);

    return (
        <Floating.Nav
            fixed
            items={items}
            className="board-floating-navigation"
            contentClassName={cn("transition-transform duration-200 motion-reduce:transition-none", dragging && "md:-translate-y-2 md:shadow-xl")}
            trailing={
                <div
                    className={cn(
                        "hidden overflow-hidden transition-[width,opacity] duration-200 motion-reduce:transition-none md:block",
                        dragging ? "w-44 opacity-100" : "w-0 opacity-0"
                    )}
                    aria-hidden={!dragging}
                >
                    <div
                        ref={target}
                        data-board-archive-drop=""
                        className={cn(
                            "ml-1 flex h-11 w-40 items-center justify-center gap-2 rounded-full border border-dashed text-sm",
                            over ? "border-primary bg-primary text-primary-foreground" : "border-primary/60 bg-primary/10 text-foreground"
                        )}
                    >
                        <IconComponent icon="archive" size="4" />
                        {t(over ? "board.Release to archive" : "board.Drop to archive")}
                    </div>
                </div>
            }
        />
    );
}
