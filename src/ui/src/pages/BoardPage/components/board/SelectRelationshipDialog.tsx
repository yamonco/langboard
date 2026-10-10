import Button from "@/components/base/Button";
import Dialog from "@/components/base/Dialog";
import Flex from "@/components/base/Flex";
import ScrollArea from "@/components/base/ScrollArea";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { useBoard } from "@/core/providers/BoardProvider";
import { useBoardController } from "@/core/providers/BoardController";
import { IBoardColumnCardContextParams } from "@/pages/BoardPage/components/board/BoardConstants";
import RelationshipTypePicker from "@/pages/BoardPage/components/board/RelationshipTypePicker";
import { memo, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export interface ISelectRelationshipDialogProps {
    isOpened: bool;
    setIsOpened: (isOpened: bool) => void;
}

const SelectRelationshipDialog = memo(({ isOpened, setIsOpened }: ISelectRelationshipDialogProps) => {
    const { model: card } = ModelRegistry.ProjectCard.useContext<IBoardColumnCardContextParams>();
    const { selectCardViewType, selectedRelationshipUIDs, setCardSelection } = useBoardController();
    const { globalRelationshipTypes } = useBoard();
    const [t] = useTranslation();
    const currentSelectedRelationshipUID = selectedRelationshipUIDs.find(([selectedCardUID]) => selectedCardUID === card.uid)?.[1];
    const [selectedRelationshipUID, setSelectedRelationshipUID] = useState(currentSelectedRelationshipUID);
    const selectedRelationshipUIDRef = useRef(currentSelectedRelationshipUID);
    const isParent = selectCardViewType === "parents";

    useEffect(() => {
        selectedRelationshipUIDRef.current = currentSelectedRelationshipUID;
        setSelectedRelationshipUID(currentSelectedRelationshipUID);
    }, [currentSelectedRelationshipUID]);

    if (!selectCardViewType) {
        return null;
    }

    const changeIsOpened = (isOpened: bool) => {
        setCardSelection(card.uid, selectedRelationshipUIDRef.current);
        setIsOpened(isOpened);
    };

    const changeIsOpenedWithoutSave = (isOpened: bool) => {
        selectedRelationshipUIDRef.current = currentSelectedRelationshipUID;
        setSelectedRelationshipUID(currentSelectedRelationshipUID);
        setIsOpened(isOpened);
    };

    const updateSelectedRelationshipUID = (nextRelationshipUID?: string) => {
        selectedRelationshipUIDRef.current = nextRelationshipUID;
        setSelectedRelationshipUID(nextRelationshipUID);
    };

    return (
        <Dialog.Root open={isOpened} onOpenChange={changeIsOpenedWithoutSave}>
            <Dialog.Content aria-describedby="" withCloseButton={false}>
                <Dialog.Title hidden />
                <Dialog.Description hidden />
                <Flex items="center" justify="between" textSize="base" weight="semibold" className="border-b" pb="3">
                    {card.title}
                </Flex>
                <ScrollArea.Root className="border">
                    <Flex direction="col" position="relative" textSize="sm" className="h-[min(theme(spacing.48),35vh)] select-none">
                        <RelationshipTypePicker
                            types={globalRelationshipTypes}
                            selectedUid={selectedRelationshipUID}
                            isParent={isParent}
                            onSelect={(uid) => updateSelectedRelationshipUID(selectedRelationshipUID === uid ? undefined : uid)}
                        />
                    </Flex>
                </ScrollArea.Root>
                <Flex items="center" justify="end" gap="1" mt="2">
                    {!!selectedRelationshipUID && (
                        <Button type="button" size="sm" variant="destructive" onClick={() => updateSelectedRelationshipUID(undefined)}>
                            {t("common.Clear")}
                        </Button>
                    )}
                    <Button type="button" size="sm" variant="secondary" onClick={() => changeIsOpenedWithoutSave(false)}>
                        {t("common.Cancel")}
                    </Button>
                    <Button type="button" size="sm" onClick={() => changeIsOpened(false)}>
                        {t("common.Save")}
                    </Button>
                </Flex>
            </Dialog.Content>
        </Dialog.Root>
    );
});
SelectRelationshipDialog.displayName = "Board.SelectRelationshipDialog";

export default SelectRelationshipDialog;
