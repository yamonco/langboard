import { memo, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router";
import { useTranslation } from "react-i18next";
import Box from "@/components/base/Box";
import Command from "@/components/base/Command";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import BaseDialog from "@/components/base/Dialog";
import useGetProjects from "@/controllers/api/dashboard/useGetProjects";
import { Project } from "@/core/models";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";
import { Utils } from "@langboard/core/utils";
import {
    buildProjectQuickSwitcherSections,
    isProjectQuickSwitcherShortcut,
    projectQuickSwitcherShortcutLabel,
    PROJECT_QUICK_SWITCHER_EVENT,
} from "@/pages/DashboardPage/components/ProjectDiscovery";

interface IProjectQuickSwitcherGroupProps {
    currentProjectUID?: string;
    heading: string;
    onSelect: (projectUID: string) => void;
    projects: Project.TModel[];
}

const ProjectQuickSwitcherGroup = ({ currentProjectUID, heading, onSelect, projects }: IProjectQuickSwitcherGroupProps) => {
    if (!projects.length) return null;

    return (
        <Command.Group heading={heading}>
            {projects.map((project) => (
                <ProjectQuickSwitcherItem
                    key={project.uid}
                    project={project}
                    active={project.uid === currentProjectUID}
                    onSelect={() => onSelect(project.uid)}
                />
            ))}
        </Command.Group>
    );
};

const ProjectQuickSwitcherItem = ({ project, active, onSelect }: { project: Project.TModel; active: bool; onSelect: () => void }) => {
    const [t, i18n] = useTranslation();
    const title = project.useField("title");
    const projectType = project.useField("project_type");
    const starred = project.useField("starred");
    const lastActivityAt = project.useField("last_activity_at");
    const createdAt = project.useField("created_at");
    const activityAt = lastActivityAt ?? createdAt;

    return (
        <Command.Item value={`${title} ${projectType}`} onSelect={onSelect} className="gap-3 rounded-lg py-2.5">
            <Flex items="center" justify="center" className="size-8 shrink-0 rounded-lg bg-secondary">
                <IconComponent icon={starred ? "star" : "folder-kanban"} size="4" />
            </Flex>
            <Box className="min-w-0 flex-1">
                <Box className="truncate font-medium">{title}</Box>
                <Box className="truncate text-xs text-muted-foreground">
                    {t(projectType === "Other" ? "common.Other" : `project.types.${projectType}`)} ·{" "}
                    {Utils.String.formatDateDistance(i18n, t, activityAt)}
                </Box>
            </Box>
            {active ? <IconComponent icon="check" size="4" className="shrink-0 text-primary" /> : null}
        </Command.Item>
    );
};

const ProjectQuickSwitcher = memo((): React.JSX.Element => {
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const location = useLocation();
    const [opened, setOpened] = useState(false);
    const { data, isFetching, isLoading } = useGetProjects({ enabled: opened });
    const projects = data?.projects ?? [];
    const sections = useMemo(() => buildProjectQuickSwitcherSections(projects), [projects]);
    const shortcutLabel = projectQuickSwitcherShortcutLabel(navigator.platform);
    const currentProjectUID = location.pathname.startsWith("/board/") ? location.pathname.split("/")[2] : undefined;

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.defaultPrevented || (event.target instanceof HTMLElement && event.target.isContentEditable)) return;
            if (!isProjectQuickSwitcherShortcut(event)) return;
            event.preventDefault();
            setOpened((current) => !current);
        };
        const open = () => setOpened(true);
        window.addEventListener("keydown", onKeyDown);
        window.addEventListener(PROJECT_QUICK_SWITCHER_EVENT, open);
        return () => {
            window.removeEventListener("keydown", onKeyDown);
            window.removeEventListener(PROJECT_QUICK_SWITCHER_EVENT, open);
        };
    }, []);

    const selectProject = (projectUID: string) => {
        setOpened(false);
        navigate(ROUTES.BOARD.MAIN(projectUID));
    };

    return (
        <Command.Dialog open={opened} onOpenChange={setOpened}>
            <BaseDialog.Title className="sr-only">{t("dashboard.Switch project")}</BaseDialog.Title>
            <BaseDialog.Description className="sr-only">{t("dashboard.Type to filter projects")}</BaseDialog.Description>
            <Command.Input placeholder={t("dashboard.Switch project...")} aria-label={t("dashboard.Switch project")} />
            <Command.List className="max-h-[min(70dvh,28rem)]">
                <Command.Empty>{isLoading || isFetching ? t("common.Loading...") : t("dashboard.No projects found")}</Command.Empty>
                <ProjectQuickSwitcherGroup
                    heading={t("dashboard.Favorites")}
                    projects={sections.favorites}
                    currentProjectUID={currentProjectUID}
                    onSelect={selectProject}
                />
                <ProjectQuickSwitcherGroup
                    heading={t("dashboard.Related to me")}
                    projects={sections.related}
                    currentProjectUID={currentProjectUID}
                    onSelect={selectProject}
                />
                <ProjectQuickSwitcherGroup
                    heading={t("dashboard.Recent work")}
                    projects={sections.recent}
                    currentProjectUID={currentProjectUID}
                    onSelect={selectProject}
                />
                <ProjectQuickSwitcherGroup
                    heading={t("dashboard.Other projects")}
                    projects={sections.other}
                    currentProjectUID={currentProjectUID}
                    onSelect={selectProject}
                />
            </Command.List>
            <Flex items="center" justify="between" className="border-t px-3 py-2 text-xs text-muted-foreground">
                <span>{t("dashboard.Type to filter projects")}</span>
                <span className="rounded border bg-muted px-1.5 py-0.5 font-mono">
                    {t("dashboard.Project switcher shortcut", { shortcut: shortcutLabel })}
                </span>
            </Flex>
        </Command.Dialog>
    );
});
ProjectQuickSwitcher.displayName = "Dashboard.ProjectQuickSwitcher";

export default ProjectQuickSwitcher;
