import { lazy, memo, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { keepPreviousData } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation } from "react-router";
import { DashboardStyledLayout } from "@/components/Layout";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Skeleton from "@/components/base/Skeleton";
import Flex from "@/components/base/Flex";
import BoardFloatingNavigation from "@/pages/BoardPage/components/board/BoardFloatingNavigation";
import IconComponent from "@/components/base/IconComponent";
import Toast from "@/components/base/Toast";
import { ROUTES } from "@/core/routing/constants";
import ChatSidebar from "@/pages/BoardPage/components/chat/ChatSidebar";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import useIsBoardChatAvailableHandlers from "@/controllers/socket/board/chat/useIsBoardChatAvailableHandlers";
import { useSocket } from "@/core/providers/SocketProvider";
import { useAuth } from "@/core/providers/AuthProvider";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import BoardPage from "@/pages/BoardPage/BoardPage";
import BoardCardPage from "@/pages/BoardPage/BoardCardPage";
import { IHeaderNavItem } from "@/components/Header/types";
import BoardSettingsPage, { SkeletonBoardSettingsPage } from "@/pages/BoardPage/BoardSettingsPage";
import { TBoardViewType, useBoardController } from "@/core/providers/BoardController";
import useBoardAssignedUsersUpdatedHandlers from "@/controllers/socket/board/useBoardAssignedUsersUpdatedHandlers";
import useProjectDeletedHandlers from "@/controllers/socket/shared/useProjectDeletedHandlers";
import { usePageHeader } from "@/core/providers/PageHeaderProvider";
import { SkeletonBoard } from "@/pages/BoardPage/components/board/Board";
import useBoardAssignedInternalBotChangedHandlers from "@/controllers/socket/board/useBoardAssignedInternalBotChangedHandlers";
import useInternalBotUpdatedHandlers from "@/controllers/socket/global/useInternalBotUpdatedHandlers";
import useSwitchSocketHandlers from "@/core/hooks/useSwitchSocketHandlers";
import { InternalBotModel, Project, ProjectCard } from "@/core/models";
import { EHttpStatus, ESocketTopic } from "@langboard/core/enums";
import useBoardBotStatusMapHandlers from "@/controllers/socket/board/useBoardBotStatusMapHandlers";
import { BoardBotScopeList } from "@/pages/BoardPage/components/board/BoardBotScope";
import useGetProject from "@/controllers/api/board/useGetProject";
import useGetCards from "@/controllers/api/board/useGetCards";
import useGetGraphApprovalCount from "@/controllers/api/board/graphApprovals/useGetGraphApprovalCount";
import ActivityList from "@/components/ActivityList";

import { cn } from "@/core/utils/ComponentUtils";
import useCardRelationshipsUpdatedHandlers from "@/controllers/socket/card/useCardRelationshipsUpdatedHandlers";
import useRoleActionFilter from "@/core/hooks/useRoleActionFilter";
import { ProjectRole } from "@/core/models/roles";
import { ScreenMap } from "@/core/utils/VariantUtils";
import useResizeEvent from "@/core/hooks/useResizeEvent";
import useBoardBotScopeCreatedHandlers from "@/controllers/socket/board/botScopes/useBoardBotScopeCreatedHandlers";
import useBoardBotScopeDeletedHandlers from "@/controllers/socket/board/botScopes/useBoardBotScopeDeletedHandlers";
import useBoardBotScopeFreezeUpdatedHandlers from "@/controllers/socket/board/botScopes/useBoardBotScopeFreezeUpdatedHandlers";
import useBoardBotScopeTriggerConditionsUpdatedHandlers from "@/controllers/socket/board/botScopes/useBoardBotScopeTriggerConditionsUpdatedHandlers";
import useBoardBotCronRescheduledHandlers from "@/controllers/socket/board/botSchedules/useBoardBotCronRescheduledHandlers";
import useBoardBotCronScheduledHandlers from "@/controllers/socket/board/botSchedules/useBoardBotCronScheduledHandlers";
import useBoardBotCronUnscheduledHandlers from "@/controllers/socket/board/botSchedules/useBoardBotCronUnscheduledHandlers";
import useBoardGraphApprovalDeletedHandlers from "@/controllers/socket/board/graphApprovals/useBoardGraphApprovalDeletedHandlers";
import useBoardGraphApprovalRequestedHandlers from "@/controllers/socket/board/graphApprovals/useBoardGraphApprovalRequestedHandlers";
import useBoardGraphApprovalUpdatedHandlers from "@/controllers/socket/board/graphApprovals/useBoardGraphApprovalUpdatedHandlers";
import { getBoardChatStore } from "@/core/stores/BoardChatStore";
import { useWorkbenchContextOpen } from "@/core/stores/UserSettingsStore";
import ProjectExplorerSidebar from "@/pages/DashboardPage/components/ProjectExplorerSidebar";
import { WORKBENCH_OPEN_CHANGES_EVENT, WORKBENCH_TOGGLE_CONTEXT_EVENT } from "@/pages/DashboardPage/components/WorkbenchCommands";
import { closeProject } from "@/pages/DashboardPage/components/OpenCardsStore";

