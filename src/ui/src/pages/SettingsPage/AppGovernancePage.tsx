import Button from "@/components/base/Button";
import Card from "@/components/base/Card";
import { IAppGovernance, TAppGovernanceMode, useAppGovernance, useManagedAppOrganizations } from "@/controllers/api/settings/apps/useAppGovernance";
import { AuthUser } from "@/core/models";
import { usePageHeader } from "@/core/providers/PageHeaderProvider";
import { isAxiosError } from "axios";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import SettingsLoadState from "./SettingsLoadState";

const modes: TAppGovernanceMode[] = ["disabled", "approved_only", "personal_allowed"];

export default function AppGovernancePage({ currentUser }: { currentUser: AuthUser.TModel }) {
    const [t] = useTranslation();
    const [cursor, setCursor] = useState<string>();
    const organizations = useManagedAppOrganizations(cursor);
    const [selected, setSelected] = useState(currentUser.is_admin ? "global" : "");
    const [locked, setLocked] = useState(false);
    return (
        <div className="mx-auto w-full max-w-3xl">
            <div className="space-y-2 p-4 sm:px-6">
                <label className="block text-sm font-medium" htmlFor="app-policy-scope">
                    {t("settings.App policy scope")}
                </label>
                <select
                    id="app-policy-scope"
                    className="h-10 w-full rounded-md border bg-background px-3"
                    value={selected}
                    disabled={locked || organizations.isFetching}
                    onChange={(event) => setSelected(event.target.value)}
                >
                    {!currentUser.is_admin && <option value="">{t("settings.App select organization")}</option>}
                    {currentUser.is_admin && <option value="global">{t("settings.App instance policy")}</option>}
                    {selected !== "global" && selected && !organizations.data?.items.some((item) => item.uid === selected) && (
                        <option value={selected}>{t("settings.App selected organization")}</option>
                    )}
                    {organizations.data?.items.map((item) => (
                        <option key={item.uid} value={item.uid}>
                            {item.name}
                        </option>
                    ))}
                </select>
                {organizations.isError && (
                    <Button variant="outline" onClick={() => void organizations.refetch()}>
                        {t("common.Retry")}
                    </Button>
                )}
                {organizations.data?.next_cursor && (
                    <Button variant="ghost" disabled={locked} onClick={() => setCursor(organizations.data!.next_cursor!)}>
                        {t("settings.App more organizations")}
                    </Button>
                )}
                {cursor && (
                    <Button variant="ghost" disabled={locked} onClick={() => setCursor(undefined)}>
                        {t("settings.App first organizations")}
                    </Button>
                )}
            </div>
            {selected && <AppGovernanceSettings key={selected} organizationUID={selected === "global" ? undefined : selected} onLock={setLocked} />}
        </div>
    );
}

