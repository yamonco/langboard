import { Outlet, RouteObject } from "react-router";
import { ProtectedAuthRoute } from "@/core/routing/ProtectedAuthRoute";
import { ROUTES } from "@/core/routing/constants";
import { lazy } from "react";

const SignInPage = lazy(() => import("./index"));
const OidcCallbackPage = lazy(() => import("./OidcCallbackPage"));

const routes: RouteObject[] = [
    {
        path: ROUTES.SIGN_IN.EMAIL,
        element: (
            <ProtectedAuthRoute>
                <SignInPage />
                <Outlet />
            </ProtectedAuthRoute>
        ),
        children: [
            {
                index: true,
                element: <></>,
            },
            {
                path: ROUTES.SIGN_IN.PASSWORD,
                element: <></>,
            },
        ],
    },
    {
        path: ROUTES.SIGN_IN.OIDC_CALLBACK,
        element: (
            <ProtectedAuthRoute>
                <OidcCallbackPage />
            </ProtectedAuthRoute>
        ),
    },
];

export default {
    routes,
};