const BoardGraphPage = lazy(() => import("@/pages/BoardPage/BoardGraphPage"));
const BoardWikiPage = lazy(() => import("@/pages/BoardPage/BoardWikiPage"));
const BoardChangesSidebar = lazy(() => import("@/pages/BoardPage/components/board/BoardChangesSidebar"));
const MyWorkSidebar = lazy(() => import("@/pages/DashboardPage/MyWorkPage"));
const BoardRelationsSidebar = lazy(() => import("@/pages/BoardPage/components/board/BoardRelationsSidebar"));
const BoardOutlineSidebar = lazy(() => import("@/pages/BoardPage/components/board/BoardOutlineSidebar"));
const BoardWikiSidebar = lazy(() => import("@/pages/BoardPage/components/board/BoardWikiSidebar"));
const SkeletonBoardWikiPage = () => <Skeleton className="m-4 h-48 w-[min(36rem,calc(100%-2rem))]" />;

const getCurrentPage = (pageRoute?: string): TBoardViewType => {
    switch (pageRoute) {
        case "card":
            return "card";
        case "wiki":
            return "wiki";
        case "graph":
            return "graph";
        case "settings":
            return "settings";
        default:
            return "board";
    }
};

type TBoardSidePanel = "botScope" | "switchProject";
type TWorkbenchContext = "explorer" | "my-work" | "changes" | "activity" | "relations" | "outline" | "wiki";

const BoardProxy = memo((): React.JSX.Element => {
    const { setPageAliasRef } = usePageHeader();
    const { currentUser } = useAuth();
    const socket = useSocket();
    const navigate = usePageNavigateRef();
    const location = useLocation();
    const [projectUID, pageRoute] = location.pathname.split("/").slice(2);
    if (!projectUID) {
        return <Navigate to={ROUTES.ERROR(EHttpStatus.HTTP_404_NOT_FOUND)} replace />;
    }

    const { data, isFetching, error, refetch } = useGetProject({ uid: projectUID }, { placeholderData: keepPreviousData });
    const { send: sendBoardBotStatusMap } = useBoardBotStatusMapHandlers({ projectUID });

    useEffect(() => {
        if (!error) {
            return;
        }

        const { handle } = setupApiErrorHandler({
            [EHttpStatus.HTTP_403_FORBIDDEN]: {
                after: () => {
                    if (currentUser) closeProject(currentUser.uid, projectUID);
                    navigate(ROUTES.ERROR(EHttpStatus.HTTP_403_FORBIDDEN), { replace: true });
                },
            },
            [EHttpStatus.HTTP_404_NOT_FOUND]: {
                after: () => {
                    if (currentUser) closeProject(currentUser.uid, projectUID);
                    navigate(ROUTES.ERROR(EHttpStatus.HTTP_404_NOT_FOUND), { replace: true });
                },
            },
            network: {
                after: () => {
                    setTimeout(() => {
                        refetch();
                    }, 5000);
                },
            },
        });

        handle(error);
    }, [error]);

    useEffect(() => {
        if (!data || isFetching) {
            setPageAliasRef.current();
            return;
        }

        if (pageRoute !== "card") {
            setPageAliasRef.current(data.project.title);
        }

        socket.subscribe(ESocketTopic.Board, [projectUID], () => {
            sendBoardBotStatusMap({});
        });
        socket.subscribe(ESocketTopic.BoardSettings, [projectUID]);

        return () => {
            socket.unsubscribe(ESocketTopic.Board, [projectUID]);
            socket.unsubscribe(ESocketTopic.BoardSettings, [projectUID]);
        };
    }, [data, isFetching, pageRoute, projectUID]);

    if (!data) {
        return <SkeletonBoard />;
    }

    return (
        <BoardProxyDisplay project={data.project} pageRoute={pageRoute} isFetching={isFetching} isProjectLoading={data.project.uid !== projectUID} />
    );
});

