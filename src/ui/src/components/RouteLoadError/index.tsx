import Button from "@/components/base/Button";
import { ROUTES } from "@/core/routing/constants";
import { useTranslation } from "react-i18next";

// Stay eager and independent of auth/layout providers: their chunks may have failed.
export default function RouteLoadError() {
    const [t] = useTranslation(undefined, { useSuspense: false });
    return (
        <main className="flex min-h-dvh items-center justify-center bg-background p-4 text-foreground">
            <section role="alert" className="w-full max-w-md rounded-xl border p-6">
                <h1 className="text-lg font-semibold">{t("errors.A rendering error occurred.", { defaultValue: "A rendering error occurred." })}</h1>
                <div className="mt-4 flex flex-wrap gap-2">
                    <Button type="button" onClick={() => window.location.reload()}>
                        {t("common.Refresh", { defaultValue: "Refresh" })}
                    </Button>
                    <Button variant="outline" asChild>
                        <a href={ROUTES.AFTER_SIGN_IN}>{t("common.Go to Dashboard", { defaultValue: "Go to Dashboard" })}</a>
                    </Button>
                </div>
            </section>
        </main>
    );
}
