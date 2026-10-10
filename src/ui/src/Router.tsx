import { createBrowserRouter, Navigate, RouteObject } from "react-router";
import { RouterProvider } from "react-router/dom";
import SuspenseComponent from "@/components/base/SuspenseComponent";
import { ROUTES } from "@/core/routing/constants";
import { memo, useEffect, useMemo } from "react";
import useAuthStore from "@/core/stores/AuthStore";
import SwallowErrorBoundary from "@/components/SwallowErrorBoundary";
import { EHttpStatus } from "@langboard/core/enums";
import { IS_OLLAMA_RUNNING } from "@/constants";
import WorkbenchRouteLayout from "@/components/Layout/WorkbenchRouteLayout";

interface IRouteConfig {
    routes: RouteObject[];
    workbench?: boolean;
}

type TRouteModule = { default: IRouteConfig };
// Route declarations are small; their page components remain lazy. Bootstrap
// must not wait for every unrelated route chunk before authentication starts.
const pages = Object.values(import.meta.glob<TRouteModule>("./pages/**/Route.tsx", { eager: true }));

const toRoutes = (routeConfigs: IRouteConfig[]): RouteObject[] => [
    ...routeConfigs.filter((config) => !config.workbench).flatMap((config) => config.routes),
    {
        element: <WorkbenchRouteLayout />,
        children: routeConfigs.filter((config) => config.workbench).flatMap((config) => config.routes),
    },
];

const routes = toRoutes(pages.map((page) => page.default));

export interface IRouterProps {
    children: React.ReactNode;
}

const Router = memo(({ children }: IRouterProps) => {
    useEffect(() => {
        useAuthStore.setState(() => ({ pageLoaded: true }));
    }, []);

    const router = useMemo(() => {
        const routeList: RouteObject[] = [
            ...(!IS_OLLAMA_RUNNING
                ? [
                      {
                          path: ROUTES.SETTINGS.OLLAMA,
                          element: <Navigate to={ROUTES.SETTINGS.API_KEYS} replace />,
                      },
                  ]
                : []),
            ...routes,
            {
                path: "*",
                element: <Navigate to={ROUTES.ERROR(EHttpStatus.HTTP_404_NOT_FOUND)} />,
            },
        ];

        return createBrowserRouter([
            {
                path: "/",
                element: (
                    <SwallowErrorBoundary>
                        <SuspenseComponent shouldWrapChildren={false} isPage>
                            {children}
                        </SuspenseComponent>
                    </SwallowErrorBoundary>
                ),
                children: routeList,
            },
        ]);
    }, [children]);

    return <RouterProvider router={router} />;
});

export default Router;
