import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { useTranslation } from "react-i18next";
import { api } from "@/core/helpers/Api";
import Button from "@/components/base/Button";
import { secretReferenceHistoryHref } from "@/core/utils/SecretReferenceLink";

export default function SecretCopyForm({ referenceUID, onClose, onCopied }: { referenceUID: string; onClose: () => void; onCopied: () => void }) {
    const [t] = useTranslation();
    const [reference, setReference] = useState<{ name: string; revision: number }>();
    const [name, setName] = useState("");
    const [busy, setBusy] = useState(false);
    const [failed, setFailed] = useState(false);
    const [copiedHref, setCopiedHref] = useState<string>();
    const active = useRef(true);
    const submitting = useRef(false);
    const url = `/secret-references/${referenceUID}`;
    useEffect(() => {
        active.current = true;
        const controller = new AbortController();
        api.get(url, { signal: controller.signal })
            .then(({ data }) => {
                if (!active.current) return;
                if (data.reference?.state !== "active" || !Number.isInteger(data.reference.revision)) {
                    setFailed(true);
                    return;
                }
                setReference(data.reference);
            })
            .catch(() => {
                if (active.current) setFailed(true);
            });
        return () => {
            active.current = false;
            controller.abort();
        };
    }, [url]);
    return (
        <section className="rounded-lg border bg-muted/30 p-4" aria-label={t("myAccount.secretCopy.title")}>
            <p className="mb-3 text-xs text-muted-foreground">{t("myAccount.secretCopy.help")}</p>
            {copiedHref ? (
                <div className="flex flex-col gap-3">
                    <p role="status" className="text-sm">
                        {t("myAccount.secretCopy.completed")}
                    </p>
                    <Link className="link text-sm text-primary" to={copiedHref}>
                        {t("myAccount.secretCopy.open")}
                    </Link>
                    <Button variant="ghost" onClick={onClose}>
                        {t("common.Close")}
                    </Button>
                </div>
            ) : (
                <form
                    className="flex flex-col gap-3"
                    onSubmit={async (event) => {
                        event.preventDefault();
                        if (!reference || submitting.current) return;
                        submitting.current = true;
                        setBusy(true);
                        setFailed(false);
                        try {
                            const { data } = await api.post(`${url}/copy`, { name, expected_revision: reference.revision });
                            if (!active.current) return;
                            const href = secretReferenceHistoryHref(data.reference?.uri);
                            if (!href) throw new Error("Invalid copy receipt");
                            setCopiedHref(href);
                            onCopied();
                        } catch {
                            if (active.current) setFailed(true);
                        } finally {
                            submitting.current = false;
                            if (active.current) setBusy(false);
                        }
                    }}
                >
                    {reference && <p className="break-all text-xs text-muted-foreground">{reference.name}</p>}
                    <label className="flex flex-col gap-2 text-sm">
                        {t("myAccount.secretCopy.name")}
                        <input
                            className="input w-full rounded-md border bg-background"
                            value={name}
                            onChange={(event) => setName(event.target.value)}
                            pattern="[a-z0-9_\-]+(/[a-z0-9_\-]+){0,7}"
                            maxLength={256}
                            autoComplete="off"
                            required
                            disabled={!reference || busy}
                        />
                    </label>
                    {failed && (
                        <p role="alert" className="text-sm">
                            {t("myAccount.secretCopy.failed")}
                        </p>
                    )}
                    <div className="flex flex-wrap gap-2">
                        <Button type="submit" disabled={!reference || busy}>
                            {t("myAccount.secretCopy.submit")}
                        </Button>
                        <Button type="button" variant="ghost" disabled={busy} onClick={onClose}>
                            {t("common.Cancel")}
                        </Button>
                    </div>
                </form>
            )}
        </section>
    );
}
