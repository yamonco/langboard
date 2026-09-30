import { useMemo, useState } from "react";
import { useLocation, useOutlet } from "react-router";
import { DashboardStyledLayoutFrame, IWorkbenchLayoutConfiguration, WorkbenchLayoutContext } from "@/components/Layout/DashboardStyledLayout";

/** The router owns the physical shell; pages supply navigation and portal their context content. */
export default function WorkbenchRouteLayout() {
    const { key: routeKey } = useLocation();
    const outlet = useOutlet();
    const [configuration, configure] = useState<IWorkbenchLayoutConfiguration>();
    const [sidebarSlot, setSidebarSlot] = useState<HTMLDivElement | null>(null);
    const context = useMemo(() => ({ configure, sidebarSlot }), [sidebarSlot]);
    const pending = configuration?.routeKey !== routeKey;
    const props = configuration?.props;

    return (
        <WorkbenchLayoutContext.Provider value={context}>
            <DashboardStyledLayoutFrame
                {...props}
                inert={pending || props?.inert}
                aria-busy={pending || props?.["aria-busy"]}
                workbenchContext={configuration?.hasContext ? <div ref={setSidebarSlot} className="size-full" /> : undefined}
                workbenchContextHidden={pending || props?.workbenchContextHidden}
            >
                {outlet}
            </DashboardStyledLayoutFrame>
        </WorkbenchLayoutContext.Provider>
    );
}
