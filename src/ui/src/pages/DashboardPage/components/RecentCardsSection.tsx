import { useEffect } from "react";
import { useLocation } from "react-router";
import { useTranslation } from "react-i18next";
import IconComponent from "@/components/base/IconComponent";
import { ProjectCard } from "@/core/models";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";
import { cn } from "@/core/utils/ComponentUtils";
import { useSocketOutsideProvider } from "@/core/providers/SocketProvider";
import { SocketEvents } from "@langboard/core/constants";
import { ESocketTopic } from "@langboard/core/enums";
import { closeCard, toggleCardPin } from "./OpenCardsStore";
import useValidateRecentCards from "./useValidateRecentCards";
import type { IOpenCard } from "./OpenCardsData";

export default function RecentCardsSection({
    userUID,
    cards: visibleOpenCards,
    collapsed: openCardsCollapsed,
    expanded: showOlderCards,
    onToggle,
    onExpand,
    onNavigate,
}: {
    userUID: string;
    cards: IOpenCard[];
    collapsed: boolean;
    expanded: boolean;
    onToggle: () => void;
    onExpand: () => void;
    onNavigate?: () => void;
}) {
    useValidateRecentCards(userUID, visibleOpenCards);
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const location = useLocation();
    const displayedCards = showOlderCards ? visibleOpenCards : visibleOpenCards.slice(0, 10);
    const projectUIDs = [...new Set(visibleOpenCards.map((card) => card.projectUID))].sort().join(",");
    useEffect(() => {
        const socket = useSocketOutsideProvider();
        // useGetProjects owns these Dashboard subscriptions. Listen without a second owner.
        const listeners = projectUIDs
            .split(",")
            .filter(Boolean)
            .map((uid) => ({
                topic: ESocketTopic.Dashboard as const,
                topicId: uid,
                event: SocketEvents.SERVER.DASHBOARD.CARD.DELETED.replace("{uid}", uid),
                eventKey: `recent-card-deleted-${userUID}-${uid}`,
                callback: (data: unknown) => {
                    if (data && typeof data === "object" && "uid" in data && typeof data.uid === "string") closeCard(userUID, uid, data.uid);
                },
            }));
        listeners.forEach((props) => socket.on(props));
        return () => listeners.forEach((props) => socket.off(props));
    }, [userUID, projectUIDs]);
    return (
        <section className="mb-2 flex max-h-[40%] min-h-0 shrink-0 flex-col" aria-label={t("dashboard.Recent cards")}>
            <button
                type="button"
                aria-expanded={!openCardsCollapsed}
                className="flex w-full shrink-0 items-center gap-1 px-2 py-1 text-left text-xs font-medium text-muted-foreground"
                onClick={onToggle}
            >
                <IconComponent icon={openCardsCollapsed ? "chevron-right" : "chevron-down"} size="3" />
                {t("dashboard.Recent cards")}
                {visibleOpenCards.length > 0 && <span className="ml-auto">{visibleOpenCards.length}</span>}
            </button>
            {!openCardsCollapsed && (
                <div className="min-h-0 overflow-y-auto" data-recent-card-list="">
                    {displayedCards.map((card) => {
                        const active = location.pathname === ROUTES.BOARD.CARD(card.projectUID, card.cardUID);
                        return (
                            <div key={`${card.projectUID}:${card.cardUID}`} className="group flex min-h-8 items-center rounded-md hover:bg-muted">
                                <button
                                    type="button"
                                    aria-current={active ? "page" : undefined}
                                    title={card.title}
                                    className={cn(
                                        "flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1 text-left text-sm",
                                        active && "bg-muted text-primary"
                                    )}
                                    onClick={() => {
                                        navigate(ROUTES.BOARD.CARD(card.projectUID, card.cardUID));
                                        onNavigate?.();
                                    }}
                                >
                                    <IconComponent icon="file-text" size="3" className="shrink-0" />
                                    <span className="truncate">{card.title}</span>
                                    <OpenCardUnreadDot cardUID={card.cardUID} />
                                </button>
                                <button
                                    type="button"
                                    aria-label={t(card.pinned ? "dashboard.Unpin card" : "dashboard.Pin card")}
                                    title={t(card.pinned ? "dashboard.Unpin card" : "dashboard.Pin card")}
                                    className={cn(
                                        "rounded p-1 hover:bg-accent",
                                        !card.pinned && "opacity-0 focus:opacity-100 group-hover:opacity-100"
                                    )}
                                    onClick={() => toggleCardPin(userUID, card.projectUID, card.cardUID)}
                                >
                                    <IconComponent icon="pin" size="3" className={card.pinned ? "text-primary" : undefined} />
                                </button>
                                <button
                                    type="button"
                                    aria-label={t("dashboard.Close card from list")}
                                    title={t("dashboard.Close card from list")}
                                    className="mr-1 rounded p-1 opacity-0 hover:bg-accent focus:opacity-100 group-hover:opacity-100"
                                    onClick={() => closeCard(userUID, card.projectUID, card.cardUID)}
                                >
                                    <IconComponent icon="x" size="3" />
                                </button>
                            </div>
                        );
                    })}
                </div>
            )}
            {!openCardsCollapsed && visibleOpenCards.length > 10 && (
                <button
                    type="button"
                    aria-expanded={showOlderCards}
                    className="shrink-0 rounded px-2 py-1 text-left text-xs text-muted-foreground hover:bg-muted"
                    onClick={onExpand}
                >
                    {showOlderCards ? t("dashboard.Show fewer cards") : t("dashboard.Show older cards", { count: visibleOpenCards.length - 10 })}
                </button>
            )}
        </section>
    );
}

function OpenCardUnreadDot({ cardUID }: { cardUID: string }) {
    const model = ProjectCard.Model.useModel(cardUID, [cardUID]);
    return model ? <LiveUnreadDot model={model} /> : null;
}

function LiveUnreadDot({ model }: { model: ProjectCard.TModel }) {
    const [t] = useTranslation();
    const unread = model.useField("has_unread_change");
    return unread ? <span aria-label={t("board.Unread changes")} className="ml-auto size-1.5 shrink-0 rounded-full bg-primary" /> : null;
}
