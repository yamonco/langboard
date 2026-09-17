import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { dropTargetForElements, monitorForElements } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import Floating from "@/components/base/Floating";
import { IFloatingNavItem } from "@/components/base/Floating/Nav";
import Button from "@/components/base/Button";
import IconComponent from "@/components/base/IconComponent";
import useRoleActionFilter from "@/core/hooks/useRoleActionFilter";
import { AuthUser, Project, ProjectColumn } from "@/core/models";
import { pinnedProjectDockColumns } from "@/core/models/projectDock";
import { ProjectRole } from "@/core/models/roles";
import { cn } from "@/core/utils/ComponentUtils";
import { BOARD_COLUMN_TOUCH_DND_ATTR, BOARD_DND_SYMBOL_SET } from "@/pages/BoardPage/components/board/BoardConstants";
import { draggedBoardCard } from "@/pages/BoardPage/components/board/BoardGestureData";
import useProjectDockSync from "@/controllers/api/board/useProjectDockSync";

function acceptsCard(data: Record<string | symbol, unknown>, projectUID: string): boolean {
    return window.matchMedia("(min-width: 768px) and (pointer: fine)").matches && !!draggedBoardCard(data, BOARD_DND_SYMBOL_SET.row, projectUID);
}

export default function BoardFloatingNavigation({
    project,
    currentUser,
    items,
    dockEnabled = false,
}: {
    project: Project.TModel;
    currentUser: AuthUser.TModel;
    items: IFloatingNavItem[];
    dockEnabled?: boolean;
}) {
    useProjectDockSync(project.uid);
    const roles = project.useField("current_auth_role_actions");
    const isAdmin = currentUser.useField("is_admin");
    const { hasRoleAction } = useRoleActionFilter(roles);
    const canDrop = dockEnabled && (isAdmin || hasRoleAction(ProjectRole.EAction.CardUpdate));
    const columns = ProjectColumn.Model.useModels((column) => column.project_uid === project.uid);
    project.useField("dock_revision");
    const pinned = pinnedProjectDockColumns(columns);
    const archive = columns.find((column) => column.is_archive);
    const [dragging, setDragging] = useState(false);

    useEffect(() => {
        if (!canDrop) return;
        return monitorForElements({
            canMonitor: ({ source }) => acceptsCard(source.data, project.uid),
            onDragStart: () => setDragging(true),
            onDrop: () => setDragging(false),
        });
    }, [canDrop, project.uid]);

    return (
        <Floating.Nav
            fixed
            items={items}
            className="board-floating-navigation"
            contentClassName={cn(
                "max-w-[calc(100vw-1rem)] transition-transform duration-200 motion-reduce:transition-none",
                dragging && "md:-translate-y-2 md:shadow-xl"
            )}
            trailing={
                dockEnabled && (
                    <div className="hidden min-w-0 items-center md:flex">
                        {pinned.length > 0 && (
                            <>
                                <span role="separator" aria-orientation="vertical" className="mx-1 h-6 w-px shrink-0 bg-border" />
                                <div className="flex min-w-0 max-w-[35vw] gap-1 overflow-x-auto">
                                    {pinned.map((column) => (
                                        <DockTarget key={column.uid} column={column} canDrop={canDrop} dragging={dragging} />
                                    ))}
                                </div>
                            </>
                        )}
                        {archive && (
                            <>
                                <span role="separator" aria-orientation="vertical" className="mx-1 h-6 w-px shrink-0 bg-border" />
                                <DockTarget column={archive} canDrop={canDrop} dragging={dragging} />
                            </>
                        )}
                    </div>
                )
            }
        />
    );
}

function DockTarget({ column, canDrop, dragging }: { column: ProjectColumn.TModel; canDrop: boolean; dragging: boolean }) {
    const target = useRef<HTMLButtonElement>(null);
    const [over, setOver] = useState(false);
    const name = column.useField("name");
    const isArchive = column.useField("is_archive");
    const [t] = useTranslation();
    useEffect(() => {
        if (!canDrop || !target.current) return;
        return dropTargetForElements({
            element: target.current,
            canDrop: ({ source }) => acceptsCard(source.data, column.project_uid),
            // The board root owns optimistic movement, API submission and undo.
            getData: () => ({ [BOARD_DND_SYMBOL_SET.column]: true, column }),
            onDragEnter: () => setOver(true),
            onDragLeave: () => setOver(false),
            onDrop: () => setOver(false),
        });
    }, [canDrop, column]);
    return (
        <Button
            ref={target}
            type="button"
            variant={over ? "default" : "ghost"}
            className={cn("h-11 max-w-40 shrink-0 gap-2 rounded-full", dragging && "border border-dashed border-primary/60")}
            aria-label={isArchive ? t("board.Archive") : name}
            onClick={() => {
                const element = document.querySelector<HTMLElement>(`[${BOARD_COLUMN_TOUCH_DND_ATTR}="${CSS.escape(column.uid)}"]`);
                const scrollport = document.getElementById("board-scrollport");
                if (!element || !scrollport) return;
                scrollport.scrollBy({
                    left: element.getBoundingClientRect().left - scrollport.getBoundingClientRect().left - 16,
                    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
                });
            }}
        >
            <IconComponent icon={isArchive ? "archive" : "pin"} size="4" />
            <span className="truncate text-xs">{isArchive ? t(over ? "board.Release to archive" : "board.Archive") : name}</span>
        </Button>
    );
}
