import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { useTranslation } from "react-i18next";
import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { ROUTES } from "@/core/routing/constants";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import useGetProjects from "@/controllers/api/dashboard/useGetProjects";
import Button from "@/components/base/Button";
import DateDistance from "@/components/DateDistance";
import { cn } from "@/core/utils/ComponentUtils";

interface IMyWorkCard {
    uid: string;
    title: string;
    project_uid: string;
    project_title: string;
    project_column_name: string;
    deadline_at: string | null;
    updated_at: string;
    reasons: string[];
}

const sections = ["Overdue", "Today", "Upcoming", "Review / Check", "Assigned to me", "Mentioned", "Created by me"] as const;
type TSection = (typeof sections)[number];

function sectionFor(card: IMyWorkCard): TSection {
    if (card.reasons.includes("overdue")) return "Overdue";
    if (card.reasons.includes("due_soon")) {
        return card.deadline_at && new Date(card.deadline_at).toDateString() === new Date().toDateString() ? "Today" : "Upcoming";
    }
    if (card.reasons.includes("assigned")) {
        if (["check", "review", "검토", "검수"].includes(card.project_column_name.trim().toLowerCase())) return "Review / Check";
        return "Assigned to me";
    }
    if (card.reasons.includes("mentioned")) return "Mentioned";
    return "Created by me";
}

export default function MyWorkPage() {
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const [searchParams, setSearchParams] = useSearchParams();
    const projectUID = searchParams.get("project_uid");
    const projectScope = !!projectUID && searchParams.get("scope") !== "all";
    const { data: projectsData } = useGetProjects();
    const { data, isPending, isFetching, isError, refetch } = useQuery({
        queryKey: ["dashboard-my-work", projectScope ? projectUID : null],
        queryFn: async () => {
            const response = await api.get<{ cards: IMyWorkCard[] }>(Routing.API.DASHBOARD.MY_WORK, {
                params: projectScope ? { project_uid: projectUID } : undefined,
                env: { interceptToast: true } as never,
            });
            return response.data.cards;
        },
        retry: false,
        staleTime: 15_000,
    });

    const updateScope = (nextProjectUID: string | null, all: boolean) => {
        const next = new URLSearchParams();
        if (nextProjectUID) next.set("project_uid", nextProjectUID);
        if (all) next.set("scope", "all");
        setSearchParams(next);
    };

    const grouped = new Map<TSection, IMyWorkCard[]>(sections.map((section) => [section, []]));
    for (const card of data ?? []) grouped.get(sectionFor(card))!.push(card);

    return (
        <section className="mx-auto max-w-5xl space-y-5" aria-label={t("dashboard.My Work")}>
            <div className="flex flex-wrap items-center gap-2">
                <h1 className="mr-auto text-xl font-semibold">{t("dashboard.My Work")}</h1>
                <Button
                    size="sm"
                    variant={!projectScope ? "secondary" : "outline"}
                    aria-pressed={!projectScope}
                    onClick={() => updateScope(projectUID, true)}
                >
                    {t("dashboard.All projects")}
                </Button>
                <Button
                    size="sm"
                    variant={projectScope ? "secondary" : "outline"}
                    aria-pressed={projectScope}
                    disabled={!projectUID}
                    onClick={() => updateScope(projectUID, false)}
                >
                    {t("dashboard.Current project")}
                </Button>
                <select
                    aria-label={t("dashboard.Choose project")}
                    className="h-9 max-w-48 rounded-md border bg-background px-2 text-sm"
                    value={projectUID ?? ""}
                    onChange={(event) => updateScope(event.target.value || null, !event.target.value)}
                >
                    <option value="">{t("dashboard.Choose project")}</option>
                    {projectsData?.projects.map((project) => (
                        <option key={project.uid} value={project.uid}>
                            {project.title}
                        </option>
                    ))}
                </select>
            </div>
            {isPending ? (
                <p role="status">{t("dashboard.Loading work")}</p>
            ) : isError ? (
                <div role="alert" className="space-x-2">
                    <span>{t("dashboard.Could not load work")}</span>
                    <Button size="sm" variant="outline" onClick={() => void refetch()}>
                        {t("dashboard.Retry")}
                    </Button>
                </div>
            ) : !data?.length ? (
                <p>{t("dashboard.No work found")}</p>
            ) : (
                <>
                    <p className="text-xs text-muted-foreground" aria-live="polite">
                        {t("dashboard.Showing recent work", { count: data.length })}
                        {isFetching ? ` · ${t("dashboard.Refreshing")}` : ""}
                    </p>
                    {sections.map((section) => {
                        const cards = grouped.get(section)!;
                        if (!cards.length) return null;
                        return (
                            <section key={section} aria-label={t(`dashboard.${section}`)}>
                                <h2 className="mb-2 text-sm font-semibold">{t(`dashboard.${section}`)}</h2>
                                <div className="divide-y rounded-lg border bg-background">
                                    {cards.map((card) => (
                                        <button
                                            key={card.uid}
                                            type="button"
                                            className={cn(
                                                "flex w-full items-center gap-3 px-3 py-2 text-left",
                                                "hover:bg-muted focus-visible:outline-primary"
                                            )}
                                            onClick={() => navigate(ROUTES.BOARD.CARD(card.project_uid, card.uid))}
                                        >
                                            <span className="min-w-0 flex-1 truncate font-medium">{card.title}</span>
                                            <span className="hidden max-w-44 truncate text-xs text-muted-foreground sm:inline">
                                                {card.project_title} · {card.project_column_name}
                                            </span>
                                            <span className="shrink-0 text-xs text-muted-foreground">
                                                <DateDistance date={new Date(card.updated_at)} />
                                            </span>
                                        </button>
                                    ))}
                                </div>
                            </section>
                        );
                    })}
                </>
            )}
        </section>
    );
}
