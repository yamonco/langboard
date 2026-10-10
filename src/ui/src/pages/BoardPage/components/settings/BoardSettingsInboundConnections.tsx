import Button from "@/components/base/Button";
import type { CatalogApp } from "@/controllers/api/board/useBoardAppCatalog";
import { useManagedAppOrganizations } from "@/controllers/api/settings/apps/useAppGovernance";
import { api } from "@/core/helpers/Api";
import { useBoardSettings } from "@/core/providers/BoardSettingsProvider";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import BoardSettingsInboundResources from "./BoardSettingsInboundResources";

interface Connection {
    connection_uid: string;
    ownership: string;
    state: string;
    revision: string;
}

export default function BoardSettingsInboundConnections({ app, onBusy }: { app: CatalogApp; onBusy: (busy: boolean) => void }) {
    const [t] = useTranslation();
    const { currentUser, canEditBasicInfo } = useBoardSettings();
    const [resourceConnection, setResourceConnection] = useState<string | null>(null);
    const [resourceBusy, setResourceBusy] = useState(false);
    const [scope, setScope] = useState("");
    const [cursor, setCursor] = useState<string>();
    const [organizationCursor, setOrganizationCursor] = useState<string>();
    const organizations = useManagedAppOrganizations(organizationCursor);
    const [confirm, setConfirm] = useState<"create" | Connection | null>(null);
    const [pending, setPending] = useState(false);
    const [failed, setFailed] = useState(false);
    const writing = useRef(false);
    const path = `/settings/apps/registry/${encodeURIComponent(app.key)}/inbound-connections`;
    const config = { env: { interceptToast: true } as never };
    const list = useQuery({
        queryKey: ["inbound-connections", currentUser?.uid, app.key, scope, cursor],
        queryFn: async ({ signal }) =>
            (
                await api.get<{ items: Connection[]; next_cursor: string | null }>(path, {
                    ...config,
                    signal,
                    params: { organization_uid: scope || undefined, after: cursor },
                })
            ).data,
        enabled: !!currentUser,
        retry: 0,
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
    });
    const busy = pending || list.isFetching;
    useEffect(() => {
        onBusy(pending || resourceBusy);
        return () => onBusy(false);
    }, [pending, resourceBusy, onBusy]);
    const refresh = async () => {
        const result = await list.refetch();
        if (!result.error) {
            setFailed(false);
            setConfirm(null);
        }
    };
    const submit = async () => {
        if (!confirm || busy || failed || list.isError || writing.current) return;
        writing.current = true;
        setPending(true);
        try {
            if (confirm === "create") {
                if (!app.app_revision || app.is_available === false) return;
                await api.post(path, { app_revision: app.app_revision, organization_uid: scope || null }, config);
            } else {
                await api.post(
                    `/settings/apps/inbound-connections/${confirm.connection_uid}/disconnect`,
                    { expected_revision: confirm.revision },
                    config
                );
            }
            setConfirm(null);
            const result = await list.refetch();
            setFailed(!!result.error);
        } catch {
            setFailed(true);
        } finally {
            writing.current = false;
            setPending(false);
        }
    };
    if (resourceConnection)
        return (
            <>
                <Button size="sm" variant="outline" disabled={resourceBusy} onClick={() => setResourceConnection(null)}>
                    {t("common.Close")}
                </Button>
                <BoardSettingsInboundResources key={resourceConnection} app={app} connectionUID={resourceConnection} onBusy={setResourceBusy} />
            </>
        );
    return (
        <section className="space-y-4 rounded-lg border p-4" aria-busy={busy}>
            <h3 className="text-base font-semibold">
                {app.name} · {t("project.settings.Manage inbound connections")}
            </h3>
            <p className="text-sm text-muted-foreground">{t("project.settings.Inbound connection help")}</p>
            <label className="block space-y-1 text-sm">
                <span>{t("project.settings.Connection ownership")}</span>
                <select
                    className="h-10 w-full rounded-md border bg-background px-3"
                    value={scope}
                    disabled={pending || failed || !!confirm}
                    onChange={(event) => {
                        setScope(event.target.value);
                        setCursor(undefined);
                    }}
                >
                    <option value="">{t("project.settings.Personal connection")}</option>
                    {scope && !organizations.data?.items.some((item) => item.uid === scope) && (
                        <option value={scope}>{t("settings.App selected organization")}</option>
                    )}
                    {organizations.data?.items.map((item) => (
                        <option key={item.uid} value={item.uid}>
                            {item.name}
                        </option>
                    ))}
                </select>
            </label>
            {organizations.isError && (
                <Button variant="ghost" size="sm" onClick={() => void organizations.refetch()}>
                    {t("settings.App more organizations")}
                </Button>
            )}
            {organizations.data?.next_cursor && (
                <Button variant="ghost" size="sm" disabled={pending} onClick={() => setOrganizationCursor(organizations.data!.next_cursor!)}>
                    {t("settings.App more organizations")}
                </Button>
            )}
            {organizationCursor && (
                <Button variant="ghost" size="sm" disabled={pending} onClick={() => setOrganizationCursor(undefined)}>
                    {t("settings.App first organizations")}
                </Button>
            )}
            {(failed || list.isError) && (
                <p role="alert" className="text-sm">
                    {t("project.settings.Inbound connection refresh required")}
                </p>
            )}
            <Button variant="outline" size="sm" disabled={busy} onClick={() => void refresh()}>
                {t("common.Retry")}
            </Button>
            {list.isFetching && <p role="status">{t("common.Loading...")}</p>}
            {!list.isFetching && !list.isError && list.data?.items.length === 0 && <p>{t("project.settings.No inbound connections")}</p>}
            <ul className="space-y-2">
                {list.data?.items.map((connection) => (
                    <li key={connection.connection_uid} className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3 text-sm">
                        <span className="min-w-0 break-all">
                            {connection.connection_uid} · {t(`project.settings.App resource state ${connection.state}`)}
                        </span>
                        <Button
                            size="sm"
                            variant="outline"
                            disabled={!canEditBasicInfo || !app.binding || busy || failed || list.isError || !!confirm}
                            onClick={() => setResourceConnection(connection.connection_uid)}
                        >
                            {t("project.settings.Manage service resources")}
                        </Button>
                        <Button
                            variant="outline"
                            size="sm"
                            disabled={busy || failed || list.isError || !!confirm || connection.state === "disconnected"}
                            onClick={() => setConfirm(connection)}
                        >
                            {t("project.settings.Disconnect inbound connection")}
                        </Button>
                    </li>
                ))}
            </ul>
            <div className="flex flex-wrap gap-2">
                {list.data?.next_cursor && (
                    <Button variant="ghost" size="sm" disabled={busy || !!confirm || failed} onClick={() => setCursor(list.data!.next_cursor!)}>
                        {t("project.settings.More inbound connections")}
                    </Button>
                )}
                {cursor && (
                    <Button variant="ghost" size="sm" disabled={busy || !!confirm || failed} onClick={() => setCursor(undefined)}>
                        {t("project.settings.First inbound connections")}
                    </Button>
                )}
                <Button
                    size="sm"
                    disabled={busy || failed || list.isError || !!confirm || !app.app_revision || app.is_available === false}
                    onClick={() => setConfirm("create")}
                >
                    {t("project.settings.Create inbound connection")}
                </Button>
            </div>
            {confirm && (
                <div className="space-y-2 rounded-md border p-3">
                    <p className="text-sm">
                        {t(confirm === "create" ? "project.settings.Inbound connection help" : "project.settings.Inbound disconnect help")}
                    </p>
                    <div className="flex gap-2">
                        <Button size="sm" disabled={busy || failed || list.isError} onClick={() => void submit()}>
                            {t("project.settings.Confirm inbound change")}
                        </Button>
                        <Button size="sm" variant="ghost" disabled={pending} onClick={() => setConfirm(null)}>
                            {t("common.Cancel")}
                        </Button>
                    </div>
                </div>
            )}
        </section>
    );
}
