import { memo, useCallback, useEffect, useMemo } from "react";
import { EHttpStatus, ESocketTopic } from "@langboard/core/enums";
import { useDashboard } from "@/core/providers/DashboardProvider";
import ProjectTabs from "@/pages/DashboardPage/components/ProjectTabs";
import { usePageHeader } from "@/core/providers/PageHeaderProvider";
import { TProjectTab } from "@/pages/DashboardPage/constants";
import useGetProjects from "@/controllers/api/dashboard/useGetProjects";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";
import useUserProjectAssignedHandlers from "@/controllers/socket/user/useUserProjectAssignedHandlers";
import useSwitchSocketHandlers from "@/core/hooks/useSwitchSocketHandlers";

interface IProjectPageProps {
    currentTab: TProjectTab;
    updateStarredProjects: React.DispatchWithoutAction;
    scrollAreaUpdater: [number, React.DispatchWithoutAction];
}

const ProjectPage = memo(({ currentTab, updateStarredProjects, scrollAreaUpdater }: IProjectPageProps): React.JSX.Element => {
    const navigate = usePageNavigateRef();
    const { setPageAliasRef } = usePageHeader();
    const { currentUser, socket } = useDashboard();
    const { data, error, isFetching, isLoading, refetch } = useGetProjects();

    const handleLoadError = useCallback(
        (error: unknown) => {
            const { handle } = setupApiErrorHandler({
                [EHttpStatus.HTTP_403_FORBIDDEN]: {
                    after: () => navigate(ROUTES.ERROR(EHttpStatus.HTTP_403_FORBIDDEN), { replace: true }),
                },
                [EHttpStatus.HTTP_404_NOT_FOUND]: {
                    after: () => navigate(ROUTES.ERROR(EHttpStatus.HTTP_404_NOT_FOUND), { replace: true }),
                },
            });

            handle(error);
        },
        [navigate]
    );

    const reloadProjects = useCallback(async () => {
        const result = await refetch();
        if (result.error) {
            handleLoadError(result.error);
            return false;
        }

        return true;
    }, [handleLoadError, refetch]);

    useEffect(() => {
        setPageAliasRef.current("Dashboard");
    }, []);

    useEffect(() => {
        if (error) {
            handleLoadError(error);
        }
    }, [error, handleLoadError]);

    useEffect(() => {
        if (!currentUser?.uid) {
            return;
        }

        socket.subscribe(ESocketTopic.UserPrivate, [currentUser.uid]);
        return () => {
            if (location.pathname.startsWith(ROUTES.DASHBOARD.ROUTE)) {
                return;
            }
            socket.unsubscribe(ESocketTopic.UserPrivate, [currentUser.uid]);
        };
    }, [currentUser, socket]);

    const projectAssignedHandlers = useMemo(
        () =>
            useUserProjectAssignedHandlers({
                currentUser,
                callback: () => {
                    reloadProjects();
                },
            }),
        [currentUser, reloadProjects]
    );
    useSwitchSocketHandlers({ socket, handlers: projectAssignedHandlers, dependencies: [projectAssignedHandlers] });

    return (
        <ProjectTabs
            currentTab={currentTab}
            userUID={currentUser.uid}
            projectsData={data}
            isProjectsFetching={isFetching}
            isProjectsLoading={isLoading}
            updateStarredProjects={updateStarredProjects}
            scrollAreaUpdater={scrollAreaUpdater}
        />
    );
});

export default ProjectPage;
