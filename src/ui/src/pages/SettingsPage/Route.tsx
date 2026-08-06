import { AuthGuard } from "@/core/routing/AuthGuard";
import { ROUTES } from "@/core/routing/constants";
import ModalPage from "@/pages/SettingsPage/ModalPage";
import { lazy } from "react";
import { Navigate, Outlet, RouteObject } from "react-router";
import { IS_OLLAMA_RUNNING } from "@/constants";

const SettingsProxy = lazy(() => import("./index"));

const routes: RouteObject[] = [
    ...(!IS_OLLAMA_RUNNING
        ? [
              {
                  path: ROUTES.SETTINGS.OLLAMA,
                  element: <Navigate to={ROUTES.SETTINGS.API_KEYS} replace />,
              },
          ]
        : []),
    {
        path: ROUTES.SETTINGS.ROUTE,
        element: (
            <AuthGuard>
                <SettingsProxy />
                <Outlet />
            </AuthGuard>
        ),
        children: [
            {
                index: true,
                element: <Navigate to={ROUTES.SETTINGS.API_KEYS} replace />,
            },
            {
                path: ROUTES.SETTINGS.API_KEYS,
                element: <></>,
            },
            {
                path: ROUTES.SETTINGS.PROJECT_TEMPLATES,
                element: <></>,
            },
            {
                path: ROUTES.SETTINGS.USERS,
                element: <></>,
            },
            {
                path: ROUTES.SETTINGS.BOTS,
                element: <></>,
            },
            {
                path: ROUTES.SETTINGS.BOT_DETAILS(":botUID"),
                element: <></>,
            },
            {
                path: ROUTES.SETTINGS.INTERNAL_BOTS,
                element: <></>,
            },
            {
                path: ROUTES.SETTINGS.INTERNAL_BOT_DETAILS(":botUID"),
                element: <></>,
            },
            {
                path: ROUTES.SETTINGS.GLOBAL_RELATIONSHIPS,
                element: <></>,
            },
            {
                path: ROUTES.SETTINGS.API_COMFORT_TOOLS,
                element: <></>,
            },
            {
                path: ROUTES.SETTINGS.WEBHOOKS,
                element: <></>,
            },
            {
                path: ROUTES.SETTINGS.NOTIFICATION_SCHEDULE,
                element: <></>,
            },
            ...(IS_OLLAMA_RUNNING
                ? [
                      {
                          path: ROUTES.SETTINGS.OLLAMA,
                          element: <></>,
                      },
                  ]
                : []),
            {
                path: ROUTES.SETTINGS.MCP_TOOL_GROUPS,
                element: <></>,
            },
            {
                path: ROUTES.SETTINGS.CREATE_API_KEY,
                element: <ModalPage />,
            },
            {
                path: ROUTES.SETTINGS.CREATE_USER,
                element: <ModalPage />,
            },
            {
                path: ROUTES.SETTINGS.CREATE_BOT,
                element: <ModalPage />,
            },
            {
                path: ROUTES.SETTINGS.CREATE_INTERNAL_BOT,
                element: <ModalPage />,
            },
            {
                path: ROUTES.SETTINGS.CREATE_GLOBAL_RELATIONSHIP,
                element: <ModalPage />,
            },
            {
                path: ROUTES.SETTINGS.CREATE_WEBHOOK,
                element: <ModalPage />,
            },
            {
                path: ROUTES.SETTINGS.CREATE_MCP_TOOL_GROUP(":groupType"),
                element: <ModalPage />,
            },
        ],
    },
];

export default {
    routes,
    loadInitially: false,
};
