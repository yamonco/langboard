import { memo, useCallback, useMemo, useReducer, useState } from "react";
import { IHeaderNavItem } from "@/components/Header/types";
import { DashboardStyledLayout } from "@/components/Layout";
import { ISidebarNavItem } from "@/components/Sidebar/types";
import useGetAllStarredProjects from "@/controllers/api/dashboard/useGetAllStarredProjects";
import { ROUTES } from "@/core/routing/constants";
import ProjectPage from "@/pages/DashboardPage/ProjectPage";
import CardsPage, { SkeletonCardsPage } from "@/pages/DashboardPage/CardsPage";
import TrackingPage, { SkeletonTrackingPage } from "@/pages/DashboardPage/TrackingPage";
import MyWorkPage from "@/pages/DashboardPage/MyWorkPage";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { Navigate } from "react-router";
import { DashboardProvider } from "@/core/providers/DashboardProvider";
import { useAuth } from "@/core/providers/AuthProvider";
import { Project } from "@/core/models";
import { useTranslation } from "react-i18next";
import { SkeletonProjectDiscoveryPage } from "@/pages/DashboardPage/components/ProjectDiscoveryPage";
import { PROJECT_QUICK_SWITCHER_EVENT } from "@/pages/DashboardPage/components/ProjectDiscovery";
import ProjectExplorerSidebar from "@/pages/DashboardPage/components/ProjectExplorerSidebar";
import { WORKBENCH_OPEN_MY_WORK_EVENT, WORKBENCH_TOGGLE_CONTEXT_EVENT } from "@/pages/DashboardPage/components/WorkbenchCommands";
import { useEffect } from "react";
import { useWorkbenchContextOpen } from "@/core/stores/UserSettingsStore";
import useResizeEvent from "@/core/hooks/useResizeEvent";
import { ScreenMap } from "@/core/utils/VariantUtils";

