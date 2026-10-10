import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router";
import { useAuth } from "@/core/providers/AuthProvider";
import { getUserSettingsStore, useUserSettings } from "@/core/stores/UserSettingsStore";
import { retainProjects, useOpenCards } from "./OpenCardsStore";
import { recentOpenCards } from "./OpenCardsData";
import RecentCardsSection from "./RecentCardsSection";
import Input from "@/components/base/Input";
import Button from "@/components/base/Button";
import IconComponent from "@/components/base/IconComponent";
import useGetProjects from "@/controllers/api/dashboard/useGetProjects";
import { Project } from "@/core/models";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";
import { cn } from "@/core/utils/ComponentUtils";
import { buildProjectQuickSwitcherSections, searchProjects } from "@/pages/DashboardPage/components/ProjectDiscovery";

import ProjectWorkloadBadges from "./ProjectWorkloadBadges";

export default function ProjectExplorerSidebar({ currentProject, onNavigate }: { currentProject?: Project.TModel; onNavigate?: () => void }) {
    const [t] = useTranslation();
    const { currentUser } = useAuth();
    const userUID = currentUser?.uid;
    const openCards = useOpenCards(userUID);
    const wikiHintDismissed = useUserSettings("wiki_hint_dismissed");
    const collapsedByUser = useUserSettings("explorer_open_cards_collapsed");
    const openCardsCollapsed = !!(userUID && collapsedByUser?.[userUID]);
    const navigate = usePageNavigateRef();
    const location = useLocation();
    const [query, setQuery] = useState("");
    const { data, isPending, isError, isFetching, refetch } = useGetProjects({ refetchOnWindowFocus: true });
    const authorizedProjectUIDs = useMemo(() => new Set(data?.projects.map((project) => project.uid) ?? []), [data]);
    const [showOlderCards, setShowOlderCards] = useState(false);
    useEffect(() => setShowOlderCards(false), [userUID]);
    const visibleOpenCards = recentOpenCards(openCards.filter((card) => authorizedProjectUIDs.has(card.projectUID)));
    const projects = useMemo(() => {
        const all = data?.projects ?? [];
        return currentProject && !all.some((project) => project.uid === currentProject.uid) ? [currentProject, ...all] : all;
    }, [currentProject, data]);
    useEffect(() => {
        if (!data || !userUID) return;
        if (openCards.some((card) => !authorizedProjectUIDs.has(card.projectUID))) {
            retainProjects(userUID, authorizedProjectUIDs);
        }
    }, [data, openCards, authorizedProjectUIDs, userUID]);
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
        <nav aria-label={t("common.Explorer")} data-workbench-explorer="" className="flex size-full min-w-0 flex-col overflow-hidden">
            <div className="shrink-0 border-b px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t("common.Explorer")}
            </div>
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
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-2 pb-3">
                {currentProject && !query.trim() && (
                    <section className="mb-3 shrink-0" aria-label={currentProject.title}>
                        <h2 className="px-2 py-1 text-xs font-medium text-muted-foreground">{currentProject.title}</h2>
                        {userUID && !wikiHintDismissed?.[userUID] && (
                            <div className="mb-1 flex items-start gap-1 rounded-md bg-muted/50 px-2 py-1.5 text-xs text-muted-foreground">
                                <span className="flex-1">{t("dashboard.Project documents are in Wiki")}</span>
                                <button
                                    type="button"
                                    aria-label={t("common.Close")}
                                    onClick={() =>
                                        getUserSettingsStore().updateSettingsByKey("wiki_hint_dismissed", {
                                            ...wikiHintDismissed,
                                            [userUID]: true,
                                        })
                                    }
                                    className="rounded p-0.5 hover:bg-accent"
                                >
                                    <IconComponent icon="x" size="3" />
                                </button>
                            </div>
                        )}
                        {(
                            [
                                { name: t("board.Board"), icon: "columns-3", route: ROUTES.BOARD.MAIN(currentProject.uid) },
                                { name: t("board.Wiki"), icon: "notebook-pen", route: ROUTES.BOARD.WIKI(currentProject.uid) },
                            ] as const
                        ).map((item) => (
                            <button
                                key={item.route}
                                type="button"
                                aria-current={
                                    location.pathname === item.route ||
                                    (item.icon === "notebook-pen" && location.pathname.startsWith(`${item.route}/`))
                                        ? "page"
                                        : undefined
                                }
                                className={cn(
                                    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted",
                                    "aria-[current=page]:bg-muted aria-[current=page]:text-primary"
                                )}
                                onClick={() => {
                                    navigate(item.route);
                                    onNavigate?.();
                                }}
                            >
                                <IconComponent icon={item.icon} size="4" />
                                <span>{item.name}</span>
                            </button>
                        ))}
                    </section>
                )}
                {!query.trim() && userUID && (
                    <RecentCardsSection
                        userUID={userUID}
                        cards={visibleOpenCards}
                        collapsed={openCardsCollapsed}
                        expanded={showOlderCards}
                        onExpand={() => setShowOlderCards((shown) => !shown)}
                        onToggle={() =>
                            getUserSettingsStore().updateSettingsByKey("explorer_open_cards_collapsed", {
                                ...collapsedByUser,
                                [userUID]: !openCardsCollapsed,
                            })
                        }
                        onNavigate={onNavigate}
                    />
                )}
                <div className="min-h-24 flex-1 overflow-y-auto" data-explorer-project-list="">
                    {isPending && (
                        <p role="status" className="px-2 py-3 text-xs text-muted-foreground">
                            {t("common.Loading...")}
                        </p>
                    )}
                    {isError && (
                        <div role="alert" className="flex flex-wrap items-center gap-2 px-2 py-3">
                            <span className="text-xs text-muted-foreground">{t("dashboard.Could not load projects")}</span>
                            <Button type="button" size="sm" variant="outline" disabled={isFetching} onClick={() => void refetch()}>
                                {t("dashboard.Retry")}
                            </Button>
                        </div>
                    )}
                    {groups.map((group) =>
                        group.projects.length ? (
                            <section key={group.title} className="mb-3">
                                <h2 className="px-2 py-1 text-xs font-medium text-muted-foreground">{group.title}</h2>
                                {group.projects.map((project) => (
                                    <ProjectExplorerItem
                                        key={project.uid}
                                        project={project}
                                        active={currentProjectUID === project.uid}
                                        onNavigate={onNavigate}
                                        onClick={() => {
                                            navigate(ROUTES.BOARD.MAIN(project.uid), { state: { commandPaletteFocus: true } });
                                            onNavigate?.();
                                        }}
                                    />
                                ))}
                            </section>
                        ) : null
                    )}
                </div>
            </div>
        </nav>
    );
}

function ProjectExplorerItem({
    project,
    active,
    onClick,
    onNavigate,
}: {
    project: Project.TModel;
    active: boolean;
    onClick: () => void;
    onNavigate?: () => void;
}) {
    const title = project.useField("title");
    const starred = project.useField("starred");
    return (
        <div className="flex min-w-0 items-center gap-1" style={{ containerType: "inline-size", containerName: "project-workload" }}>
            <button
                type="button"
                onClick={onClick}
                aria-current={active ? "page" : undefined}
                className={cn(
                    "flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted",
                    "aria-[current=page]:bg-muted aria-[current=page]:text-primary"
                )}
            >
                <IconComponent icon={starred ? "star" : "folder-kanban"} size="4" />
                <span className="truncate">{title}</span>
            </button>
            <ProjectWorkloadBadges projectUID={project.uid} compact onNavigate={onNavigate} />
        </div>
    );
}
