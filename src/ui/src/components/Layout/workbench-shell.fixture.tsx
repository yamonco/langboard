import { createContext, useContext, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { createMemoryRouter, Link, RouterProvider, useLocation } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WorkbenchRouteLayout from "./WorkbenchRouteLayout";
import DashboardStyledLayout from "./DashboardStyledLayout";
import DropdownMenu from "@/components/base/DropdownMenu";
import "@/i18n";
import "@/assets/styles/main.css";

const PageContext = createContext("missing context");
function SidebarContent() {
    return (
        <>
            <p>{useContext(PageContext)}</p>
            <DropdownMenu.Root>
                <DropdownMenu.Trigger asChild>
                    <button type="button">Nested menu</button>
                </DropdownMenu.Trigger>
                <DropdownMenu.Content>
                    <DropdownMenu.Item>Nested item</DropdownMenu.Item>
                </DropdownMenu.Content>
            </DropdownMenu.Root>
            <Link to="/board/fixture/card">Sidebar open Card</Link>
        </>
    );
}
let pageMounts = 0;
function Page({ name }: { name: string }) {
    const location = useLocation();
    const [mountNumber, setMountNumber] = useState(0);
    useEffect(() => setMountNumber(++pageMounts), []);
    const isMobile = window.innerWidth < 768;
    const [contextOpen, setContextOpen] = useState(false);
    return (
        <PageContext.Provider value={`Sidebar ${name}`}>
            <DashboardStyledLayout
                headerNavs={[]}
                headerTitle={name}
                activityRailItems={[
                    { icon: "panel-left", label: "Explorer", active: isMobile ? contextOpen : true, onClick: () => setContextOpen((open) => !open) },
                ]}
                workbenchContext={<SidebarContent />}
                workbenchContextHidden={isMobile}
                mobileWorkbenchContext={
                    isMobile && contextOpen ? { title: "Explorer", icon: "panel-left", onClose: () => setContextOpen(false) } : undefined
                }
            >
                <h1>{name}</h1>
                <output data-testid="page-mounts">{mountNumber}</output>
                <p>{location.pathname}</p>
                <nav className="flex flex-wrap gap-2">
                    <Link to="/dashboard/projects/all">Open Dashboard</Link>
                    <Link to="/board/fixture" state={{ commandPaletteFocus: true }}>
                        Open Board
                    </Link>
                    <Link to="/board/fixture/card">Open Card</Link>
                    <Link to="/board/fixture/wiki">Open Wiki</Link>
                </nav>
            </DashboardStyledLayout>
        </PageContext.Provider>
    );
}
const router = createMemoryRouter(
    [
        {
            element: <WorkbenchRouteLayout />,
            children: [
                { path: "/dashboard/projects/all", element: <Page name="Dashboard" /> },
                { path: "/board/fixture", element: <Page name="Board" /> },
                { path: "/board/fixture/card", element: <Page name="Card" /> },
                { path: "/board/fixture/wiki", element: <Page name="Wiki" /> },
            ],
        },
    ],
    { initialEntries: ["/dashboard/projects/all"] }
);
createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={new QueryClient()}>
        <RouterProvider router={router} />
    </QueryClientProvider>
);
