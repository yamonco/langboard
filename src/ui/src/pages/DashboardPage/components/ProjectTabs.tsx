import { memo, useEffect, useMemo, useReducer, useState } from "react";
import { useTranslation } from "react-i18next";
import { Search } from "lucide-react";
import Box from "@/components/base/Box";
import Input from "@/components/base/Input";
import Skeleton from "@/components/base/Skeleton";
import type { IGetProjectsResponse } from "@/controllers/api/dashboard/useGetProjects";
import { useDebounce } from "@/core/hooks/useDebounce";
import ProjectList, { SkeletonProjectList } from "@/pages/DashboardPage/components/ProjectList";
import { TProjectTab } from "@/pages/DashboardPage/constants";
import { Project } from "@/core/models";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import ProjectCompactList from "@/pages/DashboardPage/components/ProjectCompactList";
import {
    buildProjectDiscoverySections,
    parseProjectListView,
    projectListViewStorageKey,
    searchProjects,
    PROJECT_QUICK_SWITCHER_EVENT,
    type TProjectListView,
} from "@/pages/DashboardPage/components/ProjectDiscovery";

export function SkeletonProjecTabs() {
    return (
        <>
            <Box px="2" mt="3">
                <Skeleton h="9" />
            </Box>
            <Flex justify="end" gap="1" px="2" mt="2">
                <Skeleton className="size-8" />
                <Skeleton className="size-8" />
            </Flex>
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
        userUID,
        projectsData,
        isProjectsFetching,
        isProjectsLoading,
        updateStarredProjects: updateHeaderStarredProjects,
        scrollAreaUpdater,
    }: IProjectTabsProps): React.JSX.Element => {
        const [updatedStarredProjects, updateStarredProjects] = useReducer((x) => x + 1, 0);
        const [searchQuery, setSearchQuery] = useState("");
        const storageKey = projectListViewStorageKey(userUID);
        const [projectListView, setProjectListView] = useState<TProjectListView>(() => parseProjectListView(localStorage.getItem(storageKey)));
        useEffect(() => setProjectListView(parseProjectListView(localStorage.getItem(storageKey))), [storageKey]);
        const debouncedSearchQuery = useDebounce(searchQuery.trim(), 300);
        const [t] = useTranslation();

        const projectUIDs = useMemo(() => (projectsData?.projects ?? []).map((project) => project.uid), [projectsData]);
        const loadedProjects = Project.Model.useModels((model) => projectUIDs.includes(model.uid), [projectUIDs, updatedStarredProjects]);
        const projects = useMemo(() => {
            const projectsByUID = new Map(loadedProjects.map((project) => [project.uid, project]));
            return projectUIDs.map((projectUID) => projectsByUID.get(projectUID)).filter((project): project is Project.TModel => !!project);
        }, [loadedProjects, projectUIDs]);

        const currentProjects = useMemo(() => searchProjects(projects, debouncedSearchQuery), [debouncedSearchQuery, projects]);
        const discoverySections = useMemo(() => buildProjectDiscoverySections(projects), [projects]);

        const changeProjectListView = (view: TProjectListView) => {
            setProjectListView(view);
            localStorage.setItem(storageKey, view);
        };

        const updateStars = () => {
            updateHeaderStarredProjects();
            updateStarredProjects();
        };

        return (
            <>
                <Flex items="center" gap="2" px="2" mt="3">
                    <Input
                        wrapperProps={{ className: "min-w-0 flex-1" }}
                        value={searchQuery}
                        onChange={(event) => setSearchQuery(event.currentTarget.value)}
                        placeholder={t("dashboard.Search projects...")}
                        aria-label={t("dashboard.Search projects")}
                        leftIcon={<Search />}
                        clearable
                    />
                    <Button
                        type="button"
                        size="icon"
                        variant="outline"
                        className="shrink-0 md:hidden"
                        title={t("dashboard.Quick switcher")}
                        aria-label={t("dashboard.Quick switcher")}
                        onClick={() => window.dispatchEvent(new Event(PROJECT_QUICK_SWITCHER_EVENT))}
                    >
                        <IconComponent icon="search" size="4" />
                    </Button>
                </Flex>
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
                <Box>
                    <ProjectCompactList title={t("dashboard.Favorites")} projects={discoverySections.favorites} updateStarredProjects={updateStars} />
                    {(isProjectsLoading || isProjectsFetching) && currentProjects.length === 0 ? (
                        <SkeletonProjectList />
                    ) : currentProjects.length === 0 ? (
                        <h2 className="py-3 text-center text-lg text-accent-foreground">{t("dashboard.No projects found")}</h2>
                    ) : (
                        <>
                            <ProjectCompactList
                                title={t("dashboard.Recent work")}
                                projects={debouncedSearchQuery ? [] : discoverySections.recent}
                                updateStarredProjects={updateStars}
                            />
                            {projectListView === "cards" ? (
                                <ProjectList projects={currentProjects} updateStarredProjects={updateStars} scrollAreaUpdater={scrollAreaUpdater} />
                            ) : (
                                <ProjectCompactList
                                    key={debouncedSearchQuery}
                                    title={t(debouncedSearchQuery ? "dashboard.Search results" : "dashboard.All projects")}
                                    projects={currentProjects}
                                    updateStarredProjects={updateStars}
                                />
                            )}
                        </>
                    )}
                </Box>
            </>
        );
    }
);

export default ProjectTabs;
