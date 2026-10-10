import Button from "@/components/base/Button";
import Card from "@/components/base/Card";
import { IAppGovernance, TAppGovernanceMode, useAppGovernance } from "@/controllers/api/settings/apps/useAppGovernance";
import { AuthUser } from "@/core/models";
import { usePageHeader } from "@/core/providers/PageHeaderProvider";
import { isAxiosError } from "axios";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import SettingsLoadState from "./SettingsLoadState";

const modes: TAppGovernanceMode[] = ["disabled", "approved_only", "personal_allowed"];

export default function AppGovernancePage({ currentUser }: { currentUser: AuthUser.TModel }) {
    return currentUser.is_admin ? <AppGovernanceSettings /> : null;
}

function AppGovernanceSettings() {
    const [t] = useTranslation();
    const { setPageAliasRef } = usePageHeader();
    const { load, save } = useAppGovernance();
    const [baseline, setBaseline] = useState<IAppGovernance | null>(null);
    const [mode, setMode] = useState<TAppGovernanceMode>("disabled");
    const [failure, setFailure] = useState<"conflict" | "save" | null>(null);
    const [refreshFailed, setRefreshFailed] = useState(false);
    const [receipt, setReceipt] = useState<string | null>(null);
    const busy = load.isFetching || save.isPending;
    const dirty = baseline !== null && mode !== baseline.mode;

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
        if (!baseline || !dirty || busy || failure === "conflict") return;
        setFailure(null);
        setReceipt(null);
        try {
            const updated = await save.mutateAsync({ mode, expected_revision: baseline.revision });
            setBaseline(updated);
            setMode(updated.mode);
            setReceipt(updated.revision);
        } catch (error) {
            setFailure(isAxiosError(error) && error.response?.status === 409 ? "conflict" : "save");
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
                    <Card.Description>{t("settings.App governance ceiling")}</Card.Description>
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
                            {modes.map((value) => (
                                <label key={value} className="flex cursor-pointer items-start gap-3 rounded-lg border p-4">
                                    <input
                                        type="radio"
                                        name="app-governance-mode"
                                        value={value}
                                        checked={mode === value}
                                        className="mt-1 accent-primary"
                                        onChange={() => {
                                            setMode(value);
                                            setReceipt(null);
                                        }}
                                    />
                                    <span className="space-y-1">
                                        <span className="block text-sm font-medium">{t(`settings.App mode ${value}`)}</span>
                                        <span className="block text-sm text-muted-foreground">{t(`settings.App mode ${value} description`)}</span>
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
                            <p role="status" className="text-sm">
                                {t("settings.App governance saved", { revision: receipt })}
                            </p>
                        )}
                        <Button type="submit" disabled={!dirty || busy || failure === "conflict"}>
                            {save.isPending ? t("common.Saving...") : t("common.Save")}
                        </Button>
                    </form>
                </Card.Content>
            </Card.Root>
        </section>
    );
}
