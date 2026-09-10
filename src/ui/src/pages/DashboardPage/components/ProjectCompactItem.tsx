import { memo, useState } from "react";
import { useTranslation } from "react-i18next";
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
import { projectActivityAt, type TProjectActivityKind } from "@/pages/DashboardPage/components/ProjectActivityPriority";

interface IProjectCompactItemProps {
    activityKind?: TProjectActivityKind;
    project: Project.TModel;
    updateStarredProjects: React.DispatchWithoutAction;
}

const ProjectCompactItem = memo(({ activityKind = "project", project, updateStarredProjects }: IProjectCompactItemProps): React.JSX.Element => {
    const [t, i18n] = useTranslation();
    const navigate = usePageNavigateRef();
    const [isUpdating, setIsUpdating] = useState(false);
    const title = project.useField("title");
    const projectType = project.useField("project_type");
    const activityAt = projectActivityAt(project, activityKind);

    return (
        <ModelRegistry.Project.Provider model={project}>
            <Flex items="center" className="rounded-xl border border-transparent pr-2 hover:border-border hover:bg-accent/70">
                <Button
                    variant="ghost"
                    className="flex h-auto min-w-0 flex-1 justify-start gap-3 rounded-xl px-3 py-2.5 text-left hover:bg-transparent"
                    onClick={() => navigate(ROUTES.BOARD.MAIN(project.uid))}
                >
                    <Flex items="center" justify="center" className="size-9 shrink-0 rounded-lg bg-secondary text-secondary-foreground">
                        <IconComponent icon="folder-kanban" size="4" />
                    </Flex>
                    <Box className="min-w-0 flex-1">
                        <Box className="truncate text-sm font-semibold">{title}</Box>
                        <Flex items="center" gap="1.5" className="mt-0.5 min-w-0 text-xs text-muted-foreground">
                            <span className="truncate">{t(projectType === "Other" ? "common.Other" : `project.types.${projectType}`)}</span>
                            <span aria-hidden="true">·</span>
                            <span className="shrink-0">{Utils.String.formatDateDistance(i18n, t, activityAt)}</span>
                        </Flex>
                    </Box>
                </Button>
                <ProjectItemStarButton compact isUpdating={isUpdating} setIsUpdating={setIsUpdating} updateStarredProjects={updateStarredProjects} />
            </Flex>
        </ModelRegistry.Project.Provider>
    );
});
ProjectCompactItem.displayName = "Dashboard.ProjectCompactItem";

export default ProjectCompactItem;
