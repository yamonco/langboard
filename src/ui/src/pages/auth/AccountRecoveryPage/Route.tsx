import { lazy } from "react";
import { Outlet, RouteObject } from "react-router";
import { ProtectedAuthRoute } from "@/core/routing/ProtectedAuthRoute";
import { ROUTES } from "@/core/routing/constants";

const AccountRecoveryPage = lazy(() => import("."));

const routes: RouteObject[] = [
    {
        path: ROUTES.ACCOUNT_RECOVERY.NAME,
        element: (
            <ProtectedAuthRoute>
                <AccountRecoveryPage />
                <Outlet />
            </ProtectedAuthRoute>
        ),
        children: [
            {
                index: true,
                element: <></>,
            },
            {
                path: ROUTES.ACCOUNT_RECOVERY.RESET,
                element: <></>,
            },
        ],
    },
];

export default {
    routes,
};
