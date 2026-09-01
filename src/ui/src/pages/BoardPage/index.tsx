import { memo, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation } from "react-router";
import { DashboardStyledLayout } from "@/components/Layout";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import Floating from "@/components/base/Floating";
import IconComponent from "@/components/base/IconComponent";
import ScrollArea from "@/components/base/ScrollArea";
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
import BoardWikiPage, { SkeletonBoardWikiPage } from "@/pages/BoardPage/BoardWikiPage";
import BoardSettingsPage, { SkeletonBoardSettingsPage } from "@/pages/BoardPage/BoardSettingsPage";
import { TBoardViewType, useBoardController } from "@/core/providers/BoardController";
import useBoardAssignedUsersUpdatedHandlers from "@/controllers/socket/board/useBoardAssignedUsersUpdatedHandlers";
import useProjectDeletedHandlers from "@/controllers/socket/shared/useProjectDeletedHandlers";
import { usePageHeader } from "@/core/providers/PageHeaderProvider";
import { SkeletonBoard } from "@/pages/BoardPage/components/board/Board";
import useBoardAssignedInternalBotChangedHandlers from "@/controllers/socket/board/useBoardAssignedInternalBotChangedHandlers";
import useInternalBotUpdatedHandlers from "@/controllers/socket/global/useInternalBotUpdatedHandlers";
import useSwitchSocketHandlers from "@/core/hooks/useSwitchSocketHandlers";
import { GraphApprovalRequestModel, InternalBotModel, Project } from "@/core/models";
import { EGraphApprovalScopeTable, EGraphApprovalStatus } from "@/core/models/GraphApprovalRequestModel";
import { EHttpStatus, ESocketTopic } from "@langboard/core/enums";
import useBoardBotStatusMapHandlers from "@/controllers/socket/board/useBoardBotStatusMapHandlers";
import { BoardBotScopeList, isBoardBotScopeGraphApprovalOriginType } from "@/pages/BoardPage/components/board/BoardBotScope";
import useGetProject from "@/controllers/api/board/useGetProject";
import useGetGraphApprovals from "@/controllers/api/board/graphApprovals/useGetGraphApprovals";
import BoardActivityDialog from "@/pages/BoardPage/components/board/BoardActivityDialog";
import { cn } from "@/core/utils/ComponentUtils";
import useCardRelationshipsUpdatedHandlers from "@/controllers/socket/card/useCardRelationshipsUpdatedHandlers";
import useGetProjects from "@/controllers/api/dashboard/useGetProjects";
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

const getCurrentPage = (pageRoute?: string): TBoardViewType => {
    switch (pageRoute) {
        case "card":
            return "card";
        case "wiki":
            return "wiki";
        case "settings":
            return "settings";
        default:
            return "board";
    }
};

type TBoardSidePanel = "botScope" | "switchProject";

