import Button from "@/components/base/Button";
import { api } from "@/core/helpers/Api";
import { useBoardSettings } from "@/core/providers/BoardSettingsProvider";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

interface Credential {
    credential_uid: string;
    expires_at: string;
    revoked_at: string | null;
}
export default function BoardSettingsInboundCredentials({
    connectionUID,
    canIssue,
    onBusy,
}: {
    connectionUID: string;
    canIssue: boolean;
    onBusy: (busy: boolean) => void;
}) {
    const [t, i18n] = useTranslation();
    const { currentUser } = useBoardSettings();
    const [cursor, setCursor] = useState<string>();
    const [confirm, setConfirm] = useState<"issue" | Credential | null>(null);
    const [pending, setPending] = useState(false);
    const [failed, setFailed] = useState(false);
    const [token, setToken] = useState("");
    const writing = useRef(false);
    const path = `/settings/apps/connections/${connectionUID}/credentials`;
    const config = { env: { interceptToast: true } as never };
    const list = useQuery({
        queryKey: ["connection-credentials", currentUser?.uid, connectionUID, cursor],
        queryFn: async ({ signal }) =>
            (await api.get<{ items: Credential[]; next_cursor: string | null }>(path, { ...config, signal, params: { after: cursor } })).data,
        retry: 0,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
    });
    const busy = pending || list.isFetching;
    useEffect(() => {
        onBusy(pending);
        return () => onBusy(false);
    }, [pending, onBusy]);
    useEffect(() => {
        setToken("");
        setConfirm(null);
    }, [currentUser?.uid, connectionUID]);
    const refresh = async () => {
        setPending(true);
        setToken("");
        try {
            const result = await list.refetch();
            setFailed(result.isError);
            if (!result.isError) setConfirm(null);
        } catch {
            setFailed(true);
        } finally {
            setPending(false);
        }
    };
    const save = async () => {
        if (!confirm || busy || failed || list.isError || writing.current || (confirm === "issue" && !canIssue)) return;
        writing.current = true;
        setPending(true);
        setToken("");
        try {
            if (confirm === "issue") {
                // One-shot transport prevents automatic auth replay of credential issuance.
                const response = await api.post<{ token: string }>(path, { expires_in_seconds: 3600 }, { env: { secretInput: true } as never });
                setToken(response.data.token);
            } else await api.post(`${path}/${confirm.credential_uid}/revoke`, {}, config);
            setConfirm(null);
            const result = await list.refetch();
            setFailed(result.isError);
        } catch {
            setFailed(true);
        } finally {
            writing.current = false;
            setPending(false);
        }
    };
    return (
        <section className="space-y-3 rounded-lg border p-4" aria-busy={busy}>
            <h4 className="font-semibold">{t("project.settings.Manage service credentials")}</h4>
            <p className="text-sm text-muted-foreground">{t("project.settings.Service credential help")}</p>
            {(failed || list.isError) && <p role="alert">{t("project.settings.Inbound connection refresh required")}</p>}
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void refresh()}>
                {t("common.Retry")}
            </Button>
            {token && (
                <div className="space-y-2 rounded-md border p-3">
                    <p className="text-sm">{t("project.settings.Service credential once")}</p>
                    <input
                        aria-label={t("project.settings.Service credential value")}
                        className="h-10 w-full rounded-md border bg-background px-3 font-mono text-xs"
                        readOnly
                        value={token}
                        autoComplete="off"
                        spellCheck={false}
                    />
                    <Button size="sm" variant="outline" onClick={() => setToken("")}>
                        {t("project.settings.Hide service credential")}
                    </Button>
                </div>
            )}
            <ul className="space-y-2">
                {list.data?.items.map((credential) => (
                    <li key={credential.credential_uid} className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3 text-sm">
                        <span className="min-w-0 break-all">
                            {credential.credential_uid} ·{" "}
                            {new Date(credential.expires_at).toLocaleString(i18n.resolvedLanguage, {
                                month: "short",
                                day: "numeric",
                                hour: "2-digit",
                                minute: "2-digit",
                            })}
                        </span>
                        <Button
                            size="sm"
                            variant="outline"
                            disabled={busy || failed || list.isError || !!confirm || !!credential.revoked_at}
                            onClick={() => setConfirm(credential)}
                        >
                            {t("project.settings.Revoke service credential")}
                        </Button>
                    </li>
                ))}
            </ul>
            <Button size="sm" disabled={!canIssue || busy || failed || list.isError || !!confirm || !!token} onClick={() => setConfirm("issue")}>
                {t("project.settings.Issue service credential")}
            </Button>
            {confirm && (
                <div className="space-y-2 rounded-md border p-3">
                    <p className="text-sm">
                        {t(confirm === "issue" ? "project.settings.Service credential help" : "project.settings.Revoke service credential")}
                    </p>
                    <div className="flex gap-2">
                        <Button size="sm" disabled={busy || failed || list.isError} onClick={() => void save()}>
                            {t("project.settings.Confirm inbound change")}
                        </Button>
                        <Button size="sm" variant="ghost" disabled={pending} onClick={() => setConfirm(null)}>
                            {t("common.Cancel")}
                        </Button>
                    </div>
                </div>
            )}
            <div className="flex gap-2">
                {list.data?.next_cursor && (
                    <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy || failed || !!confirm}
                        onClick={() => {
                            setToken("");
                            setCursor(list.data!.next_cursor!);
                        }}
                    >
                        {t("project.settings.More inbound connections")}
                    </Button>
                )}
                {cursor && (
                    <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy || failed || !!confirm}
                        onClick={() => {
                            setToken("");
                            setCursor(undefined);
                        }}
                    >
                        {t("project.settings.First inbound connections")}
                    </Button>
                )}
            </div>
        </section>
    );
}
