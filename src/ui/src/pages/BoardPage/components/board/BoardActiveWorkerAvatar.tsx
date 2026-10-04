import IconComponent from "@/components/base/IconComponent";
import type { IStore as ProjectCard } from "@/core/models/ProjectCard";
import { cn } from "@/core/utils/ComponentUtils";
import { formatTimerDuration } from "@/core/utils/LocaleFormat";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

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
    const { i18n } = useTranslation();
    const [now, setNow] = useState(Date.now);
    useEffect(() => {
        if (worker?.status !== "started") return;
        const timer = window.setInterval(() => setNow(Date.now()), 1000);
        return () => window.clearInterval(timer);
    }, [worker?.status]);
    if (!worker) return <>{avatar}</>;
    const running = worker.status === "started";
    const title = `${running ? startedLabel : pausedLabel}: ${worker.checkitems
        .map((item) => {
            const seconds =
                item.elapsed_seconds + (item.status === "started" ? Math.max(0, Math.floor((now - Date.parse(item.sampled_at)) / 1000)) : 0);
            return `${item.title} · ${formatTimerDuration(
                { hours: Math.floor(seconds / 3600), minutes: Math.floor((seconds % 3600) / 60), seconds: seconds % 60 },
                i18n.language
            )}`;
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
