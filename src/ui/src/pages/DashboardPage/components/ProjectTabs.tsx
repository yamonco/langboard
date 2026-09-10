import { memo, useMemo, useReducer, useState } from "react";
import { useTranslation } from "react-i18next";
import { Search } from "lucide-react";
import Box from "@/components/base/Box";
import Input from "@/components/base/Input";
import Skeleton from "@/components/base/Skeleton";
import Tabs from "@/components/base/Tabs";
import type { IGetProjectsResponse } from "@/controllers/api/dashboard/useGetProjects";
import { useDebounce } from "@/core/hooks/useDebounce";
import { ROUTES } from "@/core/routing/constants";
import { Utils } from "@langboard/core/utils";
import ProjectList, { SkeletonProjectList } from "@/pages/DashboardPage/components/ProjectList";
import { PROJECT_TABS, TProjectTab, TProjectTabRoute } from "@/pages/DashboardPage/constants";
import { Project } from "@/core/models";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { compareProjectActivityPriority } from "@/pages/DashboardPage/components/ProjectActivityPriority";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import ProjectCompactList from "@/pages/DashboardPage/components/ProjectCompactList";
import {
    buildProjectDiscoverySections,
    parseProjectListView,
    projectListViewStorageKey,
    type TProjectListView,
} from "@/pages/DashboardPage/components/ProjectDiscovery";

export function SkeletonProjecTabs() {
    return (
        <>
            <Box display="grid" gap="1" h="10" p="1" className="grid-cols-4">
                <Skeleton h="8" />
                <Skeleton h="8" />
                <Skeleton h="8" />
                <Skeleton h="8" />
            </Box>
            <Box px="2" mt="3">
                <Skeleton h="9" />
            </Box>
            <Box mt="2">
                <SkeletonProjectList />
            </Box>
        </>
    );
}

interface IProjectTabsProps {
    currentTab: TProjectTab;
    userUID: string;
    projectsData?: IGetProjectsResponse;
    isProjectsFetching: bool;
    isProjectsLoading: bool;
    updateStarredProjects: React.DispatchWithoutAction;
    scrollAreaUpdater: [number, React.DispatchWithoutAction];
}