interface IBoardProxyDisplayProps {
    project: Project.TModel;
    pageRoute: string;
    isFetching: bool;
    isProjectLoading: bool;
}

function BoardHeaderCardTitle({ card }: { card: ProjectCard.TModel }) {
    const title = card.useField("title");
    return <span className="min-w-0 truncate">{title}</span>;
}

function BoardProxyDisplay({ pageRoute, isFetching, isProjectLoading, project }: IBoardProxyDisplayProps): React.JSX.Element {
    const [t] = useTranslation();
    const { setPageAliasRef } = usePageHeader();
    const socket = useSocket();
    const { currentUser } = useAuth();
    const navigate = usePageNavigateRef();
    const [isCardExpanded, setIsCardExpanded] = useState(false);
    const [activeSidePanel, setActiveSidePanel] = useState<TBoardSidePanel>();
    const [workbenchContextMode, setWorkbenchContextMode] = useState<TWorkbenchContext>("explorer");
    const workbenchContextTitle = {
        explorer: "Explorer",
        "my-work": t("dashboard.My Work"),
        changes: t("dashboard.Changes"),
        activity: t("board.Activity"),
        relations: t("dashboard.Relations"),
        outline: t("dashboard.Outline"),
        wiki: t("board.Wiki"),
    }[workbenchContextMode];
    const [isContextOpen, setIsContextOpen] = useWorkbenchContextOpen(currentUser?.uid);
    const [isMobile, setIsMobile] = useState(window.innerWidth < ScreenMap.size.md);
    const isBotScopeOpened = activeSidePanel === "botScope";
    const isWorkbenchContextVisible = !isBotScopeOpened && (isMobile ? activeSidePanel === "switchProject" : isContextOpen);
    const isSwitchProjectOpened = isMobile ? activeSidePanel === "switchProject" : isContextOpen && !isBotScopeOpened;
    const toggleBotScope = useCallback(() => {
        setActiveSidePanel((value) => (value === "botScope" ? undefined : "botScope"));
        if (!isMobile) setIsContextOpen(true);
    }, [isMobile, setIsContextOpen]);
    const toggleSwitchProject = useCallback(() => {
        if (isMobile) {
            setActiveSidePanel((value) => (value === "switchProject" ? undefined : "switchProject"));
        } else if (isBotScopeOpened) {
            setActiveSidePanel(undefined);
            setIsContextOpen(true);
        } else {
            setIsContextOpen((open) => !open);
        }
    }, [isMobile, isBotScopeOpened, setIsContextOpen]);
    const showWorkbenchContext = useCallback(
        (mode: TWorkbenchContext) => {
            setWorkbenchContextMode(mode);
            if (!isMobile) setIsContextOpen(true);
            setActiveSidePanel(isMobile ? "switchProject" : undefined);
        },
        [isMobile, setIsContextOpen]
    );
    useEffect(() => {
        const toggleContext = () => toggleSwitchProject();
        const openChanges = () => showWorkbenchContext("changes");
        window.addEventListener(WORKBENCH_TOGGLE_CONTEXT_EVENT, toggleContext);
        window.addEventListener(WORKBENCH_OPEN_CHANGES_EVENT, openChanges);
        return () => {
            window.removeEventListener(WORKBENCH_TOGGLE_CONTEXT_EVENT, toggleContext);
            window.removeEventListener(WORKBENCH_OPEN_CHANGES_EVENT, openChanges);
        };
    }, [toggleSwitchProject, showWorkbenchContext]);
    const {
        boardViewType,
        selectCardViewType,
        chatResizableSidebar,
        chatSidebarRef,
        boardChat,
        setBoardViewType,
        setChatResizableSidebar,
        setBoardChat,
    } = useBoardController();
    const isCardPage = !!pageRoute && !["graph", "wiki", "settings"].includes(pageRoute);
    const projectTitle = project.useField("title");
    const { data: boardCardsData } = useGetCards({ project_uid: project.uid }, { enabled: isCardPage && !isProjectLoading });
    const activeCard = boardCardsData && isCardPage ? ProjectCard.Model.getModel(pageRoute) : undefined;
    const { data: approvalCountData, refetch: refetchApprovalCount } = useGetGraphApprovalCount(project.uid, {
        interceptToast: false,
        enabled: !isProjectLoading,
    });
    const refreshApprovalCount = useCallback(() => void refetchApprovalCount(), [refetchApprovalCount]);
    const graphApprovalRequestedHandlers = useBoardGraphApprovalRequestedHandlers({ projectUID: project.uid, callback: refreshApprovalCount });
    const graphApprovalUpdatedHandlers = useBoardGraphApprovalUpdatedHandlers({ projectUID: project.uid, callback: refreshApprovalCount });
    const graphApprovalDeletedHandlers = useBoardGraphApprovalDeletedHandlers({ projectUID: project.uid, callback: refreshApprovalCount });
    const pendingGraphApprovalCount = approvalCountData?.count ?? 0;
    const pendingGraphApprovalBadge = pendingGraphApprovalCount > 99 ? "99+" : pendingGraphApprovalCount || undefined;
    const isBoardChatAvailableHandlers = useMemo(
        () =>
            useIsBoardChatAvailableHandlers({
                projectUID: project.uid,
                callback: (result) => {
                    if (result.available) {
                        setBoardChat({
                            bot: result.bot,
                            projectUID: project.uid,
                        });
                        setChatResizableSidebar(() => ({
                            children: (
                                <Suspense>
                                    <ChatSidebar ref={chatSidebarRef} />
                                </Suspense>
                            ),
                            initialWidth: 280,
                            collapsableWidth: 210,
                            floatingIcon: "message-circle",
                            floatingTitle: t("project.Chat with AI"),
                            floatingFullScreen: true,
                            widthCssVariable: "--board-chat-sidebar-width",
                            hidden: window.innerWidth < ScreenMap.size.md || getBoardChatStore().isChatHidden(project.uid),
                        }));
                    } else {
                        setBoardChat(undefined);
                        setChatResizableSidebar(() => ({
                            children: <></>,
                            initialWidth: 280,
                            collapsableWidth: 210,
                            hidden: true,
                        }));
                    }
                },
            }),
        [project, setBoardChat, setChatResizableSidebar]
    );
    const boardAssignedUsersUpdatedHandlers = useMemo(
        () =>
            useBoardAssignedUsersUpdatedHandlers({
                projectUID: project.uid,
                callback: (result) => {
                    if (!currentUser || (!result.assigned_user_uids.includes(currentUser.uid) && !currentUser.is_admin)) {
                        Toast.Add.error(t("errors.Forbidden"));
                    }
                },
            }),
        [project, currentUser]
    );
    const projectDeletedHandlers = useMemo(
        () =>
            useProjectDeletedHandlers({
                topic: ESocketTopic.Board,
                projectUID: project.uid,
                callback: () => {
                    if (currentUser) closeProject(currentUser.uid, project.uid);
                    Toast.Add.error(t("project.errors.Project closed."));
                    navigate(ROUTES.DASHBOARD.PROJECTS.ALL, { replace: true });
                },
            }),
        [project]
    );
    const boardAssignedInternalBotChangedHandlers = useMemo(
        () =>
            useBoardAssignedInternalBotChangedHandlers({
                projectUID: project.uid,
                callback: (data) => {
                    const internalBot = InternalBotModel.Model.getModel(data.internal_bot_uid);
                    if (internalBot) {
                        const existingBots = [...project.internal_bots];
                        const targetBotIndex = existingBots.findIndex((bot) => bot.bot_type === internalBot.bot_type);
                        if (targetBotIndex !== -1 && existingBots[targetBotIndex].uid !== internalBot.uid) {
                            existingBots.splice(targetBotIndex, 1);
                        }
                        existingBots.push(internalBot);
                        project.internal_bots = existingBots;
                    }

                    if (internalBot && internalBot.bot_type !== InternalBotModel.EInternalBotType.ProjectChat) {
                        return;
                    }

                    isBoardChatAvailableHandlers.send({});
                },
            }),
        [project, isBoardChatAvailableHandlers]
    );
    const internalBotUpdatedHandlers = useMemo(
        () =>
            useInternalBotUpdatedHandlers({
                callback: (data) => {
                    const internalBot = InternalBotModel.Model.getModel(data.uid);
                    if (internalBot && internalBot.bot_type !== InternalBotModel.EInternalBotType.ProjectChat) {
                        return;
                    }

                    isBoardChatAvailableHandlers.send({});
                },
            }),
        [isBoardChatAvailableHandlers]
    );
    const cardRelationshipsUpdatedHandlers = useMemo(
        () =>
            useCardRelationshipsUpdatedHandlers({
                projectUID: project.uid,
            }),
        [project]
    );
    const boardBotScopeCreatedHandlers = useMemo(
        () =>
            useBoardBotScopeCreatedHandlers({
                projectUID: project.uid,
            }),
        [project]
    );
    const boardBotScopeTriggerConditionsUpdatedHandlers = useMemo(
        () =>
            useBoardBotScopeTriggerConditionsUpdatedHandlers({
                projectUID: project.uid,
            }),
        [project]
    );
    const boardBotScopeFreezeUpdatedHandlers = useMemo(
        () =>
            useBoardBotScopeFreezeUpdatedHandlers({
                projectUID: project.uid,
            }),
        [project]
    );
    const boardBotScopeDeletedHandlers = useMemo(
        () =>
            useBoardBotScopeDeletedHandlers({
                projectUID: project.uid,
            }),
        [project]
    );
    const boardBotCronScheduledHandlers = useMemo(
        () =>
            useBoardBotCronScheduledHandlers({
                projectUID: project.uid,
            }),
        [project]
    );
    const boardBotCronRescheduledHandlers = useMemo(
        () =>
            useBoardBotCronRescheduledHandlers({
                projectUID: project.uid,
            }),
        [project]
    );
    const boardBotCronUnscheduledHandlers = useMemo(
        () =>
            useBoardBotCronUnscheduledHandlers({
                projectUID: project.uid,
            }),
        [project]
    );
    const handlers = useMemo(
        () => [
            isBoardChatAvailableHandlers,
            boardAssignedUsersUpdatedHandlers,
            projectDeletedHandlers,
            boardAssignedInternalBotChangedHandlers,
            internalBotUpdatedHandlers,
            cardRelationshipsUpdatedHandlers,
            boardBotScopeCreatedHandlers,
            boardBotScopeTriggerConditionsUpdatedHandlers,
            boardBotScopeFreezeUpdatedHandlers,
            boardBotScopeDeletedHandlers,
            boardBotCronScheduledHandlers,
            boardBotCronRescheduledHandlers,
            boardBotCronUnscheduledHandlers,
            graphApprovalRequestedHandlers,
            graphApprovalUpdatedHandlers,
            graphApprovalDeletedHandlers,
        ],
        [
            isBoardChatAvailableHandlers,
            boardAssignedUsersUpdatedHandlers,
            projectDeletedHandlers,
            boardAssignedInternalBotChangedHandlers,
            internalBotUpdatedHandlers,
            cardRelationshipsUpdatedHandlers,
            boardBotScopeCreatedHandlers,
            boardBotScopeTriggerConditionsUpdatedHandlers,
            boardBotScopeFreezeUpdatedHandlers,
            boardBotScopeDeletedHandlers,
            boardBotCronScheduledHandlers,
            boardBotCronRescheduledHandlers,
            boardBotCronUnscheduledHandlers,
            graphApprovalRequestedHandlers,
            graphApprovalUpdatedHandlers,
            graphApprovalDeletedHandlers,
        ]
    );

    const { subscribedTopics } = useSwitchSocketHandlers({ socket, handlers });

    useResizeEvent(
        {
            doneCallback: () => {
                setIsMobile(window.innerWidth < ScreenMap.size.md);
            },
        },
        [setIsMobile]
    );

    useEffect(() => {
        if (isFetching || !subscribedTopics.includes(ESocketTopic.Board)) {
            return;
        }

        isBoardChatAvailableHandlers.send({});
    }, [isFetching, subscribedTopics]);

    useEffect(() => {
        setPageAliasRef.current(projectTitle);
    }, [projectTitle]);

    useEffect(() => {
        setBoardViewType(getCurrentPage(pageRoute));
    }, [pageRoute]);

    useEffect(() => {
        setIsCardExpanded(false);
    }, [pageRoute]);

    useEffect(() => {
        setChatResizableSidebar((prev) => {
            if (!prev) {
                return prev;
            }

            return {
                ...prev,
                hidden: isMobile ? true : getBoardChatStore().isChatHidden(project.uid),
            };
        });
    }, [isMobile, project, setChatResizableSidebar]);

    const headerNavs: IHeaderNavItem[] = [
        {
            name: t("board.Board"),
            onClick: () => {
                setBoardViewType("board");
                navigate(ROUTES.BOARD.MAIN(project.uid), { smooth: true });
            },
            active: boardViewType === "board" || boardViewType === "card",
            hidden: !!selectCardViewType,
        },
        {
            name: t("board.Wiki"),
            onClick: () => {
                setBoardViewType("wiki");
                navigate(ROUTES.BOARD.WIKI(project.uid), { smooth: true });
            },
            active: boardViewType === "wiki",
            hidden: !!selectCardViewType,
        },
        {
            name: t("board.Relationship graph"),
            onClick: () => {
                setBoardViewType("graph");
                navigate(ROUTES.BOARD.GRAPH(project.uid), { smooth: true });
            },
            active: boardViewType === "graph",
            hidden: !!selectCardViewType,
        },
        {
            name: t("board.Activity"),
            onClick: () => showWorkbenchContext("activity"),
            active: workbenchContextMode === "activity" && isWorkbenchContextVisible,
            hidden: !!selectCardViewType,
        },
        {
            name: t("board.Settings"),
            onClick: () => {
                setBoardViewType("settings");
                navigate(ROUTES.BOARD.SETTINGS(project.uid), { smooth: true });
            },
            active: boardViewType === "settings",
            hidden: !!selectCardViewType,
        },
        {
            name: t("bot.Scope bot"),
            onClick: toggleBotScope,
            active: isBotScopeOpened,
            hidden: !!selectCardViewType && !!currentUser && currentUser.is_admin,
        },
    ];
    const floatingNavs: IBoardFloatingNavItem[] = [
        ...(boardChat && chatResizableSidebar
            ? [
                  {
                      name: t("project.Chat with AI"),
                      icon: "message-circle",
                      active: !chatResizableSidebar.hidden,
                      hidden: !!selectCardViewType,
                      onClick: () => {
                          setChatResizableSidebar((prev) => {
                              if (!prev) {
                                  return prev;
                              }

                              const hidden = !prev.hidden;
                              if (!isMobile) {
                                  getBoardChatStore().setChatVisible(project.uid, !hidden);
                              }

                              return { ...prev, hidden };
                          });
                      },
                  } satisfies IBoardFloatingNavItem,
              ]
            : []),
        {
            name: t("board.Board"),
            icon: "columns-3",
            active: boardViewType === "board" || boardViewType === "card",
            hidden: !!selectCardViewType,
            onClick: () => {
                setActiveSidePanel(undefined);
                setBoardViewType("board");
                navigate(ROUTES.BOARD.MAIN(project.uid), { smooth: true });
            },
        },
        {
            name: t("settings.Bots"),
            icon: "bot",
            badge: pendingGraphApprovalBadge,
            onClick: toggleBotScope,
            active: isBotScopeOpened,
            hidden: !!selectCardViewType && !!currentUser && currentUser.is_admin,
        },
        {
            name: t("project.Switch Project"),
            icon: "shuffle",
            active: isSwitchProjectOpened,
            hidden: !!selectCardViewType,
            onClick: toggleSwitchProject,
        },
    ];

    let PageComponent;
    let SkeletonComponent;
    // Route-backed pages must win during the render that observes a location
    // change. Waiting for the boardViewType effect leaves the previous Wiki
    // tree mounted for one render, where its auto-selection can overwrite a
    // card deep link and navigate back to the Wiki.
    const renderedViewType = pageRoute ? getCurrentPage(pageRoute) : boardViewType;
    switch (renderedViewType) {
        case "graph":
            PageComponent = BoardGraphPage;
            SkeletonComponent = SkeletonBoard;
            break;
        case "wiki":
            PageComponent = BoardWikiPage;
            SkeletonComponent = SkeletonBoardWikiPage;
            break;
        case "settings":
            PageComponent = BoardSettingsPage;
            SkeletonComponent = SkeletonBoardSettingsPage;
            break;
        default:
            PageComponent = BoardPage;
            SkeletonComponent = SkeletonBoard;
            break;
    }

    return (
        <>
            <DashboardStyledLayout
                inert={isProjectLoading}
                aria-busy={isProjectLoading}
                headerNavs={[
                    ...headerNavs,
                    {
                        name: t("dashboard.Relations panel"),
                        onClick: () => showWorkbenchContext("relations"),
                        active: workbenchContextMode === "relations",
                    },
                    {
                        name: t("dashboard.Outline"),
                        onClick: () => showWorkbenchContext("outline"),
                        active: workbenchContextMode === "outline",
                    },
                    {
                        name: t("dashboard.Wiki panel"),
                        onClick: () => showWorkbenchContext("wiki"),
                        active: workbenchContextMode === "wiki",
                    },
                ]}
                headerTitle={
                    <span className="flex min-w-0 items-center gap-1">
                        <span className="max-w-32 shrink-0 truncate">{projectTitle}</span>
                        {isCardPage && activeCard && (
                            <>
                                <IconComponent icon="chevron-right" size="3" className="shrink-0 text-muted-foreground" />
                                <BoardHeaderCardTitle card={activeCard} />
                            </>
                        )}
                    </span>
                }
                activityRailItems={[
                    {
                        icon: "panel-left",
                        label: "Explorer",
                        onClick: () => showWorkbenchContext("explorer"),
                        active: isWorkbenchContextVisible && workbenchContextMode === "explorer",
                    },
                    {
                        icon: "list-checks",
                        label: t("dashboard.My Work"),
                        onClick: () => showWorkbenchContext("my-work"),
                        active: isWorkbenchContextVisible && workbenchContextMode === "my-work",
                    },
                    {
                        icon: "circle-dot",
                        label: t("dashboard.Changes"),
                        onClick: () => showWorkbenchContext("changes"),
                        active: isWorkbenchContextVisible && workbenchContextMode === "changes",
                    },
                    {
                        icon: "network",
                        label: t("dashboard.Relations"),
                        onClick: () => showWorkbenchContext("relations"),
                        active: isWorkbenchContextVisible && workbenchContextMode === "relations",
                    },
                    {
                        icon: "list-tree",
                        label: t("dashboard.Outline"),
                        onClick: () => showWorkbenchContext("outline"),
                        active: isWorkbenchContextVisible && workbenchContextMode === "outline",
                    },
                    {
                        icon: "notebook-pen",
                        label: t("board.Wiki"),
                        onClick: () => showWorkbenchContext("wiki"),
                        active: isWorkbenchContextVisible && workbenchContextMode === "wiki",
                    },
                    ...headerNavs.map((nav, index) => ({
                        icon: ["columns-3", "notebook-pen", "network", "history", "settings", "bot"][index],
                        label: String(nav.name),
                        onClick: nav.onClick!,
                        active: nav.active,
                        hidden: nav.hidden || index === 1 || index === 2,
                        badge: index === 5 ? pendingGraphApprovalBadge : undefined,
                    })),
                ]}
                workbenchContext={
                    isBotScopeOpened ? (
                        <BoardBotScopeSidebar project={project} />
                    ) : workbenchContextMode === "explorer" ? (
                        <ProjectExplorerSidebar currentProject={project} onNavigate={() => setActiveSidePanel(undefined)} />
                    ) : (
                        <Suspense fallback={<Skeleton className="m-3 h-24" />}>
                            {workbenchContextMode === "my-work" ? (
                                <div className="h-full overflow-y-auto">
                                    <MyWorkSidebar compact projectUID={project.uid} onNavigate={() => isMobile && setActiveSidePanel(undefined)} />
                                </div>
                            ) : workbenchContextMode === "changes" ? (
                                <BoardChangesSidebar projectUID={project.uid} onNavigate={() => isMobile && setActiveSidePanel(undefined)} />
                            ) : workbenchContextMode === "activity" && currentUser ? (
                                <ActivityList
                                    form={{ listType: "ActivityModel", type: "project", project_uid: project.uid }}
                                    currentUser={currentUser}
                                    outerClassName="h-full px-3"
                                />
                            ) : workbenchContextMode === "relations" ? (
                                <BoardRelationsSidebar projectUID={project.uid} cardUID={activeCard?.uid} />
                            ) : workbenchContextMode === "outline" ? (
                                <BoardOutlineSidebar
                                    cardUID={activeCard?.uid}
                                    onRelations={() => showWorkbenchContext("relations")}
                                    onNavigate={() => isMobile && setActiveSidePanel(undefined)}
                                />
                            ) : (
                                <BoardWikiSidebar projectUID={project.uid} onNavigate={() => setActiveSidePanel(undefined)} />
                            )}
                        </Suspense>
                    )
                }
                workbenchContextHidden={!isContextOpen || isMobile || !!selectCardViewType}
                mobileWorkbenchContext={
                    isMobile && !selectCardViewType && activeSidePanel
                        ? {
                              title: isBotScopeOpened ? "Bots" : workbenchContextTitle,
                              icon: isBotScopeOpened
                                  ? "bot"
                                  : {
                                        explorer: "panel-left",
                                        "my-work": "list-checks",
                                        changes: "circle-dot",
                                        activity: "history",
                                        relations: "network",
                                        outline: "list-tree",
                                        wiki: "notebook-pen",
                                    }[workbenchContextMode],
                              onClose: () => setActiveSidePanel(undefined),
                          }
                        : undefined
                }
                resizableSidebar={
                    chatResizableSidebar
                        ? {
                              ...chatResizableSidebar,
                              floatingHidden: true,
                              hidden: isMobile || !!selectCardViewType || !!chatResizableSidebar.hidden,
                          }
                        : undefined
                }
                className="!p-0"
            >
                {!isProjectLoading && currentUser && project ? (
                    <Flex
                        position="relative"
                        w="full"
                        h="full"
                        className={cn(
                            "h-[calc(100dvh-2.75rem)] min-h-[calc(100dvh-2.75rem)]",
                            pageRoute === "settings" ? "overflow-y-auto overflow-x-hidden" : "overflow-hidden"
                        )}
                    >
                        <Box className="relative min-w-0 flex-1">
                            <Box
                                className={cn(
                                    "relative size-full",
                                    isCardPage &&
                                        isCardExpanded &&
                                        !selectCardViewType &&
                                        "pointer-events-none absolute inset-0 -z-[9999] overflow-hidden"
                                )}
                            >
                                <PageComponent project={project} currentUser={currentUser} />
                            </Box>
                            {isCardPage && (
                                <BoardCardPage
                                    key={pageRoute}
                                    projectUID={project.uid}
                                    cardUID={pageRoute}
                                    embedded
                                    isExpanded={isCardExpanded}
                                    setIsExpanded={setIsCardExpanded}
                                />
                            )}
                            {!isCardPage && !selectCardViewType && (isMobile || boardChat || renderedViewType === "board") && (
                                <BoardFloatingNavigation
                                    project={project}
                                    currentUser={currentUser}
                                    dockEnabled={renderedViewType === "board"}
                                    items={(isMobile ? floatingNavs : floatingNavs.filter((nav) => nav.icon === "message-circle")).map(
                                        (nav, index) => ({
                                            key: index,
                                            label: nav.name,
                                            icon: nav.icon,
                                            badge: nav.badge,
                                            active: nav.active,
                                            hidden: nav.hidden,
                                            onClick: nav.onClick,
                                        })
                                    )}
                                />
                            )}
                            <BoardMobileChatOverlay
                                isOpened={isMobile && !selectCardViewType && !!chatResizableSidebar && !chatResizableSidebar.hidden}
                                onClose={() => {
                                    setChatResizableSidebar((prev) => (prev ? { ...prev, hidden: true } : prev));
                                }}
                            >
                                {chatResizableSidebar?.children}
                            </BoardMobileChatOverlay>
                        </Box>
                    </Flex>
                ) : (
                    <SkeletonComponent />
                )}
            </DashboardStyledLayout>
        </>
    );
}