const BoardProxy = memo((): React.JSX.Element => {
    const { setPageAliasRef } = usePageHeader();
    const socket = useSocket();
    const navigate = usePageNavigateRef();
    const location = useLocation();
    const [projectUID, pageRoute] = location.pathname.split("/").slice(2);
    if (!projectUID) {
        return <Navigate to={ROUTES.ERROR(EHttpStatus.HTTP_404_NOT_FOUND)} replace />;
    }

    const { data, isFetching, error, refetch } = useGetProject({ uid: projectUID });
    const { send: sendBoardBotStatusMap } = useBoardBotStatusMapHandlers({ projectUID });

    useEffect(() => {
        if (!error) {
            return;
        }

        const { handle } = setupApiErrorHandler({
            [EHttpStatus.HTTP_403_FORBIDDEN]: {
                after: () => navigate(ROUTES.ERROR(EHttpStatus.HTTP_403_FORBIDDEN), { replace: true }),
            },
            [EHttpStatus.HTTP_404_NOT_FOUND]: {
                after: () => navigate(ROUTES.ERROR(EHttpStatus.HTTP_404_NOT_FOUND), { replace: true }),
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

    if (!data || data.project.uid !== projectUID) {
        return <SkeletonBoard />;
    }

    return <BoardProxyDisplay project={data.project} pageRoute={pageRoute} isFetching={isFetching} />;
});

interface IBoardProxyDisplayProps {
    project: Project.TModel;
    pageRoute: string;
    isFetching: bool;
}

function BoardProxyDisplay({ pageRoute, isFetching, project }: IBoardProxyDisplayProps): React.JSX.Element {
    const [t] = useTranslation();
    const { setPageAliasRef } = usePageHeader();
    const socket = useSocket();
    const { currentUser } = useAuth();
    const navigate = usePageNavigateRef();
    const [isCardExpanded, setIsCardExpanded] = useState(false);
    const [isActivityDialogOpened, setIsActivityDialogOpened] = useState(false);
    const [activeSidePanel, setActiveSidePanel] = useState<TBoardSidePanel>();
    const [isMobile, setIsMobile] = useState(window.innerWidth < ScreenMap.size.md);
    const isBotScopeOpened = activeSidePanel === "botScope";
    const isSwitchProjectOpened = activeSidePanel === "switchProject";
    const openActivityDialog = useCallback(() => {
        setIsActivityDialogOpened(true);
    }, [setIsActivityDialogOpened]);
    const toggleBotScope = useCallback(() => {
        setActiveSidePanel((value) => (value === "botScope" ? undefined : "botScope"));
    }, [setActiveSidePanel]);
    const toggleSwitchProject = useCallback(() => {
        setActiveSidePanel((value) => (value === "switchProject" ? undefined : "switchProject"));
    }, [setActiveSidePanel]);
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
    const isCardPage = !!pageRoute && !["wiki", "settings"].includes(pageRoute);
    const projectTitle = project.useField("title");
    useGetGraphApprovals(
        {
            project_uid: project.uid,
            status: EGraphApprovalStatus.Pending,
            limit: 100,
        },
        {
            interceptToast: false,
        }
    );
    const graphApprovalRequestedHandlers = useBoardGraphApprovalRequestedHandlers({ projectUID: project.uid });
    const graphApprovalUpdatedHandlers = useBoardGraphApprovalUpdatedHandlers({ projectUID: project.uid });
    const graphApprovalDeletedHandlers = useBoardGraphApprovalDeletedHandlers({ projectUID: project.uid });
    const pendingGraphApprovals = GraphApprovalRequestModel.Model.useModels(
        (approval) =>
            approval.project_uid === project.uid &&
            approval.status === EGraphApprovalStatus.Pending &&
            isBoardBotScopeGraphApprovalOriginType(approval.origin_type) &&
            approval.scope_table === EGraphApprovalScopeTable.Project &&
            approval.scope_uid === project.uid,
        [project]
    );
    const pendingGraphApprovalCount = pendingGraphApprovals.length;
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
            name: t("board.Activity"),
            onClick: openActivityDialog,
            active: isActivityDialogOpened,
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
    switch (boardViewType) {
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
                headerNavs={headerNavs}
                headerTitle={projectTitle}
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
                {currentUser && project ? (
                    <Flex
                        position="relative"
                        w="full"
                        h="full"
                        className={cn(
                            "h-[calc(100dvh_-_theme(spacing.16))] min-h-[calc(100dvh_-_theme(spacing.16))]",
                            pageRoute === "settings" ? "overflow-y-auto overflow-x-hidden" : "overflow-hidden"
                        )}
                    >
                        {!selectCardViewType && (
                            <BoardSidePanel
                                activePanel={activeSidePanel}
                                currentProjectUID={project.uid}
                                project={project}
                                onSelectProject={(selectedProjectUID) => {
                                    setActiveSidePanel(undefined);
                                    setBoardViewType("board");
                                    navigate(ROUTES.BOARD.MAIN(selectedProjectUID), { smooth: true });
                                }}
                            />
                        )}
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
                                    projectUID={project.uid}
                                    cardUID={pageRoute}
                                    embedded
                                    isExpanded={isCardExpanded}
                                    setIsExpanded={setIsCardExpanded}
                                />
                            )}
                            {!isCardPage && !selectCardViewType && (
                                <Floating.Nav
                                    fixed
                                    items={floatingNavs.map((nav, index) => ({
                                        key: index,
                                        label: nav.name,
                                        icon: nav.icon,
                                        badge: nav.badge,
                                        active: nav.active,
                                        hidden: nav.hidden,
                                        onClick: nav.onClick,
                                    }))}
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
            <BoardActivityDialog isOpened={isActivityDialogOpened} setIsOpened={setIsActivityDialogOpened} />
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
        <Box className="fixed inset-x-0 bottom-[4.75rem] top-16 z-50 overflow-hidden border-t bg-background shadow-2xl md:hidden">
            <Button variant="ghost" size="icon-sm" className="absolute right-2 top-2 z-10" onClick={onClose}>
                <IconComponent icon="x" size="5" />
            </Button>
            {children}
        </Box>
    );
}

function BoardSidePanel({
    activePanel,
    currentProjectUID,
    project,
    onSelectProject,
}: {
    activePanel?: TBoardSidePanel;
    currentProjectUID: string;
    project: Project.TModel;
    onSelectProject: (projectUID: string) => void;
}): React.JSX.Element {
    const isOpened = !!activePanel;
    const isBotScope = activePanel === "botScope";
    const title = isBotScope ? "Bots" : "Switch Project";
    const icon = isBotScope ? "bot" : "folder-kanban";
    const widthClassName = isBotScope ? "w-auto md:w-80" : "w-auto md:w-72";

    return (
        <Box
            className={cn(
                "fixed bottom-[4.75rem] left-2 right-2 z-40 h-[60dvh] max-h-[calc(100dvh-7rem)]",
                "overflow-hidden rounded-2xl border bg-background shadow-lg",
                "transition-[opacity,transform,width] duration-200 ease-out",
                "md:static md:h-full md:max-h-none md:shrink-0 md:rounded-none md:border-y-0 md:border-l-0 md:border-r md:shadow-none",
                isOpened
                    ? `translate-y-0 opacity-100 md:translate-y-0 ${widthClassName}`
                    : "pointer-events-none translate-y-4 opacity-0 md:w-0 md:translate-y-0 md:border-r-0"
            )}
            aria-hidden={!isOpened}
        >
            <Flex
                direction="col"
                h="full"
                className={cn(widthClassName, "transition-transform duration-200 ease-out", isOpened ? "translate-x-0" : "-translate-x-4")}
            >
                <Flex items="center" gap="2" className="shrink-0 border-b px-4 py-3" weight="semibold">
                    <IconComponent icon={icon} size="4" />
                    <span>{title}</span>
                </Flex>
                <Box className="min-h-0 flex-1">
                    {!isOpened ? (
                        <></>
                    ) : isBotScope ? (
                        <BoardBotScopeSidebar project={project} />
                    ) : (
                        <BoardSwitchProjectSidebar currentProjectUID={currentProjectUID} currentProject={project} onSelectProject={onSelectProject} />
                    )}
                </Box>
            </Flex>
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

function BoardSwitchProjectSidebar({
    currentProjectUID,
    currentProject,
    onSelectProject,
}: {
    currentProjectUID: string;
    currentProject: Project.TModel;
    onSelectProject: (projectUID: string) => void;
}): React.JSX.Element {
    const { data, isFetching, isLoading } = useGetProjects();
    const projects = useMemo(() => {
        const projectMap = new Map<string, Project.TModel>();
        [currentProject, ...(data?.projects ?? [])].forEach((project) => {
            projectMap.set(project.uid, project);
        });
        return [...projectMap.values()];
    }, [currentProject, data]);

    return (
        <ScrollArea.Root className="h-full min-h-0">
            <Flex direction="col" gap="1" p="2">
                {(isLoading || isFetching) && projects.length === 0 ? (
                    <Box className="px-2 py-3 text-sm text-muted-foreground">Loading...</Box>
                ) : (
                    projects.map((project) => (
                        <BoardSwitchProjectSidebarItem
                            key={project.uid}
                            project={project}
                            active={project.uid === currentProjectUID}
                            onClick={() => onSelectProject(project.uid)}
                        />
                    ))
                )}
            </Flex>
        </ScrollArea.Root>
    );
}

function BoardSwitchProjectSidebarItem({
    project,
    active,
    onClick,
}: {
    project: Project.TModel;
    active: bool;
    onClick: () => void;
}): React.JSX.Element {
    const title = project.useField("title");
    const projectType = project.useField("project_type");

    return (
        <Button
            type="button"
            variant={active ? "secondary" : "ghost"}
            className="h-auto justify-start gap-2 rounded-lg px-3 py-2 text-left"
            onClick={onClick}
        >
            <IconComponent icon="folder-kanban" size="4" />
            <Box className="min-w-0">
                <Box className="truncate text-sm font-medium">{title}</Box>
                <Box className="truncate text-xs text-muted-foreground">{projectType}</Box>
            </Box>
        </Button>
    );
}

interface IBoardFloatingNavItem extends IHeaderNavItem {
    icon: string;
    badge?: React.ReactNode;
}

export default BoardProxy;
