import { RouteObject } from "react-router";
import WorkbenchRouteLayout from "@/components/Layout/WorkbenchRouteLayout";

export interface IRouteConfig {
    routes: RouteObject[];
    workbench?: boolean;
}

export const toRoutes = (routeConfigs: IRouteConfig[]): RouteObject[] => [
    ...routeConfigs.filter((config) => !config.workbench).flatMap((config) => config.routes),
    {
        element: <WorkbenchRouteLayout />,
        children: routeConfigs.filter((config) => config.workbench).flatMap((config) => config.routes),
    },
];
