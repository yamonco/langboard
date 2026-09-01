import { Navigate, Outlet, RouteObject } from "react-router";
import { AuthGuard } from "@/core/routing/AuthGuard";
import { ROUTES } from "@/core/routing/constants";
import { lazy } from "react";

const ModalPage = lazy(() => import("./ModalPage"));
const DashboardProxy = lazy(() => import("./index"));

const routes: RouteObject[] = [
    {
        path: ROUTES.DASHBOARD.ROUTE,
        element: (
            <AuthGuard>
                <DashboardProxy />
                <Outlet />
            </AuthGuard>
        ),
        children: [
            {
                index: true,
                element: <Navigate to={ROUTES.DASHBOARD.PROJECTS.ALL} />,
            },
            {
                path: ROUTES.DASHBOARD.CARDS,
                element: <></>,
            },
            {
                path: ROUTES.DASHBOARD.TRACKING,
                element: <></>,
            },
            {
                path: ROUTES.DASHBOARD.PROJECTS.TAB(":tabType"),
                element: <></>,
            },
            ...createModalRoutes("cards"),
            ...createModalRoutes("tracking"),
            ...createModalRoutes("projects", ":tabType"),
        ],
    },
];

function createModalRoutes(type: string, tabName?: string): RouteObject[] {
    return [
        {
            path: createModalRoutePath(type, "new-project", tabName),
            element: <ModalPage />,
        },
        {
            path: createModalRoutePath(type, "my-activity", tabName),
            element: <ModalPage />,
        },
    ];
}

function createModalRoutePath(type: string, modal: string, tabName?: string): string {
    if (tabName) {
        return ROUTES.DASHBOARD.PROJECTS.TAB(`${tabName}/${modal}`);
    } else {
        return ROUTES.DASHBOARD.PAGE_TYPE(`${type}/${modal}`);
    }
}

export default {
    routes,
};
