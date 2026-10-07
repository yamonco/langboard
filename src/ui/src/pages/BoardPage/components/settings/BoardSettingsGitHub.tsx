import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/core/helpers/Api";
import { useBoardSettings } from "@/core/providers/BoardSettingsProvider";
import Button from "@/components/base/Button";

interface Connection {
    connection_uid: string;
    installation_url: string;
}
interface Installation {
    id: number;
    account: { id: number; login: string; type: string };
    suspended: boolean;
}
interface Authorization {
    installations: Installation[];
    installation_proof: string;
    has_more: boolean;
}
interface Repository {
    id: number;
    name: string;
    archived: boolean;
}
interface Snapshot {
    revision: string;
    items: { repository_id: string; connection_uid: string; selected: boolean }[];
}

export default function BoardSettingsGitHub() {
    const [t] = useTranslation();
    const { project, currentUser, canEditBasicInfo } = useBoardSettings();
    const root = `/board/${project.uid}/settings/apps/github`;
    const key = `github-onboarding:${currentUser.uid}:${project.uid}`;
    const [connection, setConnection] = useState<Connection | null>(() => {
        try {
            return JSON.parse(sessionStorage.getItem(key) ?? "null");
        } catch {
            return null;
        }
    });
    const [organization, setOrganization] = useState("");
    const [authorization, setAuthorization] = useState<Authorization | null>(null);
    const [installation, setInstallation] = useState<Installation | null>(null);
    const [repositories, setRepositories] = useState<Repository[]>([]);
    const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
    const [selected, setSelected] = useState<number[]>([]);
    const [nextPage, setNextPage] = useState<number | null>(null);
    const [pending, setPending] = useState(false);
    const [error, setError] = useState(false);
    const [saved, setSaved] = useState(false);
    const callbackStarted = useRef(false);
    const text = (name: string) => t(`project.settings.${name}`);
    const run = async (action: () => Promise<void>) => {
        setPending(true);
        setError(false);
        setSaved(false);
        try {
            await action();
        } catch {
            setError(true);
        } finally {
            setPending(false);
        }
    };
    useEffect(() => {
        const params = new URLSearchParams(window.location.search);
        const code = params.get("code"),
            state = params.get("state");
        if (!code || !state || callbackStarted.current || !canEditBasicInfo) return;
        const kind = sessionStorage.getItem(`${key}:kind`);
        if (kind !== "manifest" && kind !== "authorization") return;
        callbackStarted.current = true;
        // Remove one-time values before network IO; ambiguous exchanges are never retried.
        params.delete("code");
        params.delete("state");
        params.delete("github_app_manifest");
        history.replaceState(history.state, "", `${location.pathname}${params.size ? `?${params}` : ""}${location.hash}`);
        sessionStorage.removeItem(`${key}:kind`);
        void run(async () => {
            if (kind === "manifest") {
                const result = (await api.post<Connection>(`${root}/manifest/complete`, { code, state })).data;
                sessionStorage.setItem(key, JSON.stringify(result));
                setConnection(result);
            } else {
                setAuthorization((await api.post<Authorization>(`${root}/authorization/complete`, { code, state })).data);
            }
        });
    }, [key, root, canEditBasicInfo]);
    const register = () =>
        run(async () => {
            const result = (
                await api.post<{ registration_url: string; manifest: unknown }>(`${root}/manifest`, null, {
                    params: organization.trim() ? { organization: organization.trim() } : {},
                })
            ).data;
            const url = new URL(result.registration_url);
            if (url.origin !== "https://github.com" || !url.pathname.endsWith("/settings/apps/new")) throw new Error("Invalid registration target");
            sessionStorage.setItem(`${key}:kind`, "manifest");
            const form = document.createElement("form");
            form.method = "POST";
            form.action = url.href;
            const input = document.createElement("input");
            input.type = "hidden";
            input.name = "manifest";
            input.value = JSON.stringify(result.manifest);
            form.append(input);
            document.body.append(form);
            form.submit();
            form.remove();
        });
    const authorize = () =>
        run(async () => {
            const result = (await api.post<{ authorization_url: string }>(`${root}/authorization`, { connection_uid: connection!.connection_uid }))
                .data;
            const url = new URL(result.authorization_url);
            if (url.origin !== "https://github.com" || url.pathname !== "/login/oauth/authorize") throw new Error("Invalid authorization target");
            sessionStorage.setItem(`${key}:kind`, "authorization");
            location.assign(url.href);
        });
    const loadRepositories = (item: Installation, page = 1) =>
        run(async () => {
            const result = (
                await api.get<{ repositories: Repository[]; next_page: number | null }>(`${root}/installations/${item.id}/repositories`, {
                    params: { connection_uid: connection!.connection_uid, account_id: item.account.id, page },
                })
            ).data;
            if (page === 1) {
                const current = (await api.get<Snapshot>(`${root}/resources`)).data;
                setSnapshot(current);
                setSelected(
                    current.items
                        .filter((row) => row.selected && row.connection_uid === connection!.connection_uid)
                        .map((row) => Number(row.repository_id))
                );
                setInstallation(item);
                setRepositories(result.repositories);
            } else setRepositories((previous) => [...previous, ...result.repositories.filter((row) => !previous.some((old) => old.id === row.id))]);
            setNextPage(result.next_page);
        });
    const save = () =>
        run(async () => {
            const before = snapshot!.items
                .filter((row) => row.selected && row.connection_uid === connection!.connection_uid)
                .map((row) => Number(row.repository_id));
            const visible = new Set(repositories.map((row) => row.id));
            const add = selected.filter((id) => !before.includes(id));
            const remove = before.filter((id) => visible.has(id) && !selected.includes(id));
            if (!add.length && !remove.length) return;
            if (add.length > 25 || remove.length > 25) throw new Error("Delta limit");
            setSnapshot(
                (
                    await api.put<Snapshot>(`${root}/resources`, {
                        connection_uid: connection!.connection_uid,
                        installation_id: installation!.id,
                        account_id: installation!.account.id,
                        add,
                        remove,
                        expected_revision: snapshot!.revision,
                        installation_proof: authorization!.installation_proof,
                    })
                ).data
            );
            setSaved(true);
        });
    return (
        <fieldset className="fieldset min-w-0 rounded-lg border p-3" disabled={pending || !canEditBasicInfo}>
            <legend className="fieldset-legend">{text("GitHub connection")}</legend>
            <p className="text-sm text-muted-foreground">{text("GitHub onboarding help")}</p>
            {error && <p role="alert">{text("GitHub onboarding failed")}</p>}
            {saved && <p role="status">{text("GitHub repositories saved")}</p>}
            {pending && <p role="status">{t("common.Loading...")}</p>}
            {!connection ? (
                <>
                    <label className="flex flex-col gap-1">
                        {text("GitHub organization optional")}
                        <input
                            className="rounded-md border bg-background px-3 py-2"
                            value={organization}
                            maxLength={39}
                            onChange={(event) => setOrganization(event.target.value)}
                        />
                    </label>
                    <Button size="sm" variant="outline" onClick={() => void register()}>
                        {text("Create GitHub App")}
                    </Button>
                </>
            ) : (
                <>
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                            const url = new URL(connection.installation_url);
                            if (url.origin === "https://github.com" && /^\/apps\/[a-zA-Z0-9-]+\/installations\/new$/.test(url.pathname))
                                location.assign(url.href);
                        }}
                    >
                        {text("Install GitHub App")}
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => void authorize()}>
                        {text("Verify GitHub account")}
                    </Button>
                    {authorization && (
                        <>
                            {authorization.has_more && <p role="status">{text("GitHub installation limit")}</p>}
                            <div className="flex flex-wrap gap-2">
                                {authorization.installations.map((item) => (
                                    <Button
                                        key={item.id}
                                        size="sm"
                                        variant="outline"
                                        disabled={item.suspended}
                                        onClick={() => void loadRepositories(item)}
                                    >
                                        {item.account.login} · {item.account.type}
                                    </Button>
                                ))}
                            </div>
                            {installation && (
                                <fieldset className="fieldset min-w-0">
                                    <legend className="fieldset-legend">{installation.account.login}</legend>
                                    <p className="text-xs text-muted-foreground">{text("GitHub repository selection help")}</p>
                                    {repositories.map((row) => (
                                        <label key={row.id} className="flex min-w-0 items-center gap-2 py-1">
                                            <input
                                                type="checkbox"
                                                className="checkbox checkbox-sm"
                                                checked={selected.includes(row.id)}
                                                onChange={(event) =>
                                                    setSelected((previous) =>
                                                        event.target.checked ? [...previous, row.id] : previous.filter((id) => id !== row.id)
                                                    )
                                                }
                                            />
                                            <span className="break-all">{row.name}</span>
                                        </label>
                                    ))}
                                    {nextPage && (
                                        <Button size="sm" variant="outline" onClick={() => void loadRepositories(installation, nextPage)}>
                                            {text("More GitHub repositories")}
                                        </Button>
                                    )}
                                    <Button size="sm" onClick={() => void save()}>
                                        {text("Save GitHub repositories")}
                                    </Button>
                                </fieldset>
                            )}
                        </>
                    )}
                </>
            )}
        </fieldset>
    );
}
