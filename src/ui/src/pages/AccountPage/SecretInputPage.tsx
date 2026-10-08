import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { useTranslation } from "react-i18next";
import { api, submitSecretInput } from "@/core/helpers/Api";
import Button from "@/components/base/Button";

export default function SecretInputPage() {
    const { inputUID } = useParams();
    const [t] = useTranslation();
    const [target, setTarget] = useState<{ name: string; scope: string; operation: "create" | "rotate" }>();
    const [state, setState] = useState<"loading" | "ready" | "saving" | "completed" | "failed" | "cancelled">("loading");
    const [historyUID, setHistoryUID] = useState<string>();
    const input = useRef<HTMLInputElement>(null);
    const url = `/secret-input/${inputUID}`;
    useEffect(() => {
        let active = true;
        api.get(url)
            .then(({ data }) => {
                if (active) {
                    setTarget(data);
                    setState("ready");
                }
            })
            .catch(() => {
                if (active) setState("failed");
            });
        return () => {
            active = false;
            if (input.current) input.current.value = "";
        };
    }, [url]);
    return (
        <main className="mx-auto w-full max-w-lg px-4 py-10 sm:py-16">
            <section className="card card-border rounded-xl border bg-background shadow-sm">
                <div className="card-body flex flex-col gap-4 p-5 sm:p-6">
                    <h1 className="card-title text-lg font-semibold">{t("myAccount.secretInput.title")}</h1>
                    <p className="text-sm text-muted-foreground">{t("myAccount.secretInput.help")}</p>
                    {target && (
                        <p className="break-all text-sm">
                            {t(target.operation === "rotate" ? "myAccount.secretInput.rotate" : "myAccount.secretInput.create")}
                            {" · "}
                            {target.scope} · {target.name}
                        </p>
                    )}
                    {state === "cancelled" ? (
                        <p role="status">{t("myAccount.secretInput.cancelled")}</p>
                    ) : state === "completed" ? (
                        <div className="flex flex-col gap-3">
                            <p role="status">{t("myAccount.secretInput.completed")}</p>
                            {historyUID && (
                                <Link className="text-sm text-primary underline underline-offset-4" to={`/secret-references/${historyUID}/history`}>
                                    {t("myAccount.secretHistory.title")}
                                </Link>
                            )}
                        </div>
                    ) : state === "failed" ? (
                        <p role="alert">{t("myAccount.secretInput.failed")}</p>
                    ) : state === "loading" ? (
                        <p role="status">{t("common.Loading...")}</p>
                    ) : (
                        <form
                            className="flex flex-col gap-4"
                            onSubmit={async (event) => {
                                event.preventDefault();
                                if (!input.current || state !== "ready") return;
                                const value = input.current.value;
                                input.current.value = "";
                                setState("saving");
                                try {
                                    const { data } = await submitSecretInput(url, value);
                                    const referenceUID = /^secret:\/\/ref\/([A-Za-z0-9]{1,11})$/.exec(data.secret_ref)?.[1];
                                    setHistoryUID(referenceUID);
                                    setState("completed");
                                } catch {
                                    setState("failed");
                                }
                            }}
                        >
                            <label className="flex flex-col gap-2 text-sm">
                                {t("myAccount.secretInput.value")}
                                <input
                                    ref={input}
                                    className="input h-10 w-full rounded-md border bg-background px-3"
                                    type="password"
                                    name="secret-value"
                                    autoComplete="new-password"
                                    required
                                    maxLength={65536}
                                    disabled={state === "saving"}
                                />
                            </label>
                            <Button type="submit" disabled={state === "saving"}>
                                {t("myAccount.secretInput.save")}
                            </Button>
                            <Button
                                type="button"
                                variant="ghost"
                                disabled={state === "saving"}
                                onClick={async () => {
                                    if (input.current) input.current.value = "";
                                    setState("saving");
                                    try {
                                        await api.delete(url);
                                        setState("cancelled");
                                    } catch {
                                        setState("failed");
                                    }
                                }}
                            >
                                {t("myAccount.secretInput.cancel")}
                            </Button>
                        </form>
                    )}
                </div>
            </section>
        </main>
    );
}
