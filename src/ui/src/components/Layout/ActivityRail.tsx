import IconComponent from "@/components/base/IconComponent";
import Tooltip from "@/components/base/Tooltip";
import { cn } from "@/core/utils/ComponentUtils";

export interface IActivityRailItem {
    icon: string;
    label: string;
    onClick: () => void;
    active?: boolean;
    badge?: React.ReactNode;
    hidden?: boolean;
}

export default function ActivityRail({ items }: { items: IActivityRailItem[] }) {
    return (
        <nav aria-label="Workspace" className="hidden w-12 shrink-0 flex-col items-center gap-1 overflow-y-auto border-r bg-background py-2 md:flex">
            {items
                .filter((item) => !item.hidden)
                .map((item) => (
                    <Tooltip.Root key={item.label}>
                        <Tooltip.Trigger asChild>
                            <button
                                type="button"
                                aria-label={item.label}
                                aria-current={item.active ? "page" : undefined}
                                onClick={item.onClick}
                                className={cn(
                                    "relative flex size-10 shrink-0 items-center justify-center rounded-md text-muted-foreground",
                                    "hover:bg-muted hover:text-foreground",
                                    item.active && "bg-muted text-primary before:absolute before:inset-y-2 before:left-0 before:w-0.5",
                                    item.active && "before:rounded-full before:bg-primary"
                                )}
                            >
                                <IconComponent icon={item.icon} size="5" />
                                {item.badge ? (
                                    <span className="absolute right-0 top-0 rounded-full bg-primary px-1 text-[9px] text-primary-foreground">
                                        {item.badge}
                                    </span>
                                ) : null}
                            </button>
                        </Tooltip.Trigger>
                        <Tooltip.Content side="right">{item.label}</Tooltip.Content>
                    </Tooltip.Root>
                ))}
        </nav>
    );
}
