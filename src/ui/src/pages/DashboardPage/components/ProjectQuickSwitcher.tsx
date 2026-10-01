import { memo, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router";
import { useTranslation } from "react-i18next";
import useSearchWikis from "@/controllers/api/wiki/useSearchWikis";
import { useDebounce } from "@/core/hooks/useDebounce";
import Box from "@/components/base/Box";
import Command from "@/components/base/Command";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import BaseDialog from "@/components/base/Dialog";
import { projectTypeLabel } from "@/pages/DashboardPage/components/ProjectTypeCopy";
import useGetProjects from "@/controllers/api/dashboard/useGetProjects";
import { Project, ProjectCard } from "@/core/models";
import { useAuth } from "@/core/providers/AuthProvider";
import { useOpenCards } from "@/pages/DashboardPage/components/OpenCardsStore";
import { WORKBENCH_OPEN_CHANGES_EVENT, WORKBENCH_OPEN_MY_WORK_EVENT, WORKBENCH_TOGGLE_CONTEXT_EVENT } from "./WorkbenchCommands";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";
import { Utils } from "@langboard/core/utils";
import {
    buildCommandPaletteCards,
    buildProjectQuickSwitcherSections,
    isProjectQuickSwitcherShortcut,
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
        <Command.Item value={project.uid} keywords={[title, projectType]} onSelect={onSelect} className="gap-3 rounded-lg py-2.5">
            <Flex items="center" justify="center" className="size-8 shrink-0 rounded-lg bg-secondary">
                <IconComponent icon={starred ? "star" : "folder-kanban"} size="4" />
            </Flex>
            <Box className="min-w-0 flex-1">
                <Box className="truncate font-medium">{title}</Box>
                <Box className="truncate text-xs text-muted-foreground">
                    {projectTypeLabel(t, projectType)} · {Utils.String.formatDateDistance(i18n, t, activityAt)}
                </Box>
            </Box>
            {active ? <IconComponent icon="check" size="4" className="shrink-0 text-primary" /> : null}
        </Command.Item>
    );
};

