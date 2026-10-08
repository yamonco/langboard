import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Button from "@/components/base/Button";
import { api } from "@/core/helpers/Api";

interface Evidence {
    binding_uid: string;
    revision: number;
    state: string;
    commit_sha: string;
    external_id: string;
    resource_uid: string;
    occurred_at: string | null;
}
interface Snapshot {
    items: Evidence[];
    bindings: { binding_uid: string; revision: number }[];
    source_change_seq: number;
}
interface Resource {
    uid: string;
    connection_uid: string;
    name: string;
}
interface Signal {
    signal_uid: string;
    external_id: string;
    commit_sha: string;
    outcome: string;
}

export default function CardSignalEvidence({
    projectUID,
    cardUID,
    canEdit,
    onChanged,
}: {
    projectUID: string;
    cardUID: string;
    canEdit: boolean;
    onChanged?: () => void;
}) {
    const [t] = useTranslation();
    const text = (key: string) => t(`card.signals.${key}`);
    const root = `/board/${projectUID}/card/${cardUID}/signals`;
    const [open, setOpen] = useState(false);
    const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
    const [resourcesLoaded, setResourcesLoaded] = useState(false);
    const [resources, setResources] = useState<Resource[]>([]);
    const [resourceCursor, setResourceCursor] = useState<string | null>(null);
    const [resourceUID, setResourceUID] = useState("");
    const [signals, setSignals] = useState<Signal[]>([]);
    const [cursor, setCursor] = useState<string | null>(null);
    const [pending, setPending] = useState(false);
    const [error, setError] = useState(false);
    const controller = useRef<AbortController | null>(null);
    const generation = useRef(0);
    const resource = resources.find((row) => row.uid === resourceUID);
    useEffect(() => {
        generation.current++;
        controller.current?.abort();
        setSnapshot(null);
        setResources([]);
        setResourcesLoaded(false);
        setResourceCursor(null);
        setSignals([]);
        setResourceUID("");
        setCursor(null);
        setError(false);
        setPending(false);
        setOpen(false);
        return () => {
            generation.current++;
            controller.current?.abort();
        };
    }, [root]);
    const run = async (action: (signal: AbortSignal) => Promise<void>) => {
        controller.current?.abort();
        const request = new AbortController();
        controller.current = request;
        const current = ++generation.current;
        setPending(true);
        setError(false);
        try {
            await action(request.signal);
        } catch {
            if (!request.signal.aborted && current === generation.current) {
                setError(true);
                setSnapshot(null);
                setSignals([]);
                setResources([]);
                setResourceUID("");
                setResourceCursor(null);
                setCursor(null);
            }
        } finally {
            if (current === generation.current) setPending(false);
        }
    };
    const load = async (signal: AbortSignal) => {
        const result = await api.get<Snapshot>(root, { signal });
        if (!signal.aborted) setSnapshot(result.data);
    };
    const show = () => {
        setOpen(!open);
        if (!open) void run(load);
    };
    const choose = (uid: string) => {
        setResourceUID(uid);
        setSignals([]);
        setCursor(null);
        const selected = resources.find((row) => row.uid === uid);
        if (selected)
            void run(async (signal) => {
                const result = await api.get<{ items: Signal[]; next_cursor: string | null }>(
                    `/board/${projectUID}/settings/apps/github/connections/${selected.connection_uid}/resources/${uid}/signals`,
                    { signal }
                );
                if (!signal.aborted) {
                    setSignals(result.data.items);
                    setCursor(result.data.next_cursor);
                }
            });
    };
    const bind = (item: Signal) =>
        void run(async (signal) => {
            if (!resource || !snapshot) return;
            const previous = snapshot.items.find(
                (row) => row.resource_uid === resource.uid && row.external_id === item.external_id && row.commit_sha === item.commit_sha
            );
            await api.post(
                root,
                {
                    connection_uid: resource.connection_uid,
                    resource_uid: resource.uid,
                    signal_uid: item.signal_uid,
                    source_change_seq: snapshot.source_change_seq,
                    expected_revision: previous?.revision ?? null,
                },
                { signal }
            );
            if (!signal.aborted) {
                await load(signal);
                onChanged?.();
            }
        });
    return (
        <section className="min-w-0 rounded-lg border border-border p-3" aria-label={text("title")}>
            <Button type="button" variant="ghost" size="sm" className="btn btn-ghost w-full justify-between" aria-expanded={open} onClick={show}>
                {text("title")}
                <span aria-hidden="true">{open ? "−" : "+"}</span>
            </Button>
            {open && (
                <div className="mt-2 space-y-3 text-sm">
                    <p className="text-xs text-muted-foreground">{text("hint")}</p>
                    {error && <p role="alert">{text("error")}</p>}
                    {pending && <p role="status">{text("loading")}</p>}
                    <Button type="button" variant="outline" size="sm" disabled={pending} onClick={() => void run(load)}>
                        {text("refresh")}
                    </Button>
                    {snapshot && !snapshot.bindings.length && <p className="text-muted-foreground">{text("empty")}</p>}
                    {snapshot?.bindings.map((binding) => {
                        const proof = snapshot.items.find((row) => row.binding_uid === binding.binding_uid);
                        return (
                            <div key={binding.binding_uid} className="flex min-w-0 flex-wrap items-center gap-2 rounded-md bg-muted/40 p-2">
                                <span className="min-w-0 flex-1 break-all">
                                    {proof ? `${text(proof.state)} · #${proof.external_id} · ${proof.commit_sha.slice(0, 12)}` : text("unavailable")}
                                </span>
                                {canEdit && (
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="ghost"
                                        disabled={pending}
                                        onClick={() =>
                                            void run(async (signal) => {
                                                await api.post(
                                                    `${root}/${binding.binding_uid}/unlink`,
                                                    { expected_revision: binding.revision },
                                                    { signal }
                                                );
                                                if (!signal.aborted) {
                                                    await load(signal);
                                                    onChanged?.();
                                                }
                                            })
                                        }
                                    >
                                        {text("unlink")}
                                    </Button>
                                )}
                            </div>
                        );
                    })}
                    {canEdit && snapshot && (
                        <>
                            <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                disabled={pending}
                                onClick={() =>
                                    void run(async (signal) => {
                                        const result = await api.get<{ items: Resource[]; next_cursor: string | null }>(`${root}/resources`, {
                                            signal,
                                        });
                                        if (!signal.aborted) {
                                            setResources(result.data.items);
                                            setResourcesLoaded(true);
                                            setResourceCursor(result.data.next_cursor);
                                        }
                                    })
                                }
                            >
                                {text("link")}
                            </Button>
                            {resourcesLoaded && !resources.length && !resourceCursor && <p>{text("noResources")}</p>}
                            {resources.length > 0 && (
                                <select
                                    aria-label={text("repository")}
                                    className="w-full rounded-md border border-input bg-background p-2"
                                    value={resourceUID}
                                    disabled={pending}
                                    onChange={(event) => choose(event.target.value)}
                                >
                                    <option value="">{text("repository")}</option>
                                    {resources.map((row) => (
                                        <option key={row.uid} value={row.uid}>
                                            {row.name}
                                        </option>
                                    ))}
                                </select>
                            )}
                            {resourceCursor && (
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    disabled={pending}
                                    onClick={() =>
                                        void run(async (signal) => {
                                            const result = await api.get<{ items: Resource[]; next_cursor: string | null }>(`${root}/resources`, {
                                                signal,
                                                params: { after: resourceCursor },
                                            });
                                            if (!signal.aborted) {
                                                setResources((old) => [...old, ...result.data.items]);
                                                setResourceCursor(result.data.next_cursor);
                                            }
                                        })
                                    }
                                >
                                    {text("moreResources")}
                                </Button>
                            )}
                            {signals.map((item) => (
                                <Button
                                    key={item.signal_uid}
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    className="btn btn-outline h-auto min-h-9 w-full justify-start whitespace-normal break-all py-2 text-left"
                                    disabled={pending}
                                    onClick={() => bind(item)}
                                >
                                    #{item.external_id} · {item.commit_sha.slice(0, 12)} · {item.outcome}
                                </Button>
                            ))}
                            {cursor && resource && (
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    disabled={pending}
                                    onClick={() =>
                                        void run(async (signal) => {
                                            const result = await api.get<{ items: Signal[]; next_cursor: string | null }>(
                                                `/board/${projectUID}/settings/apps/github/connections/${resource.connection_uid}/resources/${resource.uid}/signals`,
                                                { signal, params: { after: cursor } }
                                            );
                                            if (!signal.aborted) {
                                                setSignals((old) => [...old, ...result.data.items]);
                                                setCursor(result.data.next_cursor);
                                            }
                                        })
                                    }
                                >
                                    {text("more")}
                                </Button>
                            )}
                        </>
                    )}
                </div>
            )}
        </section>
    );
}
