import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import { useTranslation } from "react-i18next";

export default function BoardLoadError({ isFetching, retry }: { isFetching: bool; retry: () => void }) {
    const [t] = useTranslation();
    return (
        <Box role="alert" className="m-4 shrink-0 rounded-xl border bg-background p-4">
            <p className="text-sm text-muted-foreground">{t("board.Could not load board")}</p>
            <Button
                type="button"
                size="sm"
                variant="outline"
                className="mt-2"
                disabled={isFetching}
                onClick={() => {
                    if (!isFetching) retry();
                }}
            >
                {t("common.Retry")}
            </Button>
        </Box>
    );
}
