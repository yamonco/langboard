import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/core/helpers/Api";
import { useBoardSettings } from "@/core/providers/BoardSettingsProvider";
import Button from "@/components/base/Button";

interface Connection {
    connection_uid: string;
    instance_url: string;
    revision: string;
}
interface Resource {
    id: string;
    slug: string;
    name: string;
}
interface Binding {
    resource_uid: string;
    project_id: string;
    access_revision: number;
    selected: boolean;
    path: { type: string; id: string; slug?: string }[];
}
interface Page<T> {
    items: T[];
    next_cursor: string | null;
}

export default function BoardSettingsGlitchTip({ onStatusChange }: { onStatusChange?: () => void }) {
    const [t] = useTranslation();
    const { project, currentUser, canEditBasicInfo } = useBoardSettings();
    const root = `/board/${project.uid}/settings/apps/glitchtip`;
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
    const text = (key: string) => t(`project.settings.${key}`);
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
        setDisconnecting(false);
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
    const loadOrganizations = (cursor?: string) =>
        run(async (valid) => {
            const page = (await api.get<Page<Resource>>(`${connectionRoot}/resources`, { params: cursor ? { cursor } : {} })).data;
            if (!valid()) return;
            const bound = !cursor ? (await api.get<Page<Binding>>(`${connectionRoot}/projects`)).data : null;
            if (!valid()) return;
            setOrganizations((old) => merge(old, page, !!cursor));
            if (bound) setBindings(bound);
        });
    const loadProjects = (slug: string, cursor?: string) =>
        run(async (valid) => {
            if (!cursor) {
                setOrganization(slug);
                setProjects({ items: [], next_cursor: null });
            }
            if (!slug) return;
            const page = (
                await api.get<Page<Resource>>(`${connectionRoot}/resources`, { params: { organization: slug, ...(cursor ? { cursor } : {}) } })
            ).data;
            if (valid()) setProjects((old) => merge(old, page, !!cursor));
        });
    const loadBindings = () =>
        run(async (valid) => {
            const page = (await api.get<Page<Binding>>(`${connectionRoot}/projects`, { params: { after: bindings.next_cursor } })).data;
            if (valid()) setBindings((old) => merge(old, page, true));
        });
    const toggle = (item: Resource) =>
        run(async (valid) => {
            const existing = bindings.items.find((row) => row.project_id === item.id);
            if (existing?.selected) {
                const result = (
                    await api.post<{ access_revision: number }>(`${connectionRoot}/projects/${existing.resource_uid}/remove`, {
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
                    await api.post<Binding>(`${connectionRoot}/projects`, {
                        organization,
                        project_slug: item.slug,
                        expected_revision: connection!.revision,
                        expected_resource_revision: existing?.access_revision ?? null,
                    })
                ).data;
                if (valid())
                    setBindings((old) => ({
                        ...old,
                        items: [...old.items.filter((row) => row.project_id !== item.id), { ...result, selected: true }],
                    }));
            }
            if (valid()) {
                setSaved(true);
                onStatusChange?.();
            }
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
                                    <option key={row.id} value={row.slug}>
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
                    {bindings.next_cursor && (
                        <Button size="sm" variant="outline" onClick={() => void loadBindings()}>
                            {text("Load remaining GlitchTip selections")}
                        </Button>
                    )}
                    <ul className="flex flex-col gap-2">
                        {projects.items.map((row) => (
                            <li key={row.id}>
                                <label className="flex min-h-10 items-center gap-2 rounded-md border p-2 text-sm">
                                    <input
                                        type="checkbox"
                                        checked={bindings.items.some((binding) => binding.project_id === row.id && binding.selected)}
                                        disabled={!!bindings.next_cursor}
                                        onChange={() => void toggle(row)}
                                    />
                                    <span className="min-w-0 break-words">{row.name}</span>
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
