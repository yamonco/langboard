import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router";
import { useTranslation } from "react-i18next";
import { api } from "@/core/helpers/Api";
import Button from "@/components/base/Button";

interface HistoryItem {
    uid: string;
    created_at: string;
    actor_uid: string;
    action: string;
    revision_before: number | null;
    revision_after: number;
    source_kind: string;
    request_id?: string | null;
    reason_code?: string | null;
}
export default function SecretHistoryPage() {
    const { referenceUID } = useParams();
    const [t] = useTranslation();
    const [items, setItems] = useState<HistoryItem[]>([]);
    const [cursor, setCursor] = useState<string | null>(null);
    const [busy, setBusy] = useState(true);
    const [failed, setFailed] = useState(false);
    const currentURL = useRef("");
    const url = `/secret-references/${referenceUID}/history`;
    currentURL.current = url;
    useEffect(() => {
        let active = true;
        setItems([]);
        setBusy(true);
        setFailed(false);
        setCursor(null);
        api.get(url)
            .then(({ data }) => {
                if (active) {
                    setItems(data.items);
                    setCursor(data.next_cursor);
                }
            })
            .catch(() => {
                if (active) setFailed(true);
            })
            .finally(() => {
                if (active) setBusy(false);
            });
        return () => {
            active = false;
        };
    }, [url]);
    return (
        <main className="mx-auto w-full max-w-2xl px-4 py-10 sm:py-16">
            <section className="card card-border rounded-xl border bg-background">
                <div className="card-body flex flex-col gap-4 p-5 sm:p-6">
                    <h1 className="card-title text-lg font-semibold">{t("myAccount.secretHistory.title")}</h1>
                    <p className="text-sm text-muted-foreground">{t("myAccount.secretHistory.help")}</p>
                    {failed ? (
                        <p role="alert">{t("myAccount.secretHistory.failed")}</p>
                    ) : (
                        <>
                            <ol className="flex flex-col divide-y">
                                {items.map((item) => (
                                    <li key={item.uid} className="flex flex-col gap-1 py-3 text-sm">
                                        <div className="flex flex-wrap items-center justify-between gap-2">
                                            <strong>{t(`myAccount.secretHistory.actions.${item.action}`, { defaultValue: item.action })}</strong>
                                            <time className="text-xs text-muted-foreground" dateTime={item.created_at}>
                                                {new Date(item.created_at).toLocaleString()}
                                            </time>
                                        </div>
                                        <p className="break-all text-xs text-muted-foreground">
                                            {t("myAccount.secretHistory.actor")} {item.actor_uid} · {item.source_kind}
                                            {" · "}
                                            {item.revision_before === null
                                                ? `v${item.revision_after}`
                                                : `v${item.revision_before} → v${item.revision_after}`}
                                        </p>
                                        {item.reason_code && (
                                            <p className="text-xs text-muted-foreground" title={item.request_id ?? undefined}>
                                                {t(`myAccount.secretHistory.reasons.${item.reason_code}`, { defaultValue: item.reason_code })}
                                            </p>
                                        )}
                                    </li>
                                ))}
                            </ol>
                            {!busy && !items.length && <p>{t("myAccount.secretHistory.empty")}</p>}
                            {busy && <p role="status">{t("common.Loading...")}</p>}
                            {cursor && (
                                <Button
                                    disabled={busy}
                                    onClick={async () => {
                                        setBusy(true);
                                        try {
                                            const { data } = await api.get(url, { params: { cursor } });
                                            if (currentURL.current !== url) return;
                                            setItems((previous) => [...previous, ...data.items]);
                                            setCursor(data.next_cursor);
                                        } catch {
                                            setItems([]);
                                            setCursor(null);
                                            setFailed(true);
                                        } finally {
                                            setBusy(false);
                                        }
                                    }}
                                >
                                    {t("myAccount.secretHistory.older")}
                                </Button>
                            )}
                        </>
                    )}
                </div>
            </section>
        </main>
    );
}
