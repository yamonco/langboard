import { DashboardStyledLayout } from "@/components/Layout";
import { IActivityRailItem } from "@/components/Layout/ActivityRail";
import useGetSettingRoles from "@/controllers/api/settings/useGetSettingRoles";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { AppSettingProvider } from "@/core/providers/AppSettingProvider";
import { useAuth } from "@/core/providers/AuthProvider";
import { ROUTES } from "@/core/routing/constants";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSocket } from "@/core/providers/SocketProvider";
import { EHttpStatus, ESettingSocketTopicID, ESocketTopic } from "@langboard/core/enums";
import { IS_OLLAMA_RUNNING } from "@/constants";
import { Navigate, useLocation } from "react-router";
import BotsPage from "@/pages/SettingsPage/BotsPage";
import ApiComfortToolsPage from "@/pages/SettingsPage/ApiComfortToolsPage";
import GlobalRelationshipsPage from "@/pages/SettingsPage/GlobalRelationshipsPage";
import InternalBotsPage from "@/pages/SettingsPage/InternalBotsPage";
import WebhooksPage from "@/pages/SettingsPage/WebhooksPage";
import NotificationSchedulePage from "@/pages/SettingsPage/NotificationSchedulePage";
import UsersPage from "@/pages/SettingsPage/UsersPage";
import ApiKeysPage from "@/pages/SettingsPage/ApiKeysPage";
import OllamaPage from "@/pages/SettingsPage/OllamaPage";
import McpServerPage from "@/pages/SettingsPage/McpServerPage";
import { AuthUser } from "@/core/models";
import useRoleActionFilter from "@/core/hooks/useRoleActionFilter";
import { ApiKeyRole, McpRole, SettingRole } from "@/core/models/roles";
import useGetOllamaHealth from "@/controllers/api/settings/ollama/useGetOllamaHealth";
import WorkflowStagesPage from "@/pages/SettingsPage/WorkflowStagesPage";
import GlobalLabelsPage from "@/pages/SettingsPage/GlobalLabelsPage";
import ProjectTemplatesPage from "@/pages/SettingsPage/ProjectTemplatesPage";
import { settingsRedirect } from "@/pages/SettingsPage/SettingsNavigation";

function SettingsProxy(): React.JSX.Element {
    const { currentUser } = useAuth();
    const [t] = useTranslation();
    const socket = useSocket();
    const navigate = usePageNavigateRef();
    const pathname = useLocation().pathname.split("/").slice(0, 3).join("/");
    const { data, error } = useGetSettingRoles();
    const [isReady, setIsReady] = useState(false);
    const [isOllamaAvailable, setIsOllamaAvailable] = useState(false);
    const [isOllamaHealthChecked, setIsOllamaHealthChecked] = useState(!IS_OLLAMA_RUNNING);
    const { mutateAsync: getOllamaHealthMutateAsync } = useGetOllamaHealth({ interceptToast: false });

    useEffect(() => {
        if (!error) {
            return;
        }

        const { handle } = setupApiErrorHandler({
            [EHttpStatus.HTTP_403_FORBIDDEN]: {
                after: () => navigate(ROUTES.ERROR(EHttpStatus.HTTP_403_FORBIDDEN), { replace: true }),
            },
        });

        handle(error);
    }, [error]);

    useEffect(() => {
        if (!data) {
            setIsReady(() => false);
            return;
        }

        if (currentUser) {
            currentUser.setting_role_actions = data.setting_role_actions ?? [];
            currentUser.api_key_role_actions = data.api_key_role_actions ?? [];
            currentUser.mcp_role_actions = data.mcp_role_actions ?? [];
        }

        const topicIds = Object.values(ESettingSocketTopicID);
        socket.subscribe(ESocketTopic.AppSettings, topicIds, () => {
            setIsReady(() => true);
        });
        setIsReady(() => true);

        return () => {
            socket.unsubscribe(ESocketTopic.AppSettings, topicIds);
        };
    }, [currentUser, data, socket]);

    useEffect(() => {
        if (!IS_OLLAMA_RUNNING) {
            setIsOllamaAvailable(false);
            setIsOllamaHealthChecked(true);
            return;
        }

        let isMounted = true;

        getOllamaHealthMutateAsync({})
            .then((health) => {
                if (!isMounted) {
                    return;
                }

                setIsOllamaAvailable(health.available);
                setIsOllamaHealthChecked(true);
            })
            .catch(() => {
                if (!isMounted) {
                    return;
                }

                setIsOllamaAvailable(false);
                setIsOllamaHealthChecked(true);
            });

        return () => {
            isMounted = false;
        };
    }, []);

    if (pathname === ROUTES.SETTINGS.OLLAMA && !IS_OLLAMA_RUNNING) {
        return <Navigate to={ROUTES.SETTINGS.API_KEYS} replace />;
    }

    let skeletonContent;
    switch (pathname) {
        case ROUTES.SETTINGS.API_KEYS:
            skeletonContent = <></>;
            break;
        case ROUTES.SETTINGS.PROJECT_TEMPLATES:
            skeletonContent = <></>;
            break;
        case ROUTES.SETTINGS.USERS:
            skeletonContent = <></>;
            break;
        case ROUTES.SETTINGS.BOTS:
            skeletonContent = <></>;
            break;
        case ROUTES.SETTINGS.INTERNAL_BOTS:
            skeletonContent = <></>;
            break;
        case ROUTES.SETTINGS.GLOBAL_RELATIONSHIPS:
            skeletonContent = <></>;
            break;
        case ROUTES.SETTINGS.API_COMFORT_TOOLS:
            skeletonContent = <></>;
            break;
        case ROUTES.SETTINGS.WEBHOOKS:
            skeletonContent = <></>;
            break;
        case ROUTES.SETTINGS.NOTIFICATION_SCHEDULE:
            skeletonContent = <></>;
            break;
        case ROUTES.SETTINGS.MCP_TOOL_GROUPS:
            skeletonContent = <></>;
            break;
        case ROUTES.SETTINGS.OLLAMA:
            skeletonContent = <></>;
            break;
    }

    return (
        <>
            {isReady && currentUser && (pathname !== ROUTES.SETTINGS.OLLAMA || isOllamaHealthChecked) ? (
                <SettingsProxyDisplay currentUser={currentUser} isOllamaAvailable={isOllamaAvailable} />
            ) : (
                <DashboardStyledLayout headerNavs={[]} headerTitle={t("board.Settings")} activityRailItems={[]} inert aria-busy>
                    {skeletonContent}
                </DashboardStyledLayout>
            )}
        </>
    );
}

