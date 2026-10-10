import { useTranslation } from "react-i18next";
import Box from "@/components/base/Box";
import Collapsible from "@/components/base/Collapsible";
import { cn } from "@/core/utils/ComponentUtils";
import { useState } from "react";

const MarkdownThinkBlock = ({ children = [] }: { children?: React.ReactNode }) => {
    const [t] = useTranslation();
    const [isOpened, setIsOpened] = useState(false);

    return (
        <Collapsible.Root open={isOpened} onOpenChange={setIsOpened}>
            <Collapsible.Trigger asChild>
                <button type="button" className={cn("max-w-full truncate text-left italic text-foreground/70", isOpened ? "hidden" : "block")}>
                    <span className="font-bold">{t("common.Show thoughts...")}</span>
                </button>
            </Collapsible.Trigger>
            <Collapsible.Content>
                <Box className="italic text-foreground/70">
                    <button type="button" className="font-bold" onClick={() => setIsOpened(() => false)}>
                        {t("common.Thoughts")}:{" "}
                    </button>
                    {children}
                </Box>
            </Collapsible.Content>
        </Collapsible.Root>
    );
};

export default MarkdownThinkBlock;
