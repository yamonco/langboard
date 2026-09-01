import { lazy } from "react";
import { Navigate, Outlet, RouteObject } from "react-router";
import { AuthGuard } from "@/core/routing/AuthGuard";
import { ROUTES } from "@/core/routing/constants";

const AccountPage = lazy(() => import("./index"));
const EmailVerificationPage = lazy(() => import("./EmailVerificationPage"));

const routes: RouteObject[] = [
    {
        path: ROUTES.ACCOUNT.ROUTE,
        element: (
            <AuthGuard>
                <AccountPage />
                <Outlet />
            </AuthGuard>
        ),
        children: [
            {
                index: true,
                element: <Navigate to={ROUTES.ACCOUNT.PROFILE} replace />,
            },
            {
                path: ROUTES.ACCOUNT.PROFILE,
                element: <></>,
            },
            {
                path: ROUTES.ACCOUNT.EMAILS.ROUTE,
                element: <></>,
            },
            {
                path: ROUTES.ACCOUNT.PASSWORD,
                element: <></>,
            },
            {
                path: ROUTES.ACCOUNT.GROUPS,
                element: <></>,
            },
            {
                path: ROUTES.ACCOUNT.PREFERENCES,
                element: <></>,
            },
        ],
    },
    {
        path: ROUTES.ACCOUNT.EMAILS.VERIFY,
        element: (
            <AuthGuard message="myAccount.errors.You must sign in before verifying your email.">
                <EmailVerificationPage />
            </AuthGuard>
        ),
    },
];

export default {
    routes,
};
