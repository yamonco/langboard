import { RouteObject } from "react-router";
import { ROUTES } from "@/core/routing/constants";
import { lazy } from "react";

const ErrorPage = lazy(() => import("./index"));

const routes: RouteObject[] = [
    {
        path: ROUTES.ERROR("*").replace("/*", ""),
        children: [
            {
                path: ROUTES.ERROR("*"),
                element: <ErrorPage />,
            },
        ],
    },
];

export default {
    routes,
};
