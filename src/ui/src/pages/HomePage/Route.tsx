import { ROUTES } from "@/core/routing/constants";
import { lazy } from "react";
import { RouteObject } from "react-router";

const Redirect = lazy(() => import("./Redirect"));
const HomePage = lazy(() => import("./index"));

const routes: RouteObject[] = [
    {
        path: "/",
        children: [
            {
                index: true,
                element: <HomePage />,
            },
            {
                path: ROUTES.REDIRECT,
                element: <Redirect />,
            },
        ],
    },
];

export default {
    routes,
};
