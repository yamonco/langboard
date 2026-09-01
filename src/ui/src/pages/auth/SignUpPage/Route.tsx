import { lazy } from "react";
import { Navigate, Outlet, RouteObject } from "react-router";
import { ProtectedAuthRoute } from "@/core/routing/ProtectedAuthRoute";
import { ROUTES } from "@/core/routing/constants";

const SignUpPage = lazy(() => import("./index"));
const CompletePage = lazy(() => import("./CompletePage"));
const ActivatePage = lazy(() => import("./ActivatePage"));

const routes: RouteObject[] = [
    {
        path: ROUTES.SIGN_UP.ROUTE,
        element: (
            <ProtectedAuthRoute>
                <SignUpPage />
                <Outlet />
            </ProtectedAuthRoute>
        ),
        children: [
            {
                index: true,
                element: <Navigate to={`${ROUTES.SIGN_UP.REQUIRED}?${new URLSearchParams(location.search).toString()}`} replace />,
            },
            {
                path: ROUTES.SIGN_UP.REQUIRED,
                element: <></>,
            },
            {
                path: ROUTES.SIGN_UP.ADDITIONAL,
                element: <></>,
            },
            {
                path: ROUTES.SIGN_UP.OPTIONAL,
                element: <></>,
            },
            {
                path: ROUTES.SIGN_UP.OVERVIEW,
                element: <></>,
            },
        ],
    },
    {
        path: ROUTES.SIGN_UP.COMPLETE,
        element: (
            <ProtectedAuthRoute>
                <CompletePage />
            </ProtectedAuthRoute>
        ),
    },
    {
        path: ROUTES.SIGN_UP.ACTIVATE,
        element: (
            <ProtectedAuthRoute>
                <ActivatePage />
            </ProtectedAuthRoute>
        ),
    },
];

export default {
    routes,
};
