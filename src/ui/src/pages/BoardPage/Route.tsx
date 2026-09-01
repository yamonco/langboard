import { lazy } from "react";
import { Navigate, type RouteObject } from "react-router";
import { AuthGuard } from "@/core/routing/AuthGuard";
import { ROUTES } from "@/core/routing/constants";
import { EHttpStatus } from "@langboard/core/enums";

const BoardRoutePage = lazy(() => import("./RoutePage"));
const WikiActivityDialog = lazy(() => import("./components/wiki/WikiActivityDialog"));
const WikiMetadataDialog = lazy(() => import("./components/wiki/WikiMetadataDialog"));
const BoardInvitationPage = lazy(() => import("./BoardInvitationPage"));

const routes: RouteObject[] = [
    {
        path: ROUTES.BOARD.ROUTE,
        children: [
            {
                index: true,
                element: <Navigate to={ROUTES.ERROR(EHttpStatus.HTTP_404_NOT_FOUND)} replace />,
            },
        ],
    },
    {
        path: ROUTES.BOARD.MAIN(":projectUID"),
        element: (
            <AuthGuard>
                <BoardRoutePage />
            </AuthGuard>
        ),
        children: [
            {
                path: "wiki",
                element: <></>,
            },
            {
                path: "wiki/:wikiUID",
                element: <></>,
            },
            {
                path: "wiki/:wikiUID/activity",
                element: <WikiActivityDialog />,
            },
            {
                path: "wiki/:wikiUID/metadata",
                element: <WikiMetadataDialog />,
            },
            {
                path: "settings",
                element: <></>,
            },
            {
                path: "settings/:page",
                element: <></>,
            },
            {
                path: ":cardUID",
                element: <></>,
            },
        ],
    },
    {
        path: ROUTES.BOARD.INVITATION,
        element: (
            <AuthGuard>
                <BoardInvitationPage />
            </AuthGuard>
        ),
    },
];

export default {
    routes,
};
