import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/core/helpers/Api";
import { useBoardSettings } from "@/core/providers/BoardSettingsProvider";
import Button from "@/components/base/Button";
import { formatDateDistance, formatDateTime } from "@/core/utils/LocaleFormat";

interface Connection {
    connection_uid: string;
    instance_url: string;
    revision: string;
}
interface Resource {
    id: string;
    slug?: string;
    type?: "project" | "environment" | "application" | "compose";
    name: string;
}
interface Binding {
    resource_uid: string;
    project_id?: string;
    external_id?: string;
    type?: string;
    access_revision: number;
    access_state?: string;
    selected: boolean;
    path: { type: string; id: string; slug?: string; name?: string }[];
}
interface ReadAccess {
    uid?: string;
    revision: string;
    state: string;
    granted_capabilities: string[];
}
interface DeploymentResult {
    resource_uid: string;
    items: { event_type: string; outcome: string; occurred_at: string }[];
    truncated: boolean;
}
interface IssueResult {
    resource_uid: string;
    accepted_count: number;
    next_cursor: string | null;
    limit: number;
    semantics: string;
    items: { event_type: string; external_id: string; outcome: string; occurred_at: string }[];
}
interface WebhookHealth {
    config_revision: number;
    state: "unconfigured" | "enabled" | "disabled";
    receiver_path: string | null;
    notification_id: string | null;
    provider_config: "unknown";
    last_received_at: string | null;
    local_evidence: "authenticated_notification_receipt";
    connection_state: string;
    connection_revision: string;
    binding_revision: string | null;
    resources: { resource_uid: string; health: string }[];
}
interface Page<T> {
    binding?: ReadAccess | null;
    items: T[];
    next_cursor: string | null;
}