const DashboardProxy = memo((): React.JSX.Element => {
    const [t] = useTranslation();
    const { currentUser } = useAuth();
    const [isExplorerOpen, setIsExplorerOpen] = useWorkbenchContextOpen(currentUser?.uid);
    const [isMobile, setIsMobile] = useState(window.innerWidth < ScreenMap.size.md);
    const [isMobileExplorerOpen, setIsMobileExplorerOpen] = useState(false);
    const [contextMode, setContextMode] = useState<"explorer" | "my-work">("explorer");
    const showContext = useCallback(
        (mode: "explorer" | "my-work") => {
            setContextMode(mode);
            if (isMobile) setIsMobileExplorerOpen(true);
            else setIsExplorerOpen(true);
        },
        [isMobile, setIsExplorerOpen]
    );
    useResizeEvent({ doneCallback: () => setIsMobile(window.innerWidth < ScreenMap.size.md) }, []);
    const toggleExplorer = useCallback(() => {
        if (isMobile) setIsMobileExplorerOpen((open) => !open);
        else setIsExplorerOpen((open) => !open);
    }, [isMobile, setIsExplorerOpen]);
    useEffect(() => {
        const toggle = toggleExplorer;
        const openMyWork = () => showContext("my-work");
        window.addEventListener(WORKBENCH_TOGGLE_CONTEXT_EVENT, toggle);
        window.addEventListener(WORKBENCH_OPEN_MY_WORK_EVENT, openMyWork);
        return () => {
            window.removeEventListener(WORKBENCH_TOGGLE_CONTEXT_EVENT, toggle);
            window.removeEventListener(WORKBENCH_OPEN_MY_WORK_EVENT, openMyWork);
        };
    }, [toggleExplorer, showContext]);
    const navigate = usePageNavigateRef();
    const [pageType, tabName] = location.pathname.split("/").slice(2);
    const { data, isFetching } = useGetAllStarredProjects();
    const scrollAreaUpdater = useReducer((x) => x + 1, 0);
    const [updatedStarredProjects, updateStarredProjects] = useReducer((x) => x + 1, 0);
    const [scrollAreaMutable] = scrollAreaUpdater;
    const starredProjects = Project.Model.useModels((model) => model.starred, [data, isFetching, updatedStarredProjects]);

    const headerNavs = useMemo<IHeaderNavItem[]>(() => {
        const navs: Record<string, IHeaderNavItem> = {
            projects: {
                name: t("dashboard.Projects"),
                onClick: () => {
                    navigate(ROUTES.DASHBOARD.PROJECTS.ALL, { smooth: true });
                },
            },
            cards: {
                name: t("dashboard.Cards"),
                onClick: () => {
                    navigate(ROUTES.DASHBOARD.CARDS, { smooth: true });
                },
            },
            starred: {
                name: t("dashboard.Starred"),
                subNavs: starredProjects.map((project) => ({
                    name: project.title,
                    onClick: () => {
                        navigate(ROUTES.BOARD.MAIN(project.uid));
                    },
                })),
            },
            tracking: {
                name: t("dashboard.Tracking"),
                onClick: () => {
                    navigate(ROUTES.DASHBOARD.TRACKING, { smooth: true });
                },
            },
        };

        switch (pageType) {
            case "cards":
                navs.cards.active = true;
                break;
            case "tracking":
                navs.tracking.active = true;
                break;
            case "projects":
                navs.projects.active = true;
                break;
        }

        return Object.values(navs);
    }, [pageType, starredProjects]);

    const sidebarNavs: ISidebarNavItem[] = [
        {
            icon: "plus",
            name: t("dashboard.Create New Project"),
            onClick: () => {
                navigate(`${location.pathname}/new-project`);
            },
        },
        {
            icon: "history",
            name: t("dashboard.My Activity"),
            onClick: () => {
                navigate(`${location.pathname}/my-activity`);
            },
        },
        {
            icon: "search",
            name: t("dashboard.Quick switcher"),
            onClick: () => window.dispatchEvent(new Event(PROJECT_QUICK_SWITCHER_EVENT)),
        },
    ];

    let pageContent;
    let skeletonContent;
    switch (pageType) {
        case "cards":
            pageContent = <CardsPage />;
            skeletonContent = <SkeletonCardsPage />;
            break;
        case "tracking":
            pageContent = <TrackingPage />;
            skeletonContent = <SkeletonTrackingPage />;
            break;
        case "my-work":
            pageContent = <MyWorkPage />;
            skeletonContent = <SkeletonCardsPage />;
            break;
        case "projects":
            switch (tabName) {
                case "all":
                case "starred":
                case "recent":
                case "unstarred":
                    pageContent = <ProjectPage updateStarredProjects={updateStarredProjects} scrollAreaUpdater={scrollAreaUpdater} />;
                    skeletonContent = <SkeletonProjectDiscoveryPage />;
                    break;
                default:
                    return <Navigate to={ROUTES.DASHBOARD.PROJECTS.ALL} />;
            }
            break;
        default:
            return <Navigate to={ROUTES.DASHBOARD.PROJECTS.ALL} />;
    }

    return (
        <DashboardStyledLayout
            headerNavs={headerNavs}
            headerTitle={
                pageType === "cards"
                    ? t("dashboard.Cards")
                    : pageType === "tracking"
                      ? t("dashboard.Tracking")
                      : pageType === "my-work"
                        ? t("dashboard.My Work")
                        : t("dashboard.Projects")
            }
            activityRailItems={[
                {
                    icon: "panel-left",
                    label: t("common.Explorer"),
                    onClick: () => showContext("explorer"),
                    active: contextMode === "explorer" && (isMobile ? isMobileExplorerOpen : isExplorerOpen),
                },
                { icon: "folder-kanban", label: t("dashboard.Projects"), onClick: headerNavs[0].onClick!, active: pageType === "projects" },
                { icon: "layout-dashboard", label: t("dashboard.Cards"), onClick: headerNavs[1].onClick!, active: pageType === "cards" },
                {
                    icon: "list-checks",
                    label: t("dashboard.My Work"),
                    onClick: () => showContext("my-work"),
                    active: contextMode === "my-work" && (isMobile ? isMobileExplorerOpen : isExplorerOpen),
                },
                { icon: "star", label: t("dashboard.Starred"), onClick: () => window.dispatchEvent(new Event(PROJECT_QUICK_SWITCHER_EVENT)) },
                { icon: "clock", label: t("dashboard.Tracking"), onClick: headerNavs[3].onClick!, active: pageType === "tracking" },
                ...sidebarNavs.map((item) => ({ icon: item.icon, label: item.name, onClick: item.onClick! })),
            ]}
            workbenchContext={
                contextMode === "my-work" ? (
                    <div className="h-full overflow-y-auto">
                        <MyWorkPage compact onNavigate={() => isMobile && setIsMobileExplorerOpen(false)} />
                    </div>
                ) : (
                    <ProjectExplorerSidebar onNavigate={() => isMobile && setIsMobileExplorerOpen(false)} />
                )
            }
            workbenchContextHidden={isMobile || !isExplorerOpen}
            mobileWorkbenchContext={
                isMobile && isMobileExplorerOpen
                    ? {
                          title: contextMode === "my-work" ? t("dashboard.My Work") : t("common.Explorer"),
                          icon: contextMode === "my-work" ? "list-checks" : "panel-left",
                          onClose: () => setIsMobileExplorerOpen(false),
                      }
                    : undefined
            }
            scrollAreaMutable={scrollAreaMutable}
            className="overflow-x-hidden"
        >
            {currentUser ? <DashboardProvider currentUser={currentUser}>{pageContent}</DashboardProvider> : skeletonContent}
        </DashboardStyledLayout>
    );
});

export default DashboardProxy;