function AppGovernanceSettings({ organizationUID, onLock }: { organizationUID?: string; onLock: (value: boolean) => void }) {
    const [t] = useTranslation();
    const { setPageAliasRef } = usePageHeader();
    const { load, save } = useAppGovernance(organizationUID);
    const [baseline, setBaseline] = useState<IAppGovernance | null>(null);
    const [mode, setMode] = useState<TAppGovernanceMode | null>("disabled");
    const [failure, setFailure] = useState<"conflict" | "save" | null>(null);
    const [refreshFailed, setRefreshFailed] = useState(false);
    const [receipt, setReceipt] = useState<string | null>(null);
    const writingRef = useRef(false);
    const busy = load.isFetching || save.isPending;
    const dirty = baseline !== null && mode !== baseline.mode;
    useEffect(() => {
        onLock(dirty || busy);
        return () => onLock(false);
    }, [dirty, busy, onLock]);

    useEffect(() => {
        setPageAliasRef.current(t("settings.Apps"));
    }, [t]);

    useEffect(() => {
        if (load.data && !load.isFetching && !load.isError && !baseline) {
            setBaseline(load.data);
            setMode(load.data.mode);
        }
    }, [load.data, load.isFetching, load.isError, baseline]);

    const submit = async () => {
        if (!baseline || !dirty || busy || writingRef.current || failure === "conflict") return;
        writingRef.current = true;
        setFailure(null);
        setReceipt(null);
        try {
            const updated = await save.mutateAsync({ mode, expected_revision: baseline.revision });
            setBaseline(updated);
            setMode(updated.mode);
            setReceipt(updated.revision);
        } catch (error) {
            setFailure(isAxiosError(error) && error.response?.status === 409 ? "conflict" : "save");
        } finally {
            writingRef.current = false;
        }
    };

    const refresh = async () => {
        setRefreshFailed(false);
        const result = await load.refetch();
        if (result.error || !result.data) {
            // Failed refresh leaves both the draft and its pinned revision intact.
            setRefreshFailed(true);
            return;
        }
        setBaseline(result.data);
        setMode(result.data.mode);
        setFailure(null);
        setReceipt(null);
    };

    if (!baseline) {
        return <SettingsLoadState error={load.isError} isFetching={load.isFetching} retry={() => void load.refetch()} />;
    }

    return (
        <section className="mx-auto w-full max-w-3xl space-y-4 p-4 sm:p-6" aria-busy={busy}>
            <Card.Root>
                <Card.Header>
                    <Card.Title>{t("settings.Apps")}</Card.Title>
                    <Card.Description>
                        {t(organizationUID ? "settings.App organization ceiling" : "settings.App governance ceiling")}
                    </Card.Description>
                </Card.Header>
                <Card.Content className="space-y-4">
                    <p className="text-sm text-muted-foreground">{t("settings.App personal token privacy")}</p>
                    <p className="text-sm text-muted-foreground">{t("settings.App organization automation")}</p>
                    <form
                        className="space-y-4"
                        onSubmit={(event) => {
                            event.preventDefault();
                            void submit();
                        }}
                    >
                        <fieldset disabled={busy} className="space-y-3">
                            <legend className="mb-3 text-sm font-medium">{t("settings.App access mode")}</legend>
                            {(organizationUID ? [null, ...modes] : modes).map((value) => (
                                <label key={value ?? "inherit"} className="flex cursor-pointer items-start gap-3 rounded-lg border p-4">
                                    <input
                                        type="radio"
                                        name="app-governance-mode"
                                        value={value ?? "inherit"}
                                        checked={mode === value}
                                        className="mt-1 accent-primary"
                                        onChange={() => {
                                            setMode(value);
                                            setReceipt(null);
                                        }}
                                    />
                                    <span className="space-y-1">
                                        <span className="block text-sm font-medium">{t(`settings.App mode ${value ?? "inherit"}`)}</span>
                                        <span className="block text-sm text-muted-foreground">
                                            {t(`settings.App mode ${value ?? "inherit"} description`)}
                                        </span>
                                    </span>
                                </label>
                            ))}
                        </fieldset>
                        <p className="text-sm text-muted-foreground">
                            {t("settings.App effective mode")}: {t(`settings.App mode ${baseline.effective_mode}`)}
                        </p>
                        {failure && (
                            <div role="alert" className="space-y-2 rounded-lg border border-destructive/30 p-3 text-sm">
                                <p>{t(`settings.App ${failure} failed`)}</p>
                                {refreshFailed && <p>{t("settings.App refresh failed")}</p>}
                                {failure === "conflict" && (
                                    <Button type="button" variant="outline" disabled={busy} onClick={() => void refresh()}>
                                        {t("settings.App discard and refresh")}
                                    </Button>
                                )}
                            </div>
                        )}
                        {receipt !== null && (
                            <p role="status" className="break-words text-sm">
                                {t("settings.App governance saved", { revision: receipt })}
                            </p>
                        )}
                        <Button type="submit" disabled={!dirty || busy || failure === "conflict"}>
                            {save.isPending ? t("common.Saving...") : t("common.Save")}
                        </Button>
                        {dirty && (
                            <Button
                                type="button"
                                variant="ghost"
                                disabled={busy}
                                onClick={() => {
                                    setMode(baseline.mode);
                                    setFailure(null);
                                    setReceipt(null);
                                }}
                            >
                                {t("common.Cancel")}
                            </Button>
                        )}
                    </form>
                </Card.Content>
            </Card.Root>
        </section>
    );
}
