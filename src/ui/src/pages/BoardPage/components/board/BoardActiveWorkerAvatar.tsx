import IconComponent from "@/components/base/IconComponent";
import type { IStore as ProjectCard } from "@/core/models/ProjectCard";
import { cn } from "@/core/utils/ComponentUtils";
import { useEffect, useState, type ReactNode } from "react";

type ActiveWorker = NonNullable<ProjectCard["active_workers"]>[number];

export default function BoardActiveWorkerAvatar({
    avatar,
    worker,
    startedLabel,
    pausedLabel,
}: {
    avatar: ReactNode;
    worker: ActiveWorker | undefined;
    startedLabel: string;
    pausedLabel: string;
}) {
    const [now, setNow] = useState(Date.now);
    useEffect(() => {
        if (worker?.status !== "started") return;
        const timer = window.setInterval(() => setNow(Date.now()), 1000);
        return () => window.clearInterval(timer);
    }, [worker?.status]);
    if (!worker) return <>{avatar}</>;
    const running = worker.status === "started";
    const duration = (seconds: number) => {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const remainder = seconds % 60;
        return `${hours ? `${hours}:` : ""}${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
    };
    const title = `${running ? startedLabel : pausedLabel}: ${worker.checkitems
        .map((item) => {
            const seconds =
                item.elapsed_seconds + (item.status === "started" ? Math.max(0, Math.floor((now - Date.parse(item.sampled_at)) / 1000)) : 0);
            return `${item.title} · ${duration(seconds)}`;
        })
        .join(", ")}`;
    return (
        <span className="relative inline-flex shrink-0" title={title} aria-label={title} tabIndex={0}>
            {avatar}
            <span
                className={cn(
                    "pointer-events-none absolute -bottom-1 -right-1 inline-flex size-4 items-center",
                    "justify-center rounded-full border border-background",
                    running ? "bg-emerald-600 text-white" : "bg-muted text-muted-foreground"
                )}
            >
                <IconComponent icon={running ? "hammer" : "pause"} size="3" aria-hidden="true" />
            </span>
        </span>
    );
}
