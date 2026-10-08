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
    revision: string;
    state: string;
    granted_capabilities: string[];
}
interface DeploymentResult {
    resource_uid: string;
    items: { event_type: string; outcome: string; occurred_at: string }[];
    truncated: boolean;
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
    const clearReadResults = () => {
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
        setConnection(connections.items.find((item) => item.connection_uid === uid) ?? null);
        clearResources();
        setSaved(false);
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
                if (dokploy) {
                    const page = (await api.get<Page<Binding>>(selectedRoot)).data;
                    if (!valid()) return;
                    setBindings(page);
                    setReadAccess(page.binding ?? null);
                }
                setSaved(true);
                onStatusChange?.();
            }
        });
    const selectedServices = bindings.items.filter(
        (row) => row.selected && row.access_state === "granted" && (row.type === "application" || row.type === "compose")
    );
    const readEnabled =
        !!readAccess &&
        ["enabled", "needs_attention"].includes(readAccess.state) &&
        ["signals.read", "deployments.read"].every((capability) => readAccess.granted_capabilities.includes(capability));
    const enableRead = () =>
        run(async (valid) => {
            if (!dokploy || !connection || !readAccess || !consenting || !selectedServices.length || bindings.next_cursor) return;
            const result = (
                await api.post<ReadAccess>(`${connectionRoot}/enable-read`, {
                    expected_revision: connection.revision,
                    expected_binding_revision: readAccess.revision,
                })
            ).data;
            if (!valid()) return;
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
                    {dokploy && selectedServices.length > 0 && (
                        <div className="flex min-w-0 flex-col gap-2 rounded-md border p-2">
                            <p className="text-sm">{text("Dokploy read scope help")}</p>
                            {readEnabled ? (
                                <p>{text("Dokploy read enabled")}</p>
                            ) : consenting ? (
                                <>
                                    <p>{text("Dokploy read confirm help")}</p>
                                    <Button size="sm" disabled={!!bindings.next_cursor || !readAccess} onClick={() => void enableRead()}>
                                        {text("Confirm Dokploy read access")}
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
                                    {text("Enable Dokploy read access")}
                                </Button>
                            )}
                            {selectedServices.map((binding) => (
                                <div key={binding.resource_uid} className="flex min-w-0 flex-col gap-2">
                                    <p className="break-all text-sm">
                                        {binding.path.at(-1)?.name || binding.external_id} · {text(`Dokploy resource ${binding.type}`)}
                                    </p>
                                    <Button
                                        size="sm"
                                        variant="outline"
                                        disabled={!readEnabled || !!bindings.next_cursor}
                                        onClick={() => void refreshDeployments(binding)}
                                    >
                                        {text("Refresh Dokploy deployments")}
                                    </Button>
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
