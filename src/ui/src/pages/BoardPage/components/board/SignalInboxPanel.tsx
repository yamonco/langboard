import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Button from "@/components/base/Button";
import { api } from "@/core/helpers/Api";
import type { ISocketContext } from "@/core/providers/SocketProvider";
import { formatDateDistance, formatDateTime } from "@/core/utils/LocaleFormat";
import { ESocketTopic } from "@langboard/core/enums";

interface Signal {
    signal_uid: string;
    provider: string;
    event_type: string;
    can_bind_card: boolean;
    connection_uid: string;
    resource_uid: string;
    resource_name?: string;
    resource_type?: string;
    external_id: string;
    commit_sha: string;
    outcome: string | null;
    conflict: boolean;
    occurred_at: string;
    time_basis?: string;
}
export default function SignalInboxPanel({
    projectUID,
    cards,
    canEdit,
    socket,
    onLinked,
    columns = [],
    onCreated,
}: {
    projectUID: string;
    cards: { uid: string; title: string }[];
    canEdit: boolean;
    socket: Pick<ISocketContext, "on" | "off">;
    onLinked?: (cardUID: string) => void;
    columns?: { uid: string; name: string; is_archive?: boolean }[];
    onCreated?: (cardUID: string) => void;
}) {
    const [t, i18n] = useTranslation();
    const text = (key: string) => t(`card.inbox.${key}`);
    const [items, setItems] = useState<Signal[]>([]);
    const [cursor, setCursor] = useState<string | null>(null);
    const [selected, setSelected] = useState<Signal | null>(null);
    const [cardUID, setCardUID] = useState("");
    const [creating, setCreating] = useState(false);
    const [columnUID, setColumnUID] = useState("");
    const [title, setTitle] = useState("");
    const [receipt, setReceipt] = useState<{ card_uid: string; created: boolean } | null>(null);
    const availableColumns = columns.filter((column) => !column.is_archive);
    const [pending, setPending] = useState(false);
    const [error, setError] = useState(false);
    const [refresh, setRefresh] = useState(0);
    const controller = useRef<AbortController | null>(null);
    const generation = useRef(0);
    const completedRefresh = useRef(0);
    const root = `/board/${projectUID}/signals/inbox`;
    const run = async (action: (signal: AbortSignal) => Promise<void>) => {
        const request = new AbortController();
        controller.current?.abort();
        controller.current = request;
        const current = ++generation.current;
        setPending(true);
        setError(false);
        try {
            await action(request.signal);
        } catch {
            if (!request.signal.aborted && generation.current === current) {
                setItems([]);
                setCursor(null);
                setSelected(null);
                setCreating(false);
                setReceipt(null);
                setError(true);
            }
        } finally {
            if (generation.current === current) setPending(false);
        }
    };
    const load = async (signal: AbortSignal, after?: string) => {
        const response = await api.get<{ items: Signal[]; next_cursor: string | null }>(root, { signal, params: after ? { after } : undefined });
        if (signal.aborted) return;
        setItems((value) => (after ? [...value, ...response.data.items] : response.data.items));
        setCursor(response.data.next_cursor);
    };
    useEffect(() => {
        setItems([]);
        setCursor(null);
        setSelected(null);
        setCardUID("");
        setCreating(false);
        setColumnUID("");
        setTitle("");
        setReceipt(null);
        completedRefresh.current = refresh;
        void run((signal) => load(signal));
        let timer: ReturnType<typeof setTimeout> | undefined;
        const schedule = () => {
            if (!timer)
                timer = setTimeout(() => {
                    timer = undefined;
                    setRefresh((value) => value + 1);
                }, 150);
        };
        const changed = {
            topic: ESocketTopic.Board as const,
            topicId: projectUID,
            event: "board:app-signal:changed",
            eventKey: `signal-inbox-${projectUID}`,
            callback: (data: unknown) => {
                if (data && typeof data === "object" && "app_signal_changed" in data && data.app_signal_changed === true) schedule();
            },
        };
        const reconnect = { event: "open" as const, eventKey: `signal-inbox-reconnect-${projectUID}`, callback: schedule };
        const focused = () => {
            if (document.visibilityState === "visible") schedule();
        };
        socket.on(changed);
        socket.on(reconnect);
        window.addEventListener("focus", focused);
        return () => {
            generation.current++;
            controller.current?.abort();
            if (timer) clearTimeout(timer);
            socket.off(changed);
            socket.off(reconnect);
            window.removeEventListener("focus", focused);
        };
    }, [root, socket, canEdit]);
    useEffect(() => {
        if (pending || refresh === completedRefresh.current) return;
        completedRefresh.current = refresh;
        setSelected(null);
        void run((signal) => load(signal));
    }, [pending, refresh]);
    const canBindCard = (item: Signal) => ["github", "dokploy", "glitchtip"].includes(item.provider) && item.can_bind_card === true;
    const link = () => {
        if (!canEdit || !selected || !canBindCard(selected) || !cardUID || !cards.some((card) => card.uid === cardUID)) return;
        const chosen = selected;
        void run(async (signal) => {
            const cardRoot = `/board/${projectUID}/card/${cardUID}/signals`;
            const response = await api.get<{
                source_change_seq: number;
                items: { binding_uid: string; resource_uid: string; external_id: string; commit_sha: string }[];
                bindings: { binding_uid: string; revision: number }[];
            }>(cardRoot, { signal });
            if (signal.aborted) return;
            const proof = response.data.items.find(
                (item) =>
                    item.resource_uid === chosen.resource_uid && item.external_id === chosen.external_id && item.commit_sha === chosen.commit_sha
            );
            const previous = response.data.bindings.find((binding) => binding.binding_uid === proof?.binding_uid);
            await api.post(
                cardRoot,
                {
                    connection_uid: chosen.connection_uid,
                    resource_uid: chosen.resource_uid,
                    signal_uid: chosen.signal_uid,
                    source_change_seq: response.data.source_change_seq,
                    expected_revision: previous?.revision ?? null,
                },
                { signal }
            );
            if (signal.aborted) return;
            setSelected(null);
            await load(signal);
            if (!signal.aborted) onLinked?.(cardUID);
        });
    };
    const createCard = () => {
        const trimmedTitle = title.trim();
        if (
            pending ||
            !canEdit ||
            !creating ||
            !selected ||
            !canBindCard(selected) ||
            !availableColumns.some((column) => column.uid === columnUID) ||
            !trimmedTitle ||
            trimmedTitle.length > 200
        )
            return;
        const chosen = selected;
        void run(async (signal) => {
            setReceipt(null);
            const response = await api.post<{ card_uid: string; created: boolean }>(
                `${root}/card`,
                {
                    connection_uid: chosen.connection_uid,
                    resource_uid: chosen.resource_uid,
                    signal_uid: chosen.signal_uid,
                    project_column_uid: columnUID,
                    title: trimmedTitle,
                },
                { signal }
            );
            if (signal.aborted) return;
            setSelected(null);
            setCreating(false);
            await load(signal);
            if (signal.aborted) return;
            setReceipt(response.data);
            onCreated?.(response.data.card_uid);
        });
    };
    return (
        <section className="h-full overflow-y-auto p-3" aria-label={text("title")}>
            <h2 className="mb-3 flex items-center justify-between gap-2 text-sm font-semibold">
                {text("title")}
                <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={pending}
                    onClick={() => {
                        setSelected(null);
                        void run((signal) => load(signal));
                    }}
                >
                    {text("refresh")}
                </Button>
            </h2>
            <p className="mb-3 text-xs text-muted-foreground">{text("hint")}</p>
            {pending && <p role="status">{text("loading")}</p>}
            {error && <p role="alert">{text("error")}</p>}
            {receipt && <p role="status">{text(receipt.created ? "created" : "reused")}</p>}
            {!pending && !error && !items.length && <p className="text-sm text-muted-foreground">{text("empty")}</p>}
            <div className="space-y-2">
                {items.map((item) => {
                    const content = (
                        <>
                            <span className="badge badge-outline">
                                {item.conflict
                                    ? text("conflict")
                                    : item.provider === "glitchtip"
                                      ? text(["unresolved", "resolved", "ignored"].includes(item.outcome ?? "") ? `outcome ${item.outcome}` : "other")
                                      : item.provider === "dokploy"
                                        ? text(
                                              ["success", "failure", "running", "queued", "cancelled"].includes(item.outcome ?? "")
                                                  ? `outcome ${item.outcome}`
                                                  : "other"
                                          )
                                        : text(
                                              item.outcome === "success"
                                                  ? "passed"
                                                  : item.outcome === "failure" || item.outcome === "timed_out"
                                                    ? "failed"
                                                    : "other"
                                          )}
                            </span>
                            <span className="break-all text-xs">
                                {item.provider === "github"
                                    ? `GitHub · #${item.external_id} · ${item.commit_sha.slice(0, 12)}`
                                    : item.provider === "dokploy"
                                      ? `Dokploy · ${text(["deployment.started", "deployment.queued", "deployment.succeeded", "deployment.failed", "deployment.cancelled"].includes(item.event_type) ? `event ${item.event_type}` : "event deployment")}`
                                      : item.provider === "glitchtip"
                                        ? `GlitchTip · ${text("issue")} ${item.external_id} · ${text("event issue.status_observed")}`
                                        : text("other")}
                            </span>
                            {["dokploy", "glitchtip"].includes(item.provider) && item.resource_name && (
                                <span className="break-words text-xs">{item.resource_name}</span>
                            )}
                            <time
                                className="text-xs text-muted-foreground"
                                dateTime={item.occurred_at}
                                title={formatDateTime(new Date(item.occurred_at), i18n.language, { timeStyle: "medium" })}
                            >
                                {item.time_basis === "observation" && `${text("observation")} · `}
                                {formatDateDistance(new Date(item.occurred_at), i18n.language)}
                            </time>
                        </>
                    );
                    return canBindCard(item) ? (
                        <Button
                            key={item.signal_uid}
                            type="button"
                            variant="outline"
                            className="h-auto w-full min-w-0 flex-wrap justify-start gap-2 p-3 text-left"
                            disabled={pending || !canEdit}
                            onClick={() => {
                                setSelected(item);
                                setCardUID("");
                                setCreating(false);
                                setColumnUID("");
                                setReceipt(null);
                                setTitle(
                                    [
                                        item.provider === "github" ? "GitHub" : item.provider === "glitchtip" ? "GlitchTip" : "Dokploy",
                                        item.resource_name,
                                        item.provider === "github"
                                            ? text("check")
                                            : item.provider === "glitchtip"
                                              ? `${text("issue")} ${item.external_id} · ${text(["unresolved", "resolved", "ignored"].includes(item.outcome ?? "") ? `outcome ${item.outcome}` : "other")}`
                                              : text(
                                                    [
                                                        "deployment.started",
                                                        "deployment.queued",
                                                        "deployment.succeeded",
                                                        "deployment.failed",
                                                        "deployment.cancelled",
                                                    ].includes(item.event_type)
                                                        ? `event ${item.event_type}`
                                                        : "event deployment"
                                                ),
                                    ]
                                        .filter(Boolean)
                                        .join(" · ")
                                        .slice(0, 200)
                                );
                            }}
                            aria-pressed={selected?.signal_uid === item.signal_uid}
                        >
                            {content}
                        </Button>
                    ) : (
                        <div key={item.signal_uid} className="flex min-w-0 flex-wrap items-center gap-2 rounded-md border p-3">
                            {content}
                        </div>
                    );
                })}
            </div>
            {cursor && (
                <Button type="button" variant="ghost" disabled={pending} onClick={() => void run((signal) => load(signal, cursor))}>
                    {text("more")}
                </Button>
            )}
            {selected && canEdit && canBindCard(selected) && (
                <div className="mt-4 space-y-2 rounded-lg border p-3">
                    {!creating ? (
                        <>
                            <label className="block text-sm" htmlFor={`inbox-card-${projectUID}`}>
                                {text("card")}
                            </label>
                            <select
                                id={`inbox-card-${projectUID}`}
                                className="select select-bordered w-full min-w-0 bg-background text-sm"
                                value={cardUID}
                                disabled={pending}
                                onChange={(event) => setCardUID(event.target.value)}
                            >
                                <option value="">{text("choose")}</option>
                                {cards.map((card) => (
                                    <option key={card.uid} value={card.uid}>
                                        {card.title}
                                    </option>
                                ))}
                            </select>
                            <Button type="button" disabled={pending || !cardUID} onClick={link}>
                                {text("link")}
                            </Button>
                            <Button type="button" variant="outline" disabled={pending || !availableColumns.length} onClick={() => setCreating(true)}>
                                {text("new card")}
                            </Button>
                        </>
                    ) : (
                        <>
                            <label className="block text-sm" htmlFor={`inbox-title-${projectUID}`}>
                                {text("new title")}
                            </label>
                            <input
                                id={`inbox-title-${projectUID}`}
                                className="input w-full min-w-0 rounded-md border bg-background p-2"
                                value={title}
                                maxLength={200}
                                disabled={pending}
                                onChange={(event) => setTitle(event.target.value)}
                            />
                            <label className="block text-sm" htmlFor={`inbox-column-${projectUID}`}>
                                {text("column")}
                            </label>
                            <select
                                id={`inbox-column-${projectUID}`}
                                className="select w-full min-w-0 rounded-md border bg-background p-2"
                                value={columnUID}
                                disabled={pending}
                                onChange={(event) => setColumnUID(event.target.value)}
                            >
                                <option value="">{text("choose column")}</option>
                                {availableColumns.map((column) => (
                                    <option key={column.uid} value={column.uid}>
                                        {column.name}
                                    </option>
                                ))}
                            </select>
                            <Button
                                type="button"
                                disabled={
                                    pending ||
                                    !title.trim() ||
                                    title.trim().length > 200 ||
                                    !availableColumns.some((column) => column.uid === columnUID)
                                }
                                onClick={createCard}
                            >
                                {text("create card")}
                            </Button>
                            <Button type="button" variant="ghost" disabled={pending} onClick={() => setCreating(false)}>
                                {t("common.Cancel")}
                            </Button>
                        </>
                    )}
                </div>
            )}
        </section>
    );
}
