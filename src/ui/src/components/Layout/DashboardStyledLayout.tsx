import { forwardRef } from "react";
import { useTranslation } from "react-i18next";
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
    inert?: bool;
    "aria-busy"?: React.AriaAttributes["aria-busy"];
    scrollAreaMutable?: React.ComponentPropsWithoutRef<typeof ScrollArea.Root>["mutable"];
    activityRailItems?: IActivityRailItem[];
    workbenchContext?: React.ReactNode;
    workbenchContextHidden?: boolean;
    mobileWorkbenchContext?: { title: string; icon: string; onClose: () => void };
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
            mobileWorkbenchContext,
            className,
            scrollAreaMutable,
            ...props
        },
        ref
    ) => {
        const [t] = useTranslation();
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
                {headerNavs && (
                    <Header
                        navs={
                            activityRailItems
                                ? activityRailItems
                                      .filter((item) => !item.hidden)
                                      .map((item) => ({
                                          name: item.label,
                                          onClick: item.onClick,
                                          active: item.active,
                                      }))
                                : headerNavs
                        }
                        title={headerTitle}
                        compact={!!activityRailItems}
                        navigationReady={!props.inert}
                    />
                )}
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
                {mobileWorkbenchContext && workbenchContext && (
                    <aside
                        aria-label={mobileWorkbenchContext.title}
                        data-workbench-context=""
                        className={cn(
                            "fixed bottom-[4.75rem] left-2 right-2 z-[120] h-[60dvh] max-h-[calc(100dvh-7rem)]",
                            "overflow-hidden rounded-2xl border bg-background shadow-lg md:hidden"
                        )}
                    >
                        <Flex direction="col" h="full">
                            <Flex items="center" gap="2" className="shrink-0 border-b px-4 py-3" weight="semibold">
                                <IconComponent icon={mobileWorkbenchContext.icon} size="4" />
                                <span>{mobileWorkbenchContext.title}</span>
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon-sm"
                                    className="ml-auto"
                                    aria-label={t("common.Close")}
                                    onClick={mobileWorkbenchContext.onClose}
                                >
                                    <IconComponent icon="x" size="4" />
                                </Button>
                            </Flex>
                            <Box className="min-h-0 flex-1">{workbenchContext}</Box>
                        </Flex>
                    </aside>
                )}
            </Flex>
        );
    }
);

export default DashboardStyledLayout;
