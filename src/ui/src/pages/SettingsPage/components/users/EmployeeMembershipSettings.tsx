import Button from "@/components/base/Button";
import Checkbox from "@/components/base/Checkbox";
import { api } from "@/core/helpers/Api";
import { useAppSetting } from "@/core/providers/AppSettingProvider";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

type MembershipSettings = {
    issuer: string;
    configured: boolean;
    group_uids: string[];
    groups: { uid: string; display_name: string; external_id: string | null }[];
};

export default function EmployeeMembershipSettings() {
    const [t] = useTranslation();
    const { currentUser } = useAppSetting();
    const isAdmin = currentUser.useField("is_admin");
    const [settings, setSettings] = useState<MembershipSettings>();
    const [selected, setSelected] = useState<string[]>([]);
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState("");

    useEffect(() => {
        if (!isAdmin) return;
        const abort = new AbortController();
        api.get("/settings/employee-membership", { signal: abort.signal })
            .then(({ data }) => {
                setSettings(data);
                setSelected(data.group_uids);
            })
            .catch(() => {
                if (!abort.signal.aborted) setMessage(t("settings.Membership settings failed"));
            });
        return () => abort.abort();
    }, [isAdmin, t]);

    if (!isAdmin) return null;
    const save = async () => {
        setBusy(true);
        setMessage("");
        try {
            const { data } = await api.put("/settings/employee-membership", { group_uids: selected });
            setSettings(data);
            setSelected(data.group_uids);
            setMessage(t("settings.Membership settings saved"));
        } catch {
            setMessage(t("settings.Membership settings failed"));
        } finally {
            setBusy(false);
        }
    };

    return (
        <section className="mb-6 rounded-lg border border-border p-4" aria-labelledby="employee-membership-title">
            <h2 id="employee-membership-title" className="text-lg font-semibold">
                {t("settings.Employee membership")}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">{t("settings.Employee membership guidance")}</p>
            {settings && (
                <>
                    <p className="mt-3 break-all text-xs text-muted-foreground">SCIM: {settings.issuer || t("settings.Not configured")}</p>
                    {!settings.groups.length && <p className="mt-3 text-sm">{t("settings.No synchronized SCIM groups")}</p>}
                    <div className="my-3 grid gap-2 sm:grid-cols-2">
                        {settings.groups.map((group) => (
                            <label key={group.uid} className="flex cursor-pointer items-start gap-3 rounded-md border border-border p-3">
                                <Checkbox
                                    disabled={busy}
                                    checked={selected.includes(group.uid)}
                                    aria-label={group.display_name}
                                    onCheckedChange={(checked) =>
                                        setSelected((ids) => (checked ? [...ids, group.uid] : ids.filter((uid) => uid !== group.uid)))
                                    }
                                />
                                <span className="min-w-0">
                                    <span className="block text-sm font-medium">{group.display_name}</span>
                                    <span className="block break-all text-xs text-muted-foreground">ID: {group.uid}</span>
                                    {group.external_id && (
                                        <span className="block break-all text-xs text-muted-foreground">externalId: {group.external_id}</span>
                                    )}
                                </span>
                            </label>
                        ))}
                    </div>
                    <Button disabled={busy || !settings.issuer} onClick={save}>
                        {t("common.Save")}
                    </Button>
                </>
            )}
            {message && (
                <p role="status" className="mt-2 text-sm">
                    {message}
                </p>
            )}
        </section>
    );
}