export default function BoardSettingsMetadataConnection({
    provider,
    onStatusChange,
}: {
    provider: "glitchtip" | "dokploy";
    onStatusChange?: () => void;
}) {
    const [t, i18n] = useTranslation();
    const { project, currentUser, canEditBasicInfo } = useBoardSettings();
    const dokploy = provider === "dokploy";
    const root = `/board/${project.uid}/settings/apps/${provider}`;
    const scope = `${currentUser.uid}:${root}:${canEditBasicInfo}`;
    const currentScope = useRef(scope);
    currentScope.current = scope;
    const generation = useRef(0);
    const busy = useRef(false);
    const [pending, setPending] = useState(false);
    const [error, setError] = useState(false);
    const [saved, setSaved] = useState(false);
    const [connections, setConnections] = useState<Page<Connection>>({ items: [], next_cursor: null });
    const [connection, setConnection] = useState<Connection | null>(null);
    const [instance, setInstance] = useState("");
    const [reference, setReference] = useState("");
    const [input, setInput] = useState<{ input_uid: string; input_url: string } | null>(null);
    const [organizations, setOrganizations] = useState<Page<Resource>>({ items: [], next_cursor: null });
    const [organization, setOrganization] = useState("");
    const [projects, setProjects] = useState<Page<Resource>>({ items: [], next_cursor: null });
    const [bindings, setBindings] = useState<Page<Binding>>({ items: [], next_cursor: null });
    const [disconnecting, setDisconnecting] = useState(false);
    const [readAccess, setReadAccess] = useState<ReadAccess | null>(null);
    const [consenting, setConsenting] = useState(false);
    const [deployments, setDeployments] = useState<DeploymentResult | null>(null);
    const [issues, setIssues] = useState<IssueResult | null>(null);
    const [webhook, setWebhook] = useState<WebhookHealth | null>(null);
    const [webhookReference, setWebhookReference] = useState("");
    const [notificationID, setNotificationID] = useState("");
    const [webhookInput, setWebhookInput] = useState<{ input_uid: string; input_url: string } | null>(null);
    const [webhookConfirm, setWebhookConfirm] = useState<"configure" | "disable" | null>(null);
    const clearWebhook = () => {
        setWebhook(null);
        setWebhookReference("");
        setNotificationID("");
        setWebhookInput(null);
        setWebhookConfirm(null);
    };
    const clearReadResults = () => {
        setIssues(null);
        setConsenting(false);
        setDeployments(null);
    };
    const text = (key: string) => t(`project.settings.${dokploy ? key.replaceAll("GlitchTip", "Dokploy") : key}`);
    const [environments, setEnvironments] = useState<Page<Resource>>({ items: [], next_cursor: null });
    const [environment, setEnvironment] = useState("");
    const merge = <T extends { id?: string; connection_uid?: string; resource_uid?: string }>(
        old: Page<T>,
        page: Page<T>,
        append: boolean
    ): Page<T> => {
        const identity = (item: T) => item.id ?? item.connection_uid ?? item.resource_uid;
        const ids = new Set(old.items.map(identity));
        return {
            items: append ? [...old.items, ...page.items.filter((item) => !ids.has(identity(item)))] : page.items,
            next_cursor: page.next_cursor,
        };
    };
    const clearResources = () => {
        clearWebhook();
        setOrganizations({ items: [], next_cursor: null });
        setProjects({ items: [], next_cursor: null });
        setBindings({ items: [], next_cursor: null });
        setOrganization("");
        setEnvironment("");
        setEnvironments({ items: [], next_cursor: null });
        setDisconnecting(false);
        setReadAccess(null);
        clearReadResults();
    };
    const run = async (action: (valid: () => boolean) => Promise<void>) => {
        if (busy.current || !canEditBasicInfo) return;
        busy.current = true;
        const version = ++generation.current;
        const valid = () => version === generation.current && currentScope.current === scope;
        setPending(true);
        setError(false);
        setSaved(false);
        try {
            await action(valid);
        } catch {
            if (valid()) {
                setError(true);
                clearResources();
                setConnection(null);
                setConnections({ items: [], next_cursor: null });
            }
        } finally {
            if (valid()) {
                busy.current = false;
                setPending(false);
            }
        }
    };
    const loadConnections = (after?: string) =>
        run(async (valid) => {
            const page = (await api.get<Page<Connection>>(`${root}/connections`, { params: after ? { after } : {} })).data;
            if (valid()) setConnections((old) => merge(old, page, !!after));
        });
    useEffect(() => {
        generation.current++;
        busy.current = false;
        setPending(false);
        setConnection(null);
        setConnections({ items: [], next_cursor: null });
        setInput(null);
        setReference("");
        setInstance("");
        setError(false);
        setSaved(false);
        clearResources();
        if (canEditBasicInfo) void loadConnections();
        return () => {
            generation.current++;
        };
    }, [scope]);
    const selectConnection = (uid: string) => {
        generation.current++;
        busy.current = false;
        setPending(false);
        const selected = connections.items.find((item) => item.connection_uid === uid) ?? null;
        setConnection(selected);
        clearResources();
        setSaved(false);
        if (dokploy && selected) void refreshWebhook(selected.connection_uid);
    };
    const credentialInput = () =>
        run(async (valid) => {
            const result = (await api.post<{ input_uid: string; input_url: string }>(`${root}/secret-input`)).data;
            const url = new URL(result.input_url);
            if (url.origin !== location.origin || !/^\/secret-input\/[A-Za-z0-9_-]{43}$/.test(url.pathname) || url.search || url.hash)
                throw new Error("Invalid input URL");
            if (valid()) setInput(result);
        });
    const checkInput = () =>
        run(async (valid) => {
            const status = (await api.get<{ state: string; secret_ref?: string }>(`${root}/secret-input/${input!.input_uid}`)).data;
            if (!valid()) return;
            if (status.state === "completed" && /^secret:\/\/ref\/[A-Za-z0-9]{1,11}$/.test(status.secret_ref ?? "")) {
                setReference(status.secret_ref!);
                setInput(null);
            } else if (status.state !== "pending") throw new Error("Input unavailable");
        });
    const register = () =>
        run(async (valid) => {
            const result = (
                await api.post<Connection>(`${root}/connections`, { instance_url: instance.trim(), credential_reference: reference.trim() })
            ).data;
            if (!valid()) return;
            setConnections((old) => ({ ...old, items: [result, ...old.items.filter((row) => row.connection_uid !== result.connection_uid)] }));
            setConnection(result);
            setReference("");
            setSaved(true);
            clearResources();
            onStatusChange?.();
        });
    const connectionRoot = `${root}/connections/${connection?.connection_uid}`;
    const acceptWebhook = (result: WebhookHealth) => {
        if (
            !/^[a-f0-9]{64}$/.test(result.connection_revision) ||
            !Array.isArray(result.resources) ||
            (result.binding_revision === null
                ? result.state !== "unconfigured" ||
                  result.resources.length !== 0 ||
                  result.config_revision !== 0 ||
                  result.receiver_path !== null ||
                  result.last_received_at !== null
                : !/^[a-f0-9]{64}$/.test(result.binding_revision)) ||
            !Number.isInteger(result.config_revision) ||
            result.config_revision < 0 ||
            !["unconfigured", "enabled", "disabled"].includes(result.state) ||
            result.provider_config !== "unknown" ||
            result.local_evidence !== "authenticated_notification_receipt" ||
            (result.receiver_path !== null && !/^\/apps\/dokploy\/notifications\/[A-Za-z0-9_-]+$/.test(result.receiver_path)) ||
            (result.last_received_at !== null &&
                (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(result.last_received_at) ||
                    !Number.isFinite(Date.parse(result.last_received_at))))
        )
            throw new Error("Invalid webhook health");
        if (result.connection_state === "revoked" || result.connection_state === "disconnected") throw new Error("Connection unavailable");
        setWebhook(result);
        setWebhookConfirm(null);
        setNotificationID(result.notification_id ?? "");
    };
    const refreshWebhook = (uid = connection?.connection_uid) =>
        run(async (valid) => {
            if (!dokploy || !uid) return;
            clearWebhook();
            const result = (await api.get<WebhookHealth>(`${root}/connections/${uid}/webhook-health`)).data;
            if (valid()) acceptWebhook(result);
        });
    const webhookSecretInput = () =>
        run(async (valid) => {
            const result = (await api.post<{ input_uid: string; input_url: string }>(`${root}/webhook-secret-input`)).data;
            const url = new URL(result.input_url);
            if (url.origin !== location.origin || !/^\/secret-input\/[A-Za-z0-9_-]{43}$/.test(url.pathname) || url.search || url.hash)
                throw new Error("Invalid input URL");
            if (valid()) setWebhookInput(result);
        });
    const checkWebhookInput = () =>
        run(async (valid) => {
            if (!webhookInput) return;
            const status = (await api.get<{ state: string; secret_ref?: string }>(`${root}/secret-input/${webhookInput.input_uid}`)).data;
            if (!valid()) return;
            if (status.state === "completed" && /^secret:\/\/ref\/[A-Za-z0-9]{1,11}$/.test(status.secret_ref ?? "")) {
                setWebhookReference(status.secret_ref!);
                setWebhookInput(null);
            } else if (status.state !== "pending") throw new Error("Input unavailable");
        });
    const saveWebhook = () =>
        run(async (valid) => {
            if (!dokploy || !connection || !webhook?.binding_revision || !webhookConfirm) return;
            const configuring = webhookConfirm === "configure";
            if (
                configuring &&
                (!webhookCanConfigure ||
                    !/^secret:\/\/ref\/[A-Za-z0-9]{1,11}$/.test(webhookReference.trim()) ||
                    !/^[A-Za-z0-9_-]{0,200}$/.test(notificationID.trim()))
            )
                return;
            const result = (
                await api.post<WebhookHealth>(`${connectionRoot}/webhook-${configuring ? "config" : "disable"}`, {
                    expected_revision: webhook.connection_revision,
                    expected_binding_revision: webhook.binding_revision,
                    expected_config_revision: webhook.config_revision,
                    ...(configuring ? { credential_reference: webhookReference.trim(), notification_id: notificationID.trim() || null } : {}),
                })
            ).data;
            if (!valid()) return;
            acceptWebhook(result);
            setWebhookReference("");
            setSaved(true);
            onStatusChange?.();
        });
    const selectedRoot = `${connectionRoot}/${dokploy ? "selected" : "projects"}`;
    const loadOrganizations = (cursor?: string) =>
        run(async (valid) => {
            const page = (await api.get<Page<Resource>>(`${connectionRoot}/resources`, { params: cursor ? { cursor } : {} })).data;
            if (!valid()) return;
            const bound = !cursor ? (await api.get<Page<Binding>>(selectedRoot)).data : null;
            if (!valid()) return;
            setOrganizations((old) => merge(old, page, !!cursor));
            if (bound) {
                setBindings(bound);
                setReadAccess(bound.binding ?? null);
                clearReadResults();
            }
        });
    const loadProjects = (slug: string, cursor?: string) =>
        run(async (valid) => {
            if (!cursor) {
                clearReadResults();
                setOrganization(slug);
                setProjects({ items: [], next_cursor: null });
                setEnvironments({ items: [], next_cursor: null });
                setEnvironment("");
            }
            if (!slug) return;
            const page = (
                await api.get<Page<Resource>>(`${connectionRoot}/resources`, {
                    params: dokploy ? { external_project_id: slug } : { organization: slug, ...(cursor ? { cursor } : {}) },
                })
            ).data;
            if (valid()) {
                if (dokploy) setEnvironments(page);
                else setProjects((old) => merge(old, page, !!cursor));
            }
        });
    const loadServices = (uid: string) =>
        run(async (valid) => {
            clearReadResults();
            setEnvironment(uid);
            setProjects({ items: [], next_cursor: null });
            if (!uid) return;
            const page = (
                await api.get<Page<Resource>>(`${connectionRoot}/resources`, {
                    params: { external_project_id: organization, environment_id: uid },
                })
            ).data;
            if (valid()) setProjects(page);
        });
    const matches = (row: Binding, item: Resource) => (dokploy ? row.external_id === item.id && row.type === item.type : row.project_id === item.id);
    const loadBindings = () =>
        run(async (valid) => {
            const page = (await api.get<Page<Binding>>(selectedRoot, { params: { after: bindings.next_cursor } })).data;
            if (valid()) {
                setBindings((old) => merge(old, page, true));
                setReadAccess(page.binding ?? null);
                clearReadResults();
            }
        });
    const toggle = (item: Resource) =>
        run(async (valid) => {
            if (dokploy) clearWebhook();
            clearReadResults();
            const existing = bindings.items.find((row) => matches(row, item));
            if (existing?.selected) {
                const result = (
                    await api.post<{ access_revision: number }>(`${selectedRoot}/${existing.resource_uid}/remove`, {
                        expected_revision: existing.access_revision,
                    })
                ).data;
                if (valid())
                    setBindings((old) => ({
                        ...old,
                        items: old.items.map((row) =>
                            row.resource_uid === existing.resource_uid ? { ...row, selected: false, access_revision: result.access_revision } : row
                        ),
                    }));
            } else {
                const result = (
                    await api.post<Binding>(selectedRoot, {
                        ...(dokploy
                            ? {
                                  resource_type: item.type,
                                  external_id: item.id,
                                  external_project_id: item.type === "project" ? null : organization,
                                  environment_id: item.type === "application" || item.type === "compose" ? environment : null,
                              }
                            : { organization, project_slug: item.slug }),
                        expected_revision: connection!.revision,
                        expected_resource_revision: existing?.access_revision ?? null,
                    })
                ).data;
                if (valid())
                    setBindings((old) => ({
                        ...old,
                        items: [...old.items.filter((row) => !matches(row, item)), { ...result, selected: true }],
                    }));
            }
            if (valid()) {
                const page = (await api.get<Page<Binding>>(selectedRoot)).data;
                if (!valid()) return;
                setBindings(page);
                setReadAccess(page.binding ?? null);
                setSaved(true);
                onStatusChange?.();
            }
        });
    const selectedServices = bindings.items.filter(
        (row) => row.selected && row.access_state === "granted" && (row.type === "application" || row.type === "compose")
    );
    const selectedReadResources = dokploy ? selectedServices : bindings.items.filter((row) => row.selected && row.access_state === "granted");
    const readEnabled =
        !!readAccess &&
        (dokploy ? ["enabled", "needs_attention"].includes(readAccess.state) : readAccess.state === "enabled") &&
        (dokploy ? ["signals.read", "deployments.read"] : ["resources.read", "signals.read"]).every((capability) =>
            readAccess.granted_capabilities.includes(capability)
        );
    const webhookCanConfigure =
        !!webhook?.binding_revision &&
        readEnabled &&
        !!selectedServices.length &&
        !bindings.next_cursor &&
        !!readAccess?.granted_capabilities.includes("resources.read") &&
        selectedServices.some((row) => webhook.resources.some((resource) => resource.resource_uid === row.resource_uid));
    const enableRead = () =>
        run(async (valid) => {
            if (!connection || !readAccess || !consenting || !selectedReadResources.length || bindings.next_cursor) return;
            if (!dokploy && (!/^[a-f0-9]{64}$/.test(connection.revision) || !/^[a-f0-9]{64}$/.test(readAccess.revision))) return;
            const result = (
                await api.post<ReadAccess>(`${connectionRoot}/${dokploy ? "enable-read" : "read-access"}`, {
                    ...(dokploy ? { expected_revision: connection.revision } : { expected_connection_revision: connection.revision }),
                    expected_binding_revision: readAccess.revision,
                })
            ).data;
            if (!valid()) return;
            if (dokploy) clearWebhook();
            setReadAccess(result);
            clearReadResults();
            setSaved(true);
            onStatusChange?.();
        });
    const refreshDeployments = (binding: Binding) =>
        run(async (valid) => {
            if (!dokploy || !readEnabled || !binding.selected || !connection) return;
            setDeployments(null);
            const result = (
                await api.post<DeploymentResult>(`${selectedRoot}/${binding.resource_uid}/refresh`, {
                    expected_revision: connection.revision,
                    expected_access_revision: binding.access_revision,
                })
            ).data;
            if (!valid()) return;
            if (result.resource_uid !== binding.resource_uid) throw new Error("Resource mismatch");
            const events = ["deployment.started", "deployment.queued", "deployment.succeeded", "deployment.failed", "deployment.cancelled"];
            const outcomes = ["running", "queued", "success", "failure", "cancelled"];
            const items = result.items.slice(0, 25).map((row) => {
                if (
                    !events.includes(row.event_type) ||
                    !outcomes.includes(row.outcome) ||
                    typeof row.occurred_at !== "string" ||
                    row.occurred_at.length > 40 ||
                    !Number.isFinite(Date.parse(row.occurred_at))
                )
                    throw new Error("Invalid deployment signal");
                return { event_type: row.event_type, outcome: row.outcome, occurred_at: row.occurred_at };
            });
            setDeployments({ resource_uid: result.resource_uid, items, truncated: result.truncated || result.items.length > 25 });
        });
    const refreshIssues = (binding: Binding, cursor?: string) =>
        run(async (valid) => {
            if (dokploy || !readEnabled || !connection || bindings.next_cursor || !selectedReadResources.includes(binding)) return;
            if (!/^[a-f0-9]{64}$/.test(connection.revision) || !Number.isInteger(binding.access_revision)) return;
            if (cursor && (issues?.resource_uid !== binding.resource_uid || issues.next_cursor !== cursor)) return;
            if (!cursor) setIssues(null);
            const result = (
                await api.post<IssueResult>(`${selectedRoot}/${binding.resource_uid}/issues/refresh`, {
                    expected_connection_revision: connection.revision,
                    expected_access_revision: binding.access_revision,
                    ...(cursor ? { cursor } : {}),
                })
            ).data;
            if (!valid()) return;
            if (
                result.resource_uid !== binding.resource_uid ||
                result.semantics !== "status_observation" ||
                result.limit !== 25 ||
                !Array.isArray(result.items) ||
                result.items.length > 25 ||
                !Number.isInteger(result.accepted_count) ||
                result.accepted_count < 0 ||
                result.accepted_count > 25 ||
                (result.next_cursor !== null && (typeof result.next_cursor !== "string" || !result.next_cursor.length))
            )
                throw new Error("Invalid issue observation page");
            const items = result.items.map((row) => {
                if (
                    row.event_type !== "issue.status_observed" ||
                    !["unresolved", "resolved", "ignored"].includes(row.outcome) ||
                    typeof row.external_id !== "string" ||
                    !/^[A-Za-z0-9_-]{1,128}$/.test(row.external_id) ||
                    typeof row.occurred_at !== "string" ||
                    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(row.occurred_at) ||
                    !Number.isFinite(Date.parse(row.occurred_at))
                )
                    throw new Error("Invalid issue observation");
                return { event_type: row.event_type, external_id: row.external_id, outcome: row.outcome, occurred_at: row.occurred_at };
            });
            setIssues((old) => {
                const merged = new Map((cursor && old?.resource_uid === binding.resource_uid ? old.items : []).map((row) => [row.external_id, row]));
                for (const row of items) {
                    const previous = merged.get(row.external_id);
                    if (!previous || Date.parse(row.occurred_at) >= Date.parse(previous.occurred_at)) merged.set(row.external_id, row);
                }
                return { ...result, items: [...merged.values()] };
            });
        });
    const disconnect = () =>
        run(async (valid) => {
            await api.post(`${connectionRoot}/disconnect`, { expected_revision: connection!.revision });
            if (valid()) {
                setConnections((old) => ({ ...old, items: old.items.filter((row) => row.connection_uid !== connection!.connection_uid) }));
                setConnection(null);
                clearResources();
                setSaved(true);
                onStatusChange?.();
            }
        });
    return (
        <fieldset className="fieldset flex min-w-0 flex-col gap-3 rounded-lg border p-3" disabled={pending || !canEditBasicInfo}>
            <legend className="fieldset-legend px-1 font-semibold">{text("GlitchTip connection")}</legend>
            <p className="text-sm text-muted-foreground">{text("GlitchTip connection help")}</p>
            {!canEditBasicInfo && <p>{text("GlitchTip update permission required")}</p>}
            {pending && <p role="status">{t("common.Loading...")}</p>}
            {saved && <p role="status">{text("GlitchTip changes saved")}</p>}
            {error && (
                <div role="alert" className="flex flex-col gap-2">
                    <p>{text("GlitchTip request failed")}</p>
                    <Button size="sm" variant="outline" onClick={() => void loadConnections()}>
                        {t("common.Retry")}
                    </Button>
                </div>
            )}
            <label className="flex min-w-0 flex-col gap-1 text-sm">
                {text("Existing GlitchTip connection")}
                <select
                    className="select min-h-10 w-full min-w-0 rounded-md border bg-background px-3 py-2"
                    value={connection?.connection_uid ?? ""}
                    onChange={(event) => selectConnection(event.target.value)}
                >
                    <option value="">{text("Create new GlitchTip connection")}</option>
                    {connections.items.map((row) => (
                        <option key={row.connection_uid} value={row.connection_uid}>
                            {row.instance_url}
                        </option>
                    ))}
                </select>
            </label>
            {connections.next_cursor && (
                <Button size="sm" variant="outline" onClick={() => void loadConnections(connections.next_cursor!)}>
                    {text("More GlitchTip connections")}
                </Button>
            )}
            {!connection ? (
                <>
                    <label className="flex flex-col gap-1 text-sm">
                        {text("GlitchTip instance URL")}
                        <input
                            className="input min-h-10 w-full min-w-0 rounded-md border bg-background px-3 py-2"
                            type="url"
                            value={instance}
                            placeholder="https://"
                            onChange={(event) => setInstance(event.target.value)}
                        />
                    </label>
                    <p className="text-xs text-muted-foreground">{text("GlitchTip instance approval help")}</p>
                    <label className="flex flex-col gap-1 text-sm">
                        {text("GlitchTip API credential reference")}
                        <input
                            className="input min-h-10 w-full min-w-0 rounded-md border bg-background px-3 py-2"
                            value={reference}
                            placeholder="secret://ref/"
                            onChange={(event) => setReference(event.target.value)}
                        />
                    </label>
                    <Button size="sm" variant="outline" onClick={() => void credentialInput()}>
                        {text("Store GlitchTip API token securely")}
                    </Button>
                    {input && (
                        <div className="flex flex-col gap-2">
                            <a className="underline" href={input.input_url} target="_blank" rel="noopener noreferrer">
                                {text("Open secure token input")}
                            </a>
                            <Button size="sm" variant="outline" onClick={() => void checkInput()}>
                                {text("Check token input")}
                            </Button>
                        </div>
                    )}
                    <Button
                        size="sm"
                        disabled={!instance.trim() || !/^secret:\/\/ref\/[A-Za-z0-9]{1,11}$/.test(reference.trim())}
                        onClick={() => void register()}
                    >
                        {text("Connect GlitchTip")}
                    </Button>
                </>
            ) : (
                <>
                    {dokploy && (
                        <fieldset className="fieldset flex min-w-0 flex-col gap-2 rounded-md border p-3">
                            <legend className="fieldset-legend">{text("Dokploy notification health")}</legend>
                            <Button size="sm" variant="outline" onClick={() => void refreshWebhook()}>
                                {text("Refresh Dokploy notification health")}
                            </Button>
                            {webhook && (
                                <>
                                    <p>{text(`Dokploy notifications ${webhook.state}`)}</p>
                                    <p className="text-xs text-muted-foreground">{text("Dokploy provider configuration unknown")}</p>
                                    <p className="text-sm">
                                        {text("Dokploy authenticated local receipt")}:{" "}
                                        {webhook.last_received_at ? (
                                            <time
                                                dateTime={webhook.last_received_at}
                                                title={formatDateTime(new Date(webhook.last_received_at), i18n.resolvedLanguage)}
                                            >
                                                {formatDateDistance(new Date(webhook.last_received_at), i18n.resolvedLanguage)}
                                            </time>
                                        ) : (
                                            text("Dokploy no authenticated receipt")
                                        )}
                                    </p>
                                    {webhook.receiver_path && (
                                        <label className="flex min-w-0 flex-col gap-1 text-sm">
                                            {text("Dokploy receiver path")}
                                            <input
                                                className="input min-h-10 w-full min-w-0 rounded-md border bg-background px-3 py-2"
                                                readOnly
                                                value={webhook.receiver_path}
                                                onFocus={(event) => event.target.select()}
                                            />
                                        </label>
                                    )}
                                    <p className="text-xs text-muted-foreground">{text("Dokploy notification setup help")}</p>
                                    <label className="flex flex-col gap-1 text-sm">
                                        {text("Dokploy webhook credential reference")}
                                        <input
                                            className="input min-h-10 w-full min-w-0 rounded-md border bg-background px-3 py-2"
                                            value={webhookReference}
                                            placeholder="secret://ref/"
                                            onChange={(event) => {
                                                setWebhookReference(event.target.value);
                                                setWebhookConfirm(null);
                                            }}
                                        />
                                    </label>
                                    <Button size="sm" variant="outline" onClick={() => void webhookSecretInput()}>
                                        {text("Store Dokploy webhook token securely")}
                                    </Button>
                                    {webhookInput && (
                                        <div className="flex flex-col gap-2">
                                            <a className="underline" href={webhookInput.input_url} target="_blank" rel="noopener noreferrer">
                                                {text("Open secure webhook token input")}
                                            </a>
                                            <Button size="sm" variant="outline" onClick={() => void checkWebhookInput()}>
                                                {text("Check webhook token input")}
                                            </Button>
                                        </div>
                                    )}
                                    <label className="flex flex-col gap-1 text-sm">
                                        {text("Dokploy notification ID optional")}
                                        <input
                                            className="input min-h-10 w-full min-w-0 rounded-md border bg-background px-3 py-2"
                                            maxLength={200}
                                            value={notificationID}
                                            onChange={(event) => {
                                                setNotificationID(event.target.value);
                                                setWebhookConfirm(null);
                                            }}
                                        />
                                    </label>
                                    {!webhookConfirm ? (
                                        <>
                                            <Button
                                                size="sm"
                                                variant="outline"
                                                disabled={
                                                    !webhookCanConfigure ||
                                                    !/^secret:\/\/ref\/[A-Za-z0-9]{1,11}$/.test(webhookReference.trim()) ||
                                                    !/^[A-Za-z0-9_-]{0,200}$/.test(notificationID.trim())
                                                }
                                                onClick={() => setWebhookConfirm("configure")}
                                            >
                                                {text("Configure Dokploy notifications")}
                                            </Button>
                                            {webhook.state === "enabled" && (
                                                <Button size="sm" variant="outline" onClick={() => setWebhookConfirm("disable")}>
                                                    {text("Disable Dokploy notifications")}
                                                </Button>
                                            )}
                                        </>
                                    ) : (
                                        <>
                                            <p className="text-sm">
                                                {text(
                                                    webhookConfirm === "configure"
                                                        ? "Dokploy notification confirm help"
                                                        : "Dokploy notification disable help"
                                                )}
                                            </p>
                                            <Button
                                                size="sm"
                                                disabled={webhookConfirm === "configure" && !webhookCanConfigure}
                                                onClick={() => void saveWebhook()}
                                            >
                                                {text(
                                                    webhookConfirm === "configure"
                                                        ? "Confirm Dokploy notification configuration"
                                                        : "Confirm disable Dokploy notifications"
                                                )}
                                            </Button>
                                            <Button size="sm" variant="outline" onClick={() => setWebhookConfirm(null)}>
                                                {t("common.Cancel")}
                                            </Button>
                                        </>
                                    )}
                                </>
                            )}
                        </fieldset>
                    )}
                    <Button size="sm" variant="outline" onClick={() => void loadOrganizations()}>
                        {text("Load GlitchTip organizations")}
                    </Button>
                    {organizations.items.length > 0 && (
                        <label className="flex flex-col gap-1 text-sm">
                            {text("GlitchTip organization")}
                            <select
                                className="select min-h-10 w-full min-w-0 rounded-md border bg-background px-3 py-2"
                                value={organization}
                                onChange={(event) => void loadProjects(event.target.value)}
                            >
                                <option value="">{text("Choose GlitchTip organization")}</option>
                                {organizations.items.map((row) => (
                                    <option key={row.id} value={dokploy ? row.id : row.slug}>
                                        {row.name}
                                    </option>
                                ))}
                            </select>
                        </label>
                    )}
                    {organizations.next_cursor && (
                        <Button size="sm" variant="outline" onClick={() => void loadOrganizations(organizations.next_cursor!)}>
                            {text("More GlitchTip organizations")}
                        </Button>
                    )}
                    {dokploy && organization && (
                        <Button
                            size="sm"
                            variant="outline"
                            disabled={!!bindings.next_cursor}
                            onClick={() => {
                                const item = organizations.items.find((row) => row.id === organization);
                                if (item) void toggle(item);
                            }}
                        >
                            {text(
                                bindings.items.some((row) => row.type === "project" && row.external_id === organization && row.selected)
                                    ? "Remove Dokploy project selection"
                                    : "Select Dokploy project"
                            )}
                        </Button>
                    )}
                    {dokploy && environments.items.length > 0 && (
                        <label className="flex flex-col gap-1 text-sm">
                            {text("Dokploy environment")}
                            <select
                                className="select min-h-10 w-full min-w-0 rounded-md border bg-background px-3 py-2"
                                value={environment}
                                onChange={(event) => void loadServices(event.target.value)}
                            >
                                <option value="">{text("Choose Dokploy environment")}</option>
                                {environments.items.map((row) => (
                                    <option key={row.id} value={row.id}>
                                        {row.name}
                                    </option>
                                ))}
                            </select>
                        </label>
                    )}
                    {dokploy && environment && (
                        <Button
                            size="sm"
                            variant="outline"
                            disabled={!!bindings.next_cursor}
                            onClick={() => {
                                const item = environments.items.find((row) => row.id === environment);
                                if (item) void toggle(item);
                            }}
                        >
                            {text(
                                bindings.items.some((row) => row.type === "environment" && row.external_id === environment && row.selected)
                                    ? "Remove Dokploy environment selection"
                                    : "Select Dokploy environment"
                            )}
                        </Button>
                    )}
                    {bindings.next_cursor && (
                        <Button size="sm" variant="outline" onClick={() => void loadBindings()}>
                            {text("Load remaining GlitchTip selections")}
                        </Button>
                    )}
                    <ul className="flex flex-col gap-2">
                        {projects.items.map((row) => (
                            <li key={`${row.type ?? "project"}:${row.id}`}>
                                <label className="flex min-h-10 items-center gap-2 rounded-md border p-2 text-sm">
                                    <input
                                        type="checkbox"
                                        checked={bindings.items.some((binding) => matches(binding, row) && binding.selected)}
                                        disabled={!!bindings.next_cursor}
                                        onChange={() => void toggle(row)}
                                    />
                                    <span className="min-w-0 break-words">
                                        {row.name}
                                        {dokploy && (
                                            <span className="ml-2 text-xs text-muted-foreground">{text(`Dokploy resource ${row.type}`)}</span>
                                        )}
                                    </span>
                                </label>
                            </li>
                        ))}
                    </ul>
                    {projects.next_cursor && (
                        <Button size="sm" variant="outline" onClick={() => void loadProjects(organization, projects.next_cursor!)}>
                            {text("More GlitchTip projects")}
                        </Button>
                    )}
                    <p className="text-xs text-muted-foreground">{text("GlitchTip project selection help")}</p>
                    {selectedReadResources.length > 0 && (
                        <div className="flex min-w-0 flex-col gap-2 rounded-md border p-2">
                            <p className="text-sm">{text("GlitchTip read scope help")}</p>
                            {readEnabled ? (
                                <p>{text("GlitchTip read enabled")}</p>
                            ) : consenting ? (
                                <>
                                    <p>{text("GlitchTip read confirm help")}</p>
                                    <Button size="sm" disabled={!!bindings.next_cursor || !readAccess} onClick={() => void enableRead()}>
                                        {text("Confirm GlitchTip read access")}
                                    </Button>
                                    <Button size="sm" variant="ghost" onClick={() => setConsenting(false)}>
                                        {t("common.Cancel")}
                                    </Button>
                                </>
                            ) : (
                                <Button
                                    size="sm"
                                    variant="outline"
                                    disabled={!!bindings.next_cursor || !readAccess}
                                    onClick={() => setConsenting(true)}
                                >
                                    {text("Enable GlitchTip read access")}
                                </Button>
                            )}
                            {selectedReadResources.map((binding) => (
                                <div key={binding.resource_uid} className="flex min-w-0 flex-col gap-2">
                                    <p className="break-all text-sm">
                                        {binding.path.at(-1)?.name || binding.external_id || binding.project_id}
                                        {dokploy && <> · {text(`Dokploy resource ${binding.type}`)}</>}
                                    </p>
                                    <Button
                                        size="sm"
                                        variant="outline"
                                        disabled={!readEnabled || !!bindings.next_cursor}
                                        onClick={() => void (dokploy ? refreshDeployments(binding) : refreshIssues(binding))}
                                    >
                                        {text(dokploy ? "Refresh Dokploy deployments" : "Refresh GlitchTip issues")}
                                    </Button>
                                    {!dokploy && issues?.resource_uid === binding.resource_uid && (
                                        <div aria-live="polite" className="flex min-w-0 flex-col gap-2 text-sm">
                                            <p>{text("GlitchTip issue observations help")}</p>
                                            {!issues.items.length && <p>{text("GlitchTip no observed issues")}</p>}
                                            <ul className="list flex flex-col gap-2">
                                                {issues.items.map((item) => (
                                                    <li key={item.external_id} className="list-row flex min-w-0 flex-col break-words">
                                                        <span>
                                                            {text("GlitchTip issue ID")} {item.external_id} ·{" "}
                                                            {text(`GlitchTip observed ${item.outcome}`)}
                                                        </span>
                                                        <span>
                                                            {text("GlitchTip observed at")}:{" "}
                                                            <time dateTime={item.occurred_at}>
                                                                {formatDateTime(new Date(item.occurred_at), i18n.language, { timeStyle: "medium" })}
                                                            </time>
                                                        </span>
                                                    </li>
                                                ))}
                                            </ul>
                                            {issues.next_cursor && (
                                                <Button size="sm" variant="outline" onClick={() => void refreshIssues(binding, issues.next_cursor!)}>
                                                    {text("More GlitchTip issue observations")}
                                                </Button>
                                            )}
                                        </div>
                                    )}
                                    {deployments?.resource_uid === binding.resource_uid && (
                                        <div aria-live="polite" className="flex min-w-0 flex-col gap-2 text-sm">
                                            <p>{text("Dokploy deployment results help")}</p>
                                            {!deployments.items.length && <p>{text("Dokploy no deployments")}</p>}
                                            <ul className="flex flex-col gap-2">
                                                {deployments.items.map((item, index) => (
                                                    <li key={index} className="flex min-w-0 flex-col break-words">
                                                        <span>
                                                            {text(`Dokploy event ${item.event_type}`)} · {text(`Dokploy outcome ${item.outcome}`)}
                                                        </span>
                                                        <time
                                                            dateTime={item.occurred_at}
                                                            title={formatDateTime(new Date(item.occurred_at), i18n.language, { timeStyle: "medium" })}
                                                        >
                                                            {formatDateDistance(new Date(item.occurred_at), i18n.language)}
                                                        </time>
                                                    </li>
                                                ))}
                                            </ul>
                                            {deployments.truncated && <p>{text("Dokploy deployments truncated")}</p>}
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                    {disconnecting ? (
                        <div className="flex flex-col gap-2">
                            <p className="text-sm">{text("GlitchTip disconnect help")}</p>
                            <Button size="sm" variant="outline" onClick={() => void disconnect()}>
                                {text("Confirm disconnect GlitchTip")}
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => setDisconnecting(false)}>
                                {t("common.Cancel")}
                            </Button>
                        </div>
                    ) : (
                        <Button size="sm" variant="ghost" onClick={() => setDisconnecting(true)}>
                            {text("Disconnect GlitchTip")}
                        </Button>
                    )}
                </>
            )}
        </fieldset>
    );
}
