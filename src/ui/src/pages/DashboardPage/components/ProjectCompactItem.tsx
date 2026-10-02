import { memo, useState } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/core/utils/ComponentUtils";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import { Project } from "@/core/models";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";
import { Utils } from "@langboard/core/utils";
import ProjectItemStarButton from "@/pages/DashboardPage/components/ProjectItemStarButton";
import ContextMenu from "@/components/base/ContextMenu";
import { projectTypeLabel } from "@/pages/DashboardPage/components/ProjectTypeCopy";

import ProjectWorkloadBadges from "./ProjectWorkloadBadges";

interface IProjectCompactItemProps {
    project: Project.TModel;
    dense?: boolean;
    updateStarredProjects: React.DispatchWithoutAction;
}

const ProjectCompactItem = memo(({ project, updateStarredProjects, dense }: IProjectCompactItemProps): React.JSX.Element => {
    const [t, i18n] = useTranslation();
    const navigate = usePageNavigateRef();
    const [isUpdating, setIsUpdating] = useState(false);
    const title = project.useField("title");
    const projectType = project.useField("project_type");
    const boardHasUnread = project.useField("board_has_unread_change") ?? false;
    const activityAt = project.last_activity_at ?? project.created_at;

    return (
        <ModelRegistry.Project.Provider model={project}>
            <ContextMenu.Root>
                <ContextMenu.Trigger asChild>
                    <Flex
                        items="center"
                        style={{ containerType: "inline-size", containerName: "project-workload" }}
                        className="group min-w-0 rounded-xl border border-transparent pr-2 hover:border-border hover:bg-accent/70"
                    >
                        <Button
                            variant="ghost"
                            className={cn(
                                "flex h-auto min-w-0 flex-1 justify-start gap-3 rounded-xl px-3 text-left hover:bg-transparent",
                                dense ? "py-1.5" : "py-2.5"
                            )}
                            onClick={() => navigate(ROUTES.BOARD.MAIN(project.uid))}
                        >
                            <Flex
                                items="center"
                                justify="center"
                                className={cn("relative shrink-0 rounded-lg bg-secondary text-secondary-foreground", dense ? "size-7" : "size-9")}
                            >
                                <IconComponent icon="folder-kanban" size="4" />
                                {boardHasUnread ? (
                                    <span
                                        aria-label={t("board.Unread changes")}
                                        title={t("board.Unread changes")}
                                        className="absolute -right-1 -top-1 z-10 size-2 rounded-full bg-primary"
                                    />
                                ) : null}
                            </Flex>
                            <Box className="min-w-0 flex-1">
                                <Box className="truncate text-sm font-semibold" title={title}>
                                    {title}
                                </Box>
                                <Flex items="center" gap="1.5" className="mt-0.5 min-w-0 text-xs text-muted-foreground">
                                    <span className="truncate">{projectTypeLabel(t, projectType)}</span>
                                    <span aria-hidden="true">·</span>
                                    <span className="min-w-0 truncate">{Utils.String.formatDateDistance(i18n, t, activityAt)}</span>
                                </Flex>
                            </Box>
                        </Button>
                        <ProjectWorkloadBadges projectUID={project.uid} compact />
                        <ProjectItemStarButton
                            compact
                            isUpdating={isUpdating}
                            setIsUpdating={setIsUpdating}
                            updateStarredProjects={updateStarredProjects}
                        />
                    </Flex>
                </ContextMenu.Trigger>
                <ContextMenu.Content>
                    <ContextMenu.Item onSelect={() => navigate(ROUTES.BOARD.MAIN(project.uid))}>{title}</ContextMenu.Item>
                    <ProjectItemStarButton
                        menuItem
                        isUpdating={isUpdating}
                        setIsUpdating={setIsUpdating}
                        updateStarredProjects={updateStarredProjects}
                    />
                </ContextMenu.Content>
            </ContextMenu.Root>
        </ModelRegistry.Project.Provider>
    );
});
ProjectCompactItem.displayName = "Dashboard.ProjectCompactItem";

export default ProjectCompactItem;
