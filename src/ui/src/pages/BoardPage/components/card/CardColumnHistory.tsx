import { formatDateTime } from "@/core/utils/LocaleFormat";
import Tooltip from "@/components/base/Tooltip";
import IconComponent from "@/components/base/IconComponent";
import { api } from "@/core/helpers/Api";
import { ProjectCard } from "@/core/models";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { Routing, SocketEvents } from "@langboard/core/constants";
import { ESocketTopic } from "@langboard/core/enums";
import { Utils } from "@langboard/core/utils";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface ColumnEvent {
    uid: string;
    activity_type: "card_created" | "card_moved";
    created_at: string;
    column?: { name?: string };
    recorder?: { type: string; firstname?: string; lastname?: string; name?: string };
}

export default function CardColumnHistory({ card }: { card: ProjectCard.TModel }) {
    const { projectUID, socket } = useBoardCard();
    const columnUID = card.useField("project_column_uid");
    const [events, setEvents] = useState<ColumnEvent[]>([]);
    const [t, i18n] = useTranslation();

    useEffect(() => {
        let controller: AbortController | undefined;
        const url = Utils.String.format(Routing.API.ACTIVITIY.CARD_COLUMN_HISTORY, { uid: projectUID, card_uid: card.uid });
        const refresh = () => {
            controller?.abort();
            const request = new AbortController();
            controller = request;
            void api
                .get<{ records: ColumnEvent[] }>(url, { signal: request.signal, env: { interceptToast: true } as never })
                .then(({ data }) => {
                    if (!request.signal.aborted) setEvents(data.records.filter((event) => event.column?.name));
                })
                .catch(() => {
                    if (!request.signal.aborted) setEvents([]);
                });
        };
        // Column changes can precede the asynchronous activity write. Refresh after its committed event too.
        // The dashboard project loader owns this subscription; only add a listener here.
        const listener = {
            topic: ESocketTopic.Dashboard,
            topicId: projectUID,
            event: SocketEvents.SERVER.DASHBOARD.PROJECT.ACTIVITY_RECORDED.replace("{uid}", projectUID),
            eventKey: `card-column-history-${projectUID}-${card.uid}`,
            callback: refresh,
        };
        socket.on(listener);
        refresh();
        return () => {
            controller?.abort();
            socket.off(listener);
        };
    }, [projectUID, card.uid, columnUID, socket]);

    if (!events.length) return null;

    return (
        <nav aria-label={t("card.Activity")} className="flex min-w-0 flex-wrap items-center gap-x-1 gap-y-0.5 text-[11px] text-muted-foreground/80">
            <IconComponent icon="history" size="3" className="shrink-0 opacity-70" aria-hidden="true" />
            {events.map((event, index) => {
                const date = new Date(event.created_at);
                const exact = formatDateTime(date, i18n.language, { timeStyle: "medium" });
                const actor =
                    event.recorder?.type === "bot"
                        ? event.recorder.name
                        : [event.recorder?.firstname, event.recorder?.lastname].filter(Boolean).join(" ");
                const detail = `${event.column?.name} · ${exact} · ${actor || t("common.Unknown User")}`;
                return (
                    <span key={event.uid} className="inline-flex min-w-0 items-center gap-1">
                        {index > 0 && (
                            <span aria-hidden="true" className="opacity-50">
                                ›
                            </span>
                        )}
                        <Tooltip.Root>
                            <Tooltip.Trigger asChild>
                                <time
                                    dateTime={date.toISOString()}
                                    tabIndex={0}
                                    aria-label={detail}
                                    className="max-w-full truncate rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                >
                                    {event.column?.name}
                                </time>
                            </Tooltip.Trigger>
                            <Tooltip.Content>{detail}</Tooltip.Content>
                        </Tooltip.Root>
                    </span>
                );
            })}
        </nav>
    );
}