function SettingsProxyDisplay({
    currentUser,
    isOllamaAvailable,
}: {
    currentUser: AuthUser.TModel;
    isOllamaAvailable: bool;
}): React.JSX.Element {
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const pathname = useLocation().pathname.split("/").slice(0, 3).join("/");
    const apiKeyRoleActions = currentUser.useField("api_key_role_actions");
    const settingRoleActions = currentUser.useField("setting_role_actions");
    const mcpRoleActions = currentUser.useField("mcp_role_actions");
    const { hasRoleAction: hasApiKeyRoleAction } = useRoleActionFilter(apiKeyRoleActions);
    const { hasRoleAction: hasSettingRoleAction } = useRoleActionFilter(settingRoleActions);
    const { hasRoleAction: hasMcpRoleAction } = useRoleActionFilter(mcpRoleActions);

    const settingsNavs: Record<string, IActivityRailItem> = {
        [ROUTES.SETTINGS.WORKFLOW_STAGES]: {
            icon: "list-tree",
            label: t("settings.Workflow stages"),
            onClick: () => navigate(ROUTES.SETTINGS.WORKFLOW_STAGES, { smooth: true }),
            hidden: !currentUser.is_admin || !hasSettingRoleAction(...SettingRole.CATEGORIZED_MAP.WorkflowStage),
        },
        [ROUTES.SETTINGS.GLOBAL_LABELS]: {
            icon: "tags",
            label: t("settings.Global labels"),
            onClick: () => navigate(ROUTES.SETTINGS.GLOBAL_LABELS, { smooth: true }),
            hidden: !currentUser.is_admin || !hasSettingRoleAction(...SettingRole.CATEGORIZED_MAP.GlobalLabel),
        },
        [ROUTES.SETTINGS.PROJECT_TEMPLATES]: {
            icon: "layout-template",
            label: t("settings.Project templates"),
            onClick: () => navigate(ROUTES.SETTINGS.PROJECT_TEMPLATES, { smooth: true }),
            hidden: !currentUser.is_admin,
        },
        [ROUTES.SETTINGS.API_KEYS]: {
            icon: "key-round",
            label: t("settings.API keys"),
            onClick: () => {
                navigate(ROUTES.SETTINGS.API_KEYS, { smooth: true });
            },
            hidden: !hasApiKeyRoleAction(...Object.values(ApiKeyRole.EAction)),
        },
        [ROUTES.SETTINGS.USERS]: {
            icon: "users",
            label: t("settings.Users"),
            onClick: () => {
                navigate(ROUTES.SETTINGS.USERS, { smooth: true });
            },
            hidden: !hasSettingRoleAction(...SettingRole.CATEGORIZED_MAP.User),
        },
        [ROUTES.SETTINGS.BOTS]: {
            icon: "bot",
            label: t("settings.Bots"),
            onClick: () => {
                navigate(ROUTES.SETTINGS.BOTS, { smooth: true });
            },
            hidden: !hasSettingRoleAction(...SettingRole.CATEGORIZED_MAP.Bot),
        },
        [ROUTES.SETTINGS.INTERNAL_BOTS]: {
            icon: "bot-message-square",
            label: t("settings.Internal bots"),
            onClick: () => {
                navigate(ROUTES.SETTINGS.INTERNAL_BOTS, { smooth: true });
            },
            hidden: !hasSettingRoleAction(...SettingRole.CATEGORIZED_MAP.InternalBot),
        },
        [ROUTES.SETTINGS.GLOBAL_RELATIONSHIPS]: {
            icon: "waypoints",
            label: t("settings.Global relationships"),
            onClick: () => {
                navigate(ROUTES.SETTINGS.GLOBAL_RELATIONSHIPS, { smooth: true });
            },
            hidden: !hasSettingRoleAction(...SettingRole.CATEGORIZED_MAP.GlobalRelationship),
        },
        [ROUTES.SETTINGS.API_COMFORT_TOOLS]: {
            icon: "package-plus",
            label: t("settings.API comfort tools"),
            onClick: () => {
                navigate(ROUTES.SETTINGS.API_COMFORT_TOOLS, { smooth: true });
            },
            hidden: !hasSettingRoleAction(...SettingRole.CATEGORIZED_MAP.ApiComfortTool),
        },
        [ROUTES.SETTINGS.WEBHOOKS]: {
            icon: "webhook",
            label: t("settings.Webhooks"),
            onClick: () => {
                navigate(ROUTES.SETTINGS.WEBHOOKS, { smooth: true });
            },
            hidden: !hasSettingRoleAction(...SettingRole.CATEGORIZED_MAP.Webhook),
        },
        [ROUTES.SETTINGS.NOTIFICATION_SCHEDULE]: {
            icon: "bell",
            label: t("settings.Notification schedule"),
            onClick: () => {
                navigate(ROUTES.SETTINGS.NOTIFICATION_SCHEDULE, { smooth: true });
            },
            hidden: !hasSettingRoleAction(...SettingRole.CATEGORIZED_MAP.NotificationSchedule),
        },
        [ROUTES.SETTINGS.MCP_TOOL_GROUPS]: {
            icon: "package",
            label: t("mcp.MCP Server"),
            onClick: () => {
                navigate(ROUTES.SETTINGS.MCP_TOOL_GROUPS, { smooth: true });
            },
            hidden: !hasMcpRoleAction(...Object.values(McpRole.EAction)),
        },
    };

    if (IS_OLLAMA_RUNNING && isOllamaAvailable) {
        settingsNavs[ROUTES.SETTINGS.OLLAMA] = {
            icon: "ollama",
            label: t("settings.Ollama"),
            onClick: () => {
                navigate(ROUTES.SETTINGS.OLLAMA, { smooth: true });
            },
            hidden: !hasSettingRoleAction(...SettingRole.CATEGORIZED_MAP.Ollama),
        };
    }

    if (settingsNavs[pathname]) {
        settingsNavs[pathname].active = true;
    }

    let pageContent;
    switch (pathname) {
        case ROUTES.SETTINGS.WORKFLOW_STAGES:
            pageContent = <WorkflowStagesPage currentUser={currentUser} />;
            break;
        case ROUTES.SETTINGS.GLOBAL_LABELS:
            pageContent = <GlobalLabelsPage currentUser={currentUser} />;
            break;
        case ROUTES.SETTINGS.PROJECT_TEMPLATES:
            pageContent = <ProjectTemplatesPage />;
            break;
        case ROUTES.SETTINGS.API_KEYS:
            pageContent = <ApiKeysPage />;
            break;
        case ROUTES.SETTINGS.USERS:
            pageContent = <UsersPage />;
            break;
        case ROUTES.SETTINGS.BOTS:
            pageContent = <BotsPage />;
            break;
        case ROUTES.SETTINGS.INTERNAL_BOTS:
            pageContent = <InternalBotsPage />;
            break;
        case ROUTES.SETTINGS.GLOBAL_RELATIONSHIPS:
            pageContent = <GlobalRelationshipsPage />;
            break;
        case ROUTES.SETTINGS.API_COMFORT_TOOLS:
            pageContent = <ApiComfortToolsPage />;
            break;
        case ROUTES.SETTINGS.WEBHOOKS:
            pageContent = <WebhooksPage />;
            break;
        case ROUTES.SETTINGS.NOTIFICATION_SCHEDULE:
            pageContent = <NotificationSchedulePage />;
            break;
        case ROUTES.SETTINGS.MCP_TOOL_GROUPS:
            pageContent = <McpServerPage />;
            break;
        case ROUTES.SETTINGS.OLLAMA:
            pageContent = IS_OLLAMA_RUNNING && isOllamaAvailable ? <OllamaPage /> : null;
            break;
    }

    useEffect(() => {
        const redirect = settingsRedirect(settingsNavs, pathname, ROUTES.DASHBOARD.PROJECTS.ALL);
        if (redirect) navigate(redirect, { replace: true });
    }, [pathname, currentUser.is_admin, hasApiKeyRoleAction, hasSettingRoleAction, hasMcpRoleAction, isOllamaAvailable]);

    return (
        <DashboardStyledLayout headerNavs={[]} headerTitle={t("board.Settings")} activityRailItems={Object.values(settingsNavs)}>
            <AppSettingProvider currentUser={currentUser}>{pageContent}</AppSettingProvider>
        </DashboardStyledLayout>
    );
}

export default SettingsProxy;
