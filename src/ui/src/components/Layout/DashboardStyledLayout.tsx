import { forwardRef } from "react";
import Header from "@/components/Header";
import { IHeaderNavItem } from "@/components/Header/types";
import ResizableSidebar, { IResizableSidebarProps } from "@/components/ResizableSidebar";
import Sidebar from "@/components/Sidebar";
import { ISidebarNavItem } from "@/components/Sidebar/types";
import { cn } from "@/core/utils/ComponentUtils";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import ScrollArea from "@/components/base/ScrollArea";
import useScrollToTop from "@/core/hooks/useScrollToTop";
import ActivityRail, { IActivityRailItem } from "@/components/Layout/ActivityRail";

interface IBaseDashboardStyledLayoutProps {
    children: React.ReactNode;
    headerNavs?: IHeaderNavItem[];
    headerTitle?: React.ReactNode;
    sidebarNavs?: ISidebarNavItem[];
    resizableSidebar?: Omit<IResizableSidebarProps, "main">;
    className?: string;
    scrollAreaMutable?: React.ComponentPropsWithoutRef<typeof ScrollArea.Root>["mutable"];
    activityRailItems?: IActivityRailItem[];
    workbenchContext?: React.ReactNode;
    workbenchContextHidden?: boolean;
}

interface IHeaderDashboardStyledLayoutProps extends IBaseDashboardStyledLayoutProps {
    headerNavs: IHeaderNavItem[];
    headerTitle?: React.ReactNode;
}

interface INoHeaderDashboardStyledLayoutProps extends IBaseDashboardStyledLayoutProps {
    headerNavs?: undefined;
    headerTitle?: undefined;
}

interface ISidebarDashboardStyledLayoutProps extends IBaseDashboardStyledLayoutProps {
    sidebarNavs: ISidebarNavItem[];
    resizableSidebar?: undefined;
}

interface IResizableSidebarDashboardStyledLayoutProps extends IBaseDashboardStyledLayoutProps {
    sidebarNavs?: undefined;
    resizableSidebar: Omit<IResizableSidebarProps, "main">;
}

export type TDashboardStyledLayoutProps =
    | IHeaderDashboardStyledLayoutProps
    | INoHeaderDashboardStyledLayoutProps
    | ISidebarDashboardStyledLayoutProps
    | IResizableSidebarDashboardStyledLayoutProps
    | IBaseDashboardStyledLayoutProps;

const DashboardStyledLayout = forwardRef<HTMLDivElement, TDashboardStyledLayoutProps>(
    (
        {
            children,
            headerNavs,
            headerTitle,
            sidebarNavs,
            resizableSidebar,
            activityRailItems,
            workbenchContext,
            workbenchContextHidden,
            className,
            scrollAreaMutable,
            ...props
        },
        ref
    ) => {
        const { scrollableRef, isAtTop, scrollToTop } = useScrollToTop({});

        const main = (
            <ScrollArea.Root viewportId="main" mutable={scrollAreaMutable} className="relative size-full overflow-y-auto" viewportRef={scrollableRef}>
                <main className={cn("relative size-full overflow-y-auto p-4 md:p-6 lg:p-8", className)}>
                    {children}
                    {!isAtTop && (
                        <Button
                            onClick={scrollToTop}
                            size="icon"
                            variant="outline"
                            className="fixed bottom-2 left-1/2 inline-flex -translate-x-1/2 transform rounded-full shadow-md"
                        >
                            <IconComponent icon="arrow-up" size="4" />
                        </Button>
                    )}
                </main>
            </ScrollArea.Root>
        );

        let sidebar;
        if (sidebarNavs) {
            sidebar = <Sidebar navs={sidebarNavs} main={main} />;
        } else if (resizableSidebar) {
            sidebar = <ResizableSidebar main={main} {...resizableSidebar} compactHeight={!!activityRailItems} />;
        } else {
            sidebar = main;
        }

        return (
            <Flex direction="col" w="full" minH="screen" ref={ref} {...props}>
                {headerNavs && <Header navs={headerNavs} title={headerTitle} compact={!!activityRailItems} />}
                <Box
                    w="full"
                    className={cn("overflow-y-auto", activityRailItems ? "h-[calc(100dvh-2.75rem)]" : "min-h-[calc(100vh_-_theme(spacing.16))]")}
                >
                    {activityRailItems ? (
                        <div className="flex size-full">
                            <ActivityRail items={activityRailItems} />
                            <div className="min-w-0 flex-1">
                                {workbenchContext ? (
                                    <ResizableSidebar
                                        main={<div className="min-w-0 flex-1">{sidebar}</div>}
                                        initialWidth={280}
                                        collapsableWidth={220}
                                        minWidth={220}
                                        maxWidth={420}
                                        compactHeight
                                        floatingHidden
                                        showCollapseButton={false}
                                        hidden={workbenchContextHidden}
                                    >
                                        {workbenchContextHidden ? null : workbenchContext}
                                    </ResizableSidebar>
                                ) : (
                                    sidebar
                                )}
                            </div>
                        </div>
                    ) : (
                        sidebar
                    )}
                </Box>
            </Flex>
        );
    }
);

export default DashboardStyledLayout;