function BoardMobileChatOverlay({
    children,
    isOpened,
    onClose,
}: {
    children: React.ReactNode;
    isOpened: bool;
    onClose: () => void;
}): React.JSX.Element | null {
    if (!isOpened) {
        return null;
    }

    return (
        <Box className="fixed inset-x-0 bottom-[4.75rem] top-11 z-50 overflow-hidden border-t bg-background shadow-2xl md:hidden">
            <Button variant="ghost" size="icon-sm" className="absolute right-2 top-2 z-10" onClick={onClose}>
                <IconComponent icon="x" size="5" />
            </Button>
            {children}
        </Box>
    );
}

function BoardBotScopeSidebar({ project }: { project: Project.TModel }): React.JSX.Element {
    const currentUserRoleActions = project.useField("current_auth_role_actions");
    const { hasRoleAction } = useRoleActionFilter(currentUserRoleActions);

    if (!hasRoleAction(ProjectRole.EAction.Update)) {
        return <></>;
    }

    return (
        <Box className="h-full">
            <BoardBotScopeList target={{ target_table: "project", target: project }} className="h-full pb-3" />
        </Box>
    );
}

interface IBoardFloatingNavItem extends IHeaderNavItem {
    icon: string;
    badge?: React.ReactNode;
}

export default BoardProxy;
