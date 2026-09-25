import { createBrowserRouter, Navigate, RouteObject } from "react-router";
import { RouterProvider } from "react-router/dom";
import SuspenseComponent from "@/components/base/SuspenseComponent";
import { ROUTES } from "@/core/routing/constants";
import { memo, useEffect, useMemo, useState } from "react";
import useAuthStore from "@/core/stores/AuthStore";
import SwallowErrorBoundary from "@/components/SwallowErrorBoundary";
import { EHttpStatus } from "@langboard/core/enums";
import { IS_OLLAMA_RUNNING } from "@/constants";

interface IRouteConfig {
    routes: RouteObject[];
}

type TRouteModule = { default: IRouteConfig };
type TRouteImporter = () => Promise<TRouteModule>;

const pages = Object.values(import.meta.glob<TRouteModule>("./pages/**/Route.tsx"));

const loadRouteConfigs = async (importers: TRouteImporter[]) => {
    return Promise.all(
        importers.map(async (importPage) => {
            return (await importPage()).default;
        })
    );
};

const toRoutes = (routeConfigs: IRouteConfig[]) => routeConfigs.flatMap((routeConfig) => routeConfig.routes);

export interface IRouterProps {
    children: React.ReactNode;
}

const Router = memo(({ children }: IRouterProps) => {
    const [routes, setRoutes] = useState<RouteObject[] | null>(null);

    useEffect(() => {
        let isDisposed = false;

        void loadRouteConfigs(pages).then((loadedConfigs) => {
            if (isDisposed) {
                return;
            }

            setRoutes(toRoutes(loadedConfigs));
            useAuthStore.setState(() => ({
                pageLoaded: true,
            }));
        });

        return () => {
            isDisposed = true;
        };
    }, []);

    const router = useMemo(() => {
        if (!routes) {
            return null;
        }

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
    }, [children, routes]);

    if (!router) {
        return null;
    }

    return <RouterProvider router={router} />;
});

export default Router;