const ProjectTabs = memo(
    ({
        currentTab,
        userUID,
        projectsData,
        isProjectsFetching,
        isProjectsLoading,
        updateStarredProjects: updateHeaderStarredProjects,
        scrollAreaUpdater,
    }: IProjectTabsProps): React.JSX.Element => {
        const navigate = usePageNavigateRef();
        const [updatedStarredProjects, updateStarredProjects] = useReducer((x) => x + 1, 0);
        const [searchQuery, setSearchQuery] = useState("");
        const storageKey = projectListViewStorageKey(userUID);
        const [projectListView, setProjectListView] = useState<TProjectListView>(() => parseProjectListView(localStorage.getItem(storageKey)));
        const debouncedSearchQuery = useDebounce(searchQuery.trim(), 300);
        const [t] = useTranslation();

        const projectUIDs = useMemo(() => (projectsData?.projects ?? []).map((project) => project.uid), [projectsData]);
        const loadedProjects = Project.Model.useModels((model) => projectUIDs.includes(model.uid), [projectUIDs, updatedStarredProjects]);
        const projects = useMemo(() => {
            const projectsByUID = new Map(loadedProjects.map((project) => [project.uid, project]));
            return projectUIDs.map((projectUID) => projectsByUID.get(projectUID)).filter((project): project is Project.TModel => !!project);
        }, [loadedProjects, projectUIDs]);

        const currentProjects = useMemo(() => {
            const query = debouncedSearchQuery.toLowerCase();
            const filteredProjects = projects.filter((project) => {
                if (query && !project.title.toLowerCase().includes(query)) {
                    return false;
                }

                switch (currentTab) {
                    case "starred":
                        return project.starred;
                    case "unstarred":
                        return !project.starred;
                    default:
                        return true;
                }
            });

            return [...filteredProjects].sort(compareProjectActivityPriority);
        }, [currentTab, debouncedSearchQuery, projects, updatedStarredProjects]);
        const discoverySections = useMemo(() => buildProjectDiscoverySections(currentProjects), [currentProjects]);

        const changeProjectListView = (view: TProjectListView) => {
            setProjectListView(view);
            localStorage.setItem(storageKey, view);
        };

        const navigateToTab = (tab: IProjectTabsProps["currentTab"]) => {
            if (tab === currentTab) {
                return;
            }

            navigate(ROUTES.DASHBOARD.PROJECTS[tab.toUpperCase() as TProjectTabRoute]);
        };

        return (
            <Tabs.Provider value={currentTab}>
                <Box px="2">
                    <Tabs.List className="grid w-full grid-cols-4 gap-1">
                        {PROJECT_TABS.map((tab) => (
                            <Tabs.Trigger value={tab} key={Utils.String.Token.reactKey(`dashboard.tabs.${tab}`)} onClick={() => navigateToTab(tab)}>
                                {t(`dashboard.tabs.${tab}`)}
                            </Tabs.Trigger>
                        ))}
                    </Tabs.List>
                </Box>
                <Box px="2" mt="3">
                    <Input
                        value={searchQuery}
                        onChange={(event) => setSearchQuery(event.currentTarget.value)}
                        placeholder={t("dashboard.Search projects...")}
                        aria-label={t("dashboard.Search projects")}
                        leftIcon={<Search />}
                        clearable
                    />
                </Box>
                <Flex role="group" justify="end" gap="1" px="2" mt="2" aria-label={t("dashboard.Project view") as string}>
                    <Button
                        type="button"
                        size="icon-sm"
                        variant={projectListView === "compact" ? "secondary" : "ghost"}
                        title={t("dashboard.Compact view")}
                        aria-label={t("dashboard.Compact view")}
                        aria-pressed={projectListView === "compact"}
                        onClick={() => changeProjectListView("compact")}
                    >
                        <IconComponent icon="list" size="4" />
                    </Button>
                    <Button
                        type="button"
                        size="icon-sm"
                        variant={projectListView === "cards" ? "secondary" : "ghost"}
                        title={t("dashboard.Card view")}
                        aria-label={t("dashboard.Card view")}
                        aria-pressed={projectListView === "cards"}
                        onClick={() => changeProjectListView("cards")}
                    >
                        <IconComponent icon="layout-grid" size="4" />
                    </Button>
                </Flex>
                <Tabs.Content value={currentTab}>
                    {(isProjectsLoading || isProjectsFetching) && currentProjects.length === 0 ? (
                        <SkeletonProjectList />
                    ) : currentProjects.length === 0 ? (
                        <h2 className="py-3 text-center text-lg text-accent-foreground">{t("dashboard.No projects found")}</h2>
                    ) : projectListView === "cards" ? (
                        <ProjectList
                            projects={currentProjects}
                            updateStarredProjects={() => {
                                updateHeaderStarredProjects();
                                updateStarredProjects();
                            }}
                            scrollAreaUpdater={scrollAreaUpdater}
                        />
                    ) : debouncedSearchQuery ? (
                        <ProjectCompactList
                            title={t("dashboard.Search results")}
                            projects={discoverySections.all}
                            updateStarredProjects={() => {
                                updateHeaderStarredProjects();
                                updateStarredProjects();
                            }}
                        />
                    ) : currentTab === "all" ? (
                        <>
                            <ProjectCompactList
                                title={t("dashboard.Favorites")}
                                projects={discoverySections.favorites}
                                updateStarredProjects={() => {
                                    updateHeaderStarredProjects();
                                    updateStarredProjects();
                                }}
                            />
                            <ProjectCompactList
                                title={t("dashboard.Related to me")}
                                activityKind="related"
                                projects={discoverySections.related}
                                updateStarredProjects={() => {
                                    updateHeaderStarredProjects();
                                    updateStarredProjects();
                                }}
                            />
                            <ProjectCompactList
                                title={t("dashboard.Recent work")}
                                projects={discoverySections.recent}
                                updateStarredProjects={() => {
                                    updateHeaderStarredProjects();
                                    updateStarredProjects();
                                }}
                            />
                            <ProjectCompactList
                                title={t("dashboard.All projects")}
                                projects={discoverySections.all}
                                updateStarredProjects={() => {
                                    updateHeaderStarredProjects();
                                    updateStarredProjects();
                                }}
                            />
                        </>
                    ) : (
                        <ProjectCompactList
                            projects={discoverySections.all}
                            updateStarredProjects={() => {
                                updateHeaderStarredProjects();
                                updateStarredProjects();
                            }}
                        />
                    )}
                </Tabs.Content>
            </Tabs.Provider>
        );
    }
);

export default ProjectTabs;
