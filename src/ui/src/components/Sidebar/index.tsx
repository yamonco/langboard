import { useState } from "react";
import { useTranslation } from "react-i18next";
import SidebarNavItems from "@/components/Sidebar/SidebarNavItems";
import { ISidebarProps } from "@/components/Sidebar/types";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Floating from "@/components/base/Floating";
import IconComponent from "@/components/base/IconComponent";
import { cn } from "@/core/utils/ComponentUtils";

function Sidebar({ navs, main, floatingIcon = "plus", floatingTitle = "common.Actions" }: ISidebarProps) {
    const [t] = useTranslation();
    const [isCollapsed, setIsCollapsed] = useState(false);

    return (
        <>
            <Box
                display={{ md: "grid" }}
                w="full"
                className={cn(
                    "group/sidebar h-[calc(100vh_-_theme(spacing.16))] transition-all duration-200 ease-in-out",
                    "data-[collapsed=true]:grid-cols-[52px_1fr]",
                    "md:data-[collapsed=false]:grid-cols-[220px_1fr] lg:data-[collapsed=false]:grid-cols-[280px_1fr]"
                )}
                data-collapsed={isCollapsed}
            >
                <Box position="relative" display={{ initial: "hidden", md: "block" }} size="full" data-workbench-sidebar="">
                    <aside
                        className={cn(
                            "sticky z-50 flex size-full flex-col items-start border-r text-sm font-medium transition-all duration-100",
                            "group-data-[collapsed=true]/sidebar:p-1 lg:group-data-[collapsed=true]/sidebar:p-2",
                            "group-data-[collapsed=false]/sidebar:p-2 lg:group-data-[collapsed=false]/sidebar:p-3"
                        )}
                    >
                        <SidebarNavItems navs={navs} isCollapsed={isCollapsed} />
                    </aside>

                    <Button
                        variant="secondary"
                        aria-label={t(isCollapsed ? "common.Expand" : "common.Collapse")}
                        onClick={() => setIsCollapsed(!isCollapsed)}
                        className="absolute right-1 top-1/2 z-50 size-10 -translate-y-1/2 rounded-md p-0"
                    >
                        <IconComponent icon={isCollapsed ? "chevron-right" : "chevron-left"} size="8" />
                    </Button>
                </Box>
                {main}
            </Box>
            <Floating.Button.Root>
                <Floating.Button.Content key="sidebar-floating-content">
                    <SidebarNavItems isFloating navs={navs} />
                </Floating.Button.Content>
                <Floating.Button.Trigger key="sidebar-floating-trigger" icon={floatingIcon} title={t(floatingTitle)} titleSide="right" />
            </Floating.Button.Root>
        </>
    );
}

export default Sidebar;
