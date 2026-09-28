import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router";
import Input from "@/components/base/Input";
import IconComponent from "@/components/base/IconComponent";
import useGetProjects from "@/controllers/api/dashboard/useGetProjects";
import { Project } from "@/core/models";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";
import { cn } from "@/core/utils/ComponentUtils";
import { buildProjectQuickSwitcherSections, searchProjects } from "@/pages/DashboardPage/components/ProjectDiscovery";

export default function ProjectExplorerSidebar({ currentProject }: { currentProject?: Project.TModel }) {
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const location = useLocation();
    const [query, setQuery] = useState("");
    const { data } = useGetProjects();
    const projects = useMemo(() => {
        const all = data?.projects ?? [];
        return currentProject && !all.some((project) => project.uid === currentProject.uid) ? [currentProject, ...all] : all;
    }, [currentProject, data]);
    const sections = useMemo(() => buildProjectQuickSwitcherSections(projects), [projects]);
    const currentProjectUID = location.pathname.startsWith("/board/") ? location.pathname.split("/")[2] : undefined;
    const groups = query.trim()
        ? [{ title: t("dashboard.Projects"), projects: searchProjects(projects, query) }]
        : [
              { title: t("dashboard.Favorites"), projects: sections.favorites },
              { title: t("dashboard.Recent work"), projects: sections.recent },
              { title: t("dashboard.Projects"), projects: [...sections.related, ...sections.other] },
          ];

    return (
        <nav aria-label="Explorer" className="flex size-full min-w-0 flex-col overflow-hidden">
            <div className="shrink-0 border-b px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Explorer</div>
            <div className="shrink-0 p-2">
                <Input
                    value={query}
                    onChange={(event) => setQuery(event.currentTarget.value)}
                    placeholder={t("dashboard.Search projects...")}
                    aria-label={t("dashboard.Search projects")}
                    leftIcon={<IconComponent icon="search" />}
                    clearable
                />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
                {groups.map((group) =>
                    group.projects.length ? (
                        <section key={group.title} className="mb-3">
                            <h2 className="px-2 py-1 text-xs font-medium text-muted-foreground">{group.title}</h2>
                            {group.projects.map((project) => (
                                <ProjectExplorerItem
                                    key={project.uid}
                                    project={project}
                                    active={currentProjectUID === project.uid}
                                    onClick={() => navigate(ROUTES.BOARD.MAIN(project.uid))}
                                />
                            ))}
                        </section>
                    ) : null
                )}
            </div>
        </nav>
    );
}

function ProjectExplorerItem({ project, active, onClick }: { project: Project.TModel; active: boolean; onClick: () => void }) {
    const title = project.useField("title");
    const starred = project.useField("starred");
    return (
        <button
            type="button"
            onClick={onClick}
            aria-current={active ? "page" : undefined}
            className={cn(
                "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted",
                "aria-[current=page]:bg-muted aria-[current=page]:text-primary"
            )}
        >
            <IconComponent icon={starred ? "star" : "folder-kanban"} size="4" />
            <span className="truncate">{title}</span>
        </button>
    );
}
