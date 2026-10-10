import Button from "@/components/base/Button";
import Loading from "@/components/base/Loading";
import { useTranslation } from "react-i18next";

export default function SettingsLoadState({ error, isFetching, retry }: { error: boolean; isFetching: boolean; retry: () => void }) {
    const [t] = useTranslation();
    return (
        <div className="m-4 rounded-xl border bg-background p-4" role={error ? "alert" : "status"}>
            {error ? (
                <>
                    <p className="text-sm text-muted-foreground">{t("settings.Could not load settings")}</p>
                    <Button type="button" size="sm" variant="outline" className="mt-2" disabled={isFetching} onClick={retry}>
                        {t("common.Retry")}
                    </Button>
                </>
            ) : (
                <Loading variant="secondary" size="2" animate="pulse" />
            )}
        </div>
    );
}
