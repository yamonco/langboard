import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router";
import { useAuth } from "@/core/providers/AuthProvider";
import { getUserSettingsStore, useUserSettings } from "@/core/stores/UserSettingsStore";
import { closeCard, retainProjects, toggleCardPin, useOpenCards } from "./OpenCardsStore";
import Input from "@/components/base/Input";
import IconComponent from "@/components/base/IconComponent";
import useGetProjects from "@/controllers/api/dashboard/useGetProjects";
import { Project } from "@/core/models";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";
import { cn } from "@/core/utils/ComponentUtils";
import { buildProjectQuickSwitcherSections, searchProjects } from "@/pages/DashboardPage/components/ProjectDiscovery";

export default function ProjectExplorerSidebar({ currentProject, onNavigate }: { currentProject?: Project.TModel; onNavigate?: () => void }) {
    const [t] = useTranslation();
    const { currentUser } = useAuth();
    const userUID = currentUser?.uid;
    const openCards = useOpenCards(userUID);
    const collapsedByUser = useUserSettings("explorer_open_cards_collapsed");
    const openCardsCollapsed = !!(userUID && collapsedByUser?.[userUID]);
    const navigate = usePageNavigateRef();
    const location = useLocation();
    const [query, setQuery] = useState("");
    const { data } = useGetProjects();
    const projects = useMemo(() => {
        const all = data?.projects ?? [];
        return currentProject && !all.some((project) => project.uid === currentProject.uid) ? [currentProject, ...all] : all;
    }, [currentProject, data]);
    useEffect(() => {
        if (!data || !userUID) return;
        const authorizedProjectUIDs = new Set(projects.map((project) => project.uid));
        if (openCards.some((card) => !authorizedProjectUIDs.has(card.projectUID))) {
            retainProjects(userUID, authorizedProjectUIDs);
        }
    }, [data, openCards, projects, userUID]);
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
                {!query.trim() && userUID && (
                    <section className="mb-3" aria-label={t("dashboard.Open cards")}>
                        <button
                            type="button"
                            aria-expanded={!openCardsCollapsed}
                            className="flex w-full items-center gap-1 px-2 py-1 text-left text-xs font-medium text-muted-foreground"
                            onClick={() =>
                                getUserSettingsStore().updateSettingsByKey("explorer_open_cards_collapsed", {
                                    ...collapsedByUser,
                                    [userUID]: !openCardsCollapsed,
                                })
                            }
                        >
                            <IconComponent icon={openCardsCollapsed ? "chevron-right" : "chevron-down"} size="3" />
                            {t("dashboard.Open cards")}
                            {openCards.length > 0 && <span className="ml-auto">{openCards.length}</span>}
                        </button>
                        {!openCardsCollapsed &&
                            openCards.map((card) => {
                                const active = location.pathname === ROUTES.BOARD.CARD(card.projectUID, card.cardUID);
                                return (
                                    <div
                                        key={`${card.projectUID}:${card.cardUID}`}
                                        className="group flex min-h-8 items-center rounded-md hover:bg-muted"
                                    >
                                        <button
                                            type="button"
                                            aria-current={active ? "page" : undefined}
                                            title={card.title}
                                            className={cn(
                                                "flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1 text-left text-sm",
                                                active && "bg-muted text-primary"
                                            )}
                                            onClick={() => {
                                                navigate(ROUTES.BOARD.CARD(card.projectUID, card.cardUID));
                                                onNavigate?.();
                                            }}
                                        >
                                            <IconComponent icon="file-text" size="3" className="shrink-0" />
                                            <span className="truncate">{card.title}</span>
                                        </button>
                                        <button
                                            type="button"
                                            aria-label={t(card.pinned ? "dashboard.Unpin card" : "dashboard.Pin card")}
                                            title={t(card.pinned ? "dashboard.Unpin card" : "dashboard.Pin card")}
                                            className={cn(
                                                "rounded p-1 hover:bg-accent",
                                                !card.pinned && "opacity-0 focus:opacity-100 group-hover:opacity-100"
                                            )}
                                            onClick={() => toggleCardPin(userUID, card.projectUID, card.cardUID)}
                                        >
                                            <IconComponent icon="pin" size="3" className={card.pinned ? "text-primary" : undefined} />
                                        </button>
                                        <button
                                            type="button"
                                            aria-label={t("dashboard.Close card from list")}
                                            title={t("dashboard.Close card from list")}
                                            className="mr-1 rounded p-1 opacity-0 hover:bg-accent focus:opacity-100 group-hover:opacity-100"
                                            onClick={() => closeCard(userUID, card.projectUID, card.cardUID)}
                                        >
                                            <IconComponent icon="x" size="3" />
                                        </button>
                                    </div>
                                );
                            })}
                    </section>
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
                                    onClick={() => {
                                        navigate(ROUTES.BOARD.MAIN(project.uid));
                                        onNavigate?.();
                                    }}
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
