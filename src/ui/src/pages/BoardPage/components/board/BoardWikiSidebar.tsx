import { useTranslation } from "react-i18next";
import { useLocation } from "react-router";
import useGetWikis from "@/controllers/api/wiki/useGetWikis";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";
import { cn } from "@/core/utils/ComponentUtils";

export default function BoardWikiSidebar({ projectUID, onNavigate }: { projectUID: string; onNavigate?: () => void }) {
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const location = useLocation();
    const { data, isFetching, error } = useGetWikis({ project_uid: projectUID });
    const wikis = data?.wikis.filter((wiki) => !wiki.forbidden && !wiki.isInBin) ?? [];
    const open = (url: string) => {
        navigate(url);
        onNavigate?.();
    };

    return (
        <nav aria-label={t("board.Wiki")} data-workbench-context="" className="flex h-full min-w-0 flex-col overflow-hidden">
            <div className="flex shrink-0 items-center justify-between border-b px-3 py-2 text-xs font-semibold uppercase tracking-wide">
                <span>{t("board.Wiki")}</span>
                <button type="button" className="text-primary hover:underline" onClick={() => open(ROUTES.BOARD.WIKI(projectUID))}>
                    {t("dashboard.Open wiki")}
                </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
                {error ? (
                    <p role="alert" className="px-2 py-3 text-sm text-destructive">
                        {t("dashboard.Could not load wikis")}
                    </p>
                ) : isFetching && !data ? (
                    <p role="status" className="px-2 py-3 text-sm text-muted-foreground">
                        {t("dashboard.Loading wikis")}
                    </p>
                ) : !wikis.length ? (
                    <p className="px-2 py-3 text-sm text-muted-foreground">{t("dashboard.No wikis")}</p>
                ) : (
                    wikis.map((wiki) => {
                        const route = ROUTES.BOARD.WIKI_PAGE(projectUID, wiki.uid);
                        return (
                            <button
                                key={wiki.uid}
                                type="button"
                                aria-current={location.pathname === route ? "page" : undefined}
                                className={cn(
                                    "block w-full truncate rounded px-2 py-1 text-left text-sm hover:bg-muted",
                                    "aria-[current=page]:bg-muted aria-[current=page]:text-primary"
                                )}
                                title={wiki.title}
                                onClick={() => open(route)}
                            >
                                {wiki.title}
                            </button>
                        );
                    })
                )}
            </div>
        </nav>
    );
}
