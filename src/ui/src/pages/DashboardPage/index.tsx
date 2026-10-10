import { memo, useMemo, useReducer } from "react";
import { IHeaderNavItem } from "@/components/Header/types";
import { DashboardStyledLayout } from "@/components/Layout";
import { ISidebarNavItem } from "@/components/Sidebar/types";
import useGetAllStarredProjects from "@/controllers/api/dashboard/useGetAllStarredProjects";
import { ROUTES } from "@/core/routing/constants";
import ProjectPage from "@/pages/DashboardPage/ProjectPage";
import CardsPage, { SkeletonCardsPage } from "@/pages/DashboardPage/CardsPage";
import TrackingPage, { SkeletonTrackingPage } from "@/pages/DashboardPage/TrackingPage";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { Navigate } from "react-router";
import { DashboardProvider } from "@/core/providers/DashboardProvider";
import { useAuth } from "@/core/providers/AuthProvider";
import { Project } from "@/core/models";
import { useTranslation } from "react-i18next";
import { SkeletonProjecTabs } from "@/pages/DashboardPage/components/ProjectTabs";
import { PROJECT_QUICK_SWITCHER_EVENT } from "@/pages/DashboardPage/components/ProjectDiscovery";

const DashboardProxy = memo((): React.JSX.Element => {
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const [pageType, tabName] = location.pathname.split("/").slice(2);
    const { data, isFetching } = useGetAllStarredProjects();
    const scrollAreaUpdater = useReducer((x) => x + 1, 0);
    const [updatedStarredProjects, updateStarredProjects] = useReducer((x) => x + 1, 0);
    const [scrollAreaMutable] = scrollAreaUpdater;
    const { currentUser } = useAuth();
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
        case "projects":
            switch (tabName) {
                case "all":
                case "starred":
                case "recent":
                case "unstarred":
                    pageContent = (
                        <ProjectPage updateStarredProjects={updateStarredProjects} currentTab={tabName} scrollAreaUpdater={scrollAreaUpdater} />
                    );
                    skeletonContent = <SkeletonProjecTabs />;
                    break;
                default:
                    return <Navigate to={ROUTES.DASHBOARD.PROJECTS.ALL} />;
            }
            break;
        default:
            return <Navigate to={ROUTES.DASHBOARD.PROJECTS.ALL} />;
    }

    return (
        <DashboardStyledLayout headerNavs={headerNavs} sidebarNavs={sidebarNavs} scrollAreaMutable={scrollAreaMutable} className="overflow-x-hidden">
            {currentUser ? <DashboardProvider currentUser={currentUser}>{pageContent}</DashboardProvider> : skeletonContent}
        </DashboardStyledLayout>
    );
});

export default DashboardProxy;