const ProjectQuickSwitcher = memo((): React.JSX.Element => {
    const [t] = useTranslation();
    const { currentUser } = useAuth();
    const navigate = usePageNavigateRef();
    const location = useLocation();
    const [opened, setOpened] = useState(false);
    const projectNavigation = useRef(false);
    const actionSelected = useRef<boolean | string>(false);
    const returnFocus = useRef<HTMLElement | null>(null);
    const [searchText, setSearchText] = useState("");
    const wikiQuery = useDebounce(searchText.trim(), 300);
    const { data, isFetching, isLoading } = useGetProjects({ enabled: opened });
    const projects = data?.projects ?? [];
    const openCards = useOpenCards(currentUser?.uid);
    const sections = useMemo(() => buildProjectQuickSwitcherSections(projects), [projects]);
    const currentProjectUID = location.pathname.startsWith("/board/") ? location.pathname.split("/")[2] : undefined;
    const wikiSearch = useSearchWikis(currentProjectUID, wikiQuery, opened);
    const boardCards = ProjectCard.Model.useModels(
        (card) => opened && card.project_uid === currentProjectUID && card.source_type !== "project_wiki",
        [opened, currentProjectUID]
    );
    const cards = useMemo(() => {
        const authorized = new Set(projects.map((project) => project.uid));
        return buildCommandPaletteCards(
            openCards,
            boardCards.map((card) => ({ projectUID: card.project_uid, cardUID: card.uid, title: card.title })),
            authorized
        );
    }, [openCards, boardCards, projects]);

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.defaultPrevented || (event.target instanceof HTMLElement && event.target.isContentEditable)) return;
            if (!isProjectQuickSwitcherShortcut(event)) return;
            event.preventDefault();
            if (!opened) {
                returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
                actionSelected.current = false;
            }
            setOpened((current) => !current);
        };
        const open = () => {
            if (!opened) {
                returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
                actionSelected.current = false;
            }
            setOpened(true);
        };
        window.addEventListener("keydown", onKeyDown);
        window.addEventListener(PROJECT_QUICK_SWITCHER_EVENT, open);
        return () => {
            window.removeEventListener("keydown", onKeyDown);
            window.removeEventListener(PROJECT_QUICK_SWITCHER_EVENT, open);
        };
    }, [opened]);

    const selectProject = (projectUID: string) => {
        projectNavigation.current = true;
        setOpened(false);
        navigate(ROUTES.BOARD.MAIN(projectUID), { state: { commandPaletteFocus: true } });
    };
    const selectRoute = (route: string) => {
        actionSelected.current = true;
        setOpened(false);
        navigate(route);
    };
    const selectCommand = (eventName: string) => {
        actionSelected.current = eventName;
        setOpened(false);
        window.dispatchEvent(new Event(eventName));
    };

    return (
        <Command.Dialog
            open={opened}
            onCloseAutoFocus={(event) => {
                event.preventDefault();
                if (actionSelected.current) {
                    if (actionSelected.current === WORKBENCH_OPEN_MY_WORK_EVENT) {
                        document.querySelector<HTMLElement>("[data-my-work-context]")?.focus({ preventScroll: true });
                    }
                    return;
                }
                const previous = returnFocus.current;
                if (!projectNavigation.current && previous?.isConnected && previous !== document.body) {
                    previous.focus({ preventScroll: true });
                    return;
                }
                projectNavigation.current = false;
                document.querySelector<HTMLButtonElement>("[data-command-palette-trigger]")?.focus({ preventScroll: true });
            }}
            onOpenChange={(open) => {
                setOpened(open);
                if (!open) setSearchText("");
            }}
        >
            <BaseDialog.Title className="sr-only">{t("dashboard.Command palette")}</BaseDialog.Title>
            <BaseDialog.Description className="sr-only">{t("dashboard.Search projects, cards and commands")}</BaseDialog.Description>
            <Command.Input
                value={searchText}
                onValueChange={setSearchText}
                placeholder={t("dashboard.Search projects, cards and commands")}
                aria-label={t("dashboard.Command palette")}
            />
            <Command.List className="max-h-[min(70dvh,28rem)]">
                <Command.Empty>{isLoading || isFetching ? t("common.Loading...") : t("dashboard.No commands found")}</Command.Empty>
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
                <Command.Group heading={t("dashboard.Actions")}>
                    {currentProjectUID && (
                        <Command.Item
                            value="action:new-card"
                            keywords={[t("board.Add a card")]}
                            onSelect={() => selectRoute(`${ROUTES.BOARD.MAIN(currentProjectUID)}?new-card=1`)}
                            className="gap-3 rounded-lg"
                        >
                            <IconComponent icon="plus" size="4" />
                            {t("dashboard.New card")}
                        </Command.Item>
                    )}
                    <Command.Item
                        value="action:new-project"
                        keywords={[t("dashboard.Create New Project")]}
                        onSelect={() => selectRoute(`${ROUTES.DASHBOARD.PROJECTS.ALL}/new-project`)}
                        className="gap-3 rounded-lg"
                    >
                        <IconComponent icon="folder-plus" size="4" />
                        {t("dashboard.New project")}
                    </Command.Item>
                    <Command.Item
                        value="action:toggle-sidebar"
                        onSelect={() => selectCommand(WORKBENCH_TOGGLE_CONTEXT_EVENT)}
                        className="gap-3 rounded-lg"
                    >
                        <IconComponent icon="panel-left" size="4" />
                        {t("dashboard.Toggle sidebar")}
                    </Command.Item>
                </Command.Group>
                {cards.length > 0 && (
                    <Command.Group heading={t("dashboard.Cards")}>
                        {cards.map((card) => (
                            <Command.Item
                                key={`${card.projectUID}:${card.cardUID}`}
                                value={`card:${card.projectUID}:${card.cardUID}`}
                                keywords={[card.title, projects.find((project) => project.uid === card.projectUID)?.title ?? ""]}
                                onSelect={() => selectRoute(ROUTES.BOARD.CARD(card.projectUID, card.cardUID))}
                                className="gap-3 rounded-lg"
                            >
                                <IconComponent icon="file-text" size="4" />
                                <span className="truncate">{card.title}</span>
                            </Command.Item>
                        ))}
                    </Command.Group>
                )}
                {opened && searchText.trim() === wikiQuery && wikiSearch.data?.items.length ? (
                    <Command.Group heading={t("board.Wiki")}>
                        {wikiSearch.data.items.map((wiki) => (
                            <Command.Item
                                key={wiki.wiki_uid}
                                value={`wiki:${wiki.wiki_uid}`}
                                keywords={[wiki.title, wikiQuery]}
                                onSelect={() => selectRoute(ROUTES.BOARD.WIKI_PAGE(currentProjectUID!, wiki.wiki_uid))}
                                className="gap-3 rounded-lg"
                            >
                                <IconComponent icon="notebook-pen" size="4" />
                                <span className="min-w-0 flex-1">
                                    <span className="block truncate">{wiki.title}</span>
                                    {wiki.snippet && <span className="block truncate text-xs text-muted-foreground">{wiki.snippet}</span>}
                                </span>
                            </Command.Item>
                        ))}
                        {wikiSearch.data.next_cursor && (
                            <div className="px-2 py-1 text-xs text-muted-foreground">{t("dashboard.Refine your search for more wiki results")}</div>
                        )}
                    </Command.Group>
                ) : null}
                <Command.Group heading={t("dashboard.Navigation")}>
                    <Command.Item
                        value="navigation:my-work"
                        onSelect={() =>
                            currentProjectUID || location.pathname.startsWith("/dashboard/")
                                ? selectCommand(WORKBENCH_OPEN_MY_WORK_EVENT)
                                : selectRoute(ROUTES.DASHBOARD.MY_WORK)
                        }
                        className="gap-3 rounded-lg"
                    >
                        <IconComponent icon="list-checks" size="4" />
                        {t("dashboard.My Work")}
                    </Command.Item>
                    {currentProjectUID && (
                        <>
                            <Command.Item
                                value="navigation:changes"
                                onSelect={() => selectCommand(WORKBENCH_OPEN_CHANGES_EVENT)}
                                className="gap-3 rounded-lg"
                            >
                                <IconComponent icon="history" size="4" />
                                {t("dashboard.Changes")}
                            </Command.Item>
                            <Command.Item
                                value="navigation:relations"
                                onSelect={() => selectRoute(ROUTES.BOARD.GRAPH(currentProjectUID))}
                                className="gap-3 rounded-lg"
                            >
                                <IconComponent icon="network" size="4" />
                                {t("dashboard.Relations")}
                            </Command.Item>
                        </>
                    )}
                </Command.Group>
            </Command.List>
            <Flex items="center" justify="between" className="hidden border-t px-3 py-2 text-xs text-muted-foreground sm:flex">
                <span>{t("dashboard.Search projects, cards and commands")}</span>
                <span className="rounded border bg-muted px-1.5 py-0.5 font-mono">⌘K / Ctrl K</span>
            </Flex>
        </Command.Dialog>
    );
});
ProjectQuickSwitcher.displayName = "Dashboard.ProjectQuickSwitcher";

export default ProjectQuickSwitcher;
