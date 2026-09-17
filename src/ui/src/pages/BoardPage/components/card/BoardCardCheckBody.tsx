import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { cn } from "@/core/utils/ComponentUtils";
import BoardCardDescription from "@/pages/BoardPage/components/card/BoardCardDescription";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

/**
 * Single-object body for check cards: the short title acts as the whole content.
 * Members, deadline, and the description section header stay hidden; the edit
 * button is the explicit way to fill the body and graduate into a normal card.
 */
function BoardCardCheckBody({ scrollParentRef }: { scrollParentRef: React.RefObject<HTMLDivElement | null> }): React.JSX.Element {
    const { card, enterCardEditMode } = useBoardCard();
    const [t] = useTranslation();
    const title = card.useField("title");
    const completed = card.useField("completed") ?? false;
    const bodyText = useMemo(() => title, [title]);

    return (
        <Flex direction="col" gap="3" className="min-w-0">
            <Box className={cn("break-all text-2xl font-semibold leading-snug", completed && "line-through opacity-60")}>{bodyText}</Box>
            <Box textSize="sm" className="text-muted-foreground">
                {t("card.Fill the body to turn this into a normal card")}
            </Box>
            <BoardCardDescription key={`board-card-check-description-${card.uid}`} scrollParentRef={scrollParentRef} />
            <Button variant="outline" size="sm" className="w-fit" onClick={enterCardEditMode}>
                <IconComponent icon="pencil" size="4" />
                {t("common.Edit")}
            </Button>
        </Flex>
    );
}

BoardCardCheckBody.displayName = "Board.Card.CheckBody";

export default BoardCardCheckBody;
