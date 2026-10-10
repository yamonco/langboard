import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Popover from "@/components/base/Popover";
import Toast from "@/components/base/Toast";
import useUpdateCardRelationships from "@/controllers/api/card/useUpdateCardRelationships";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { ProjectCardRelationship } from "@/core/models";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { useBoardController } from "@/core/providers/BoardController";
import { cn } from "@/core/utils/ComponentUtils";
import BoardCardActionRelationshipList from "@/pages/BoardPage/components/card/action/relationship/BoardCardActionRelationshipList";
import { ISharedBoardCardActionProps } from "@/pages/BoardPage/components/card/action/types";
import { useState } from "react";
import { useTranslation } from "react-i18next";

export interface IBoardCardActionRelationshipButtonProps extends ISharedBoardCardActionProps {
    type: ProjectCardRelationship.TRelationship;
    relationships: ProjectCardRelationship.TModel[];
    isExpanded?: bool;
}

function BoardCardActionRelationshipButton({ type, relationships, buttonClassName, isExpanded = false }: IBoardCardActionRelationshipButtonProps) {
    const { selectCardViewType, disabledCardSelectionUIDsRef, startCardSelection, filterRelationships } = useBoardController();
    const { projectUID, card } = useBoardCard();
    const [isOpened, setIsOpened] = useState(false);
    const [isValidating, setIsValidating] = useState(false);
    const { mutateAsync: updateCardRelationshipsMutateAsync } = useUpdateCardRelationships({ interceptToast: true });
    const [t] = useTranslation();
    const isParent = type === "parents";

    const saveRelationship = (newRelationships: [string, string][]) => {
        setIsOpened(true);
        setIsValidating(true);

        const promise = updateCardRelationshipsMutateAsync({
            project_uid: projectUID,
            card_uid: card.uid,
            is_parent: isParent,
            relationships: newRelationships,
        });

        Toast.Add.promise(promise, {
            loading: t("common.Updating..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler({}, messageRef);

                handle(error);
                return messageRef.message;
            },
            success: () => {
                return t("successes.Relationships updated successfully.");
            },
            finally: () => {
                setIsValidating(() => false);
            },
        });
    };

    const selectRelationship = () => {
        const initialSelections = filterRelationships(card.uid, relationships, isParent).map(
            (relationship) =>
                [isParent ? relationship.parent_card_uid : relationship.child_card_uid, relationship.relationship_type_uid] satisfies [string, string]
        );

        setIsOpened(false);
        // Reverse composition/reference edges are valid; the server rejects only blocks cycles.
        disabledCardSelectionUIDsRef.current = [card.uid];
        startCardSelection({
            type,
            currentUID: card.uid,
            initialSelections,
            saveCallback: saveRelationship,
            cancelCallback: () => setIsOpened(true),
        });
    };

    const title = t(`card.${type === "parents" ? "Parent" : "Child"} cards`);

    return (
        <Popover.Root open={isOpened} onOpenChange={setIsOpened}>
            <Popover.Trigger asChild>
                <Button
                    type="button"
                    variant={{ initial: "secondary", sm: "default" }}
                    size="icon"
                    title={title}
                    className={cn(
                        buttonClassName,
                        "transition-transform duration-200 sm:z-[120] sm:rounded-full",
                        isExpanded ? "sm:relative sm:size-9" : "sm:absolute sm:top-1/2 sm:size-10 sm:-translate-y-1/2",
                        !isExpanded && isParent && "sm:-left-5",
                        !isExpanded && !isParent && "sm:-right-5"
                    )}
                >
                    <IconComponent icon="git-fork" className={cn("size-4 sm:size-6", isParent ? "" : "rotate-180")} />
                    <Box display={{ sm: "hidden" }}>{title}</Box>
                </Button>
            </Popover.Trigger>
            <Popover.Content className="p-0" hidden={!!selectCardViewType}>
                <Flex items="center" justify="between" textSize="base" weight="semibold" className="border-b" pl="4" mr="1" py="1">
                    {title}
                    <Button variant="ghost" size="icon-sm" disabled={isValidating} onClick={() => setIsOpened(false)}>
                        <IconComponent icon="x" size="5" />
                    </Button>
                </Flex>
                <Box pb="3" pt="2" px="4">
                    <BoardCardActionRelationshipList type={type} relationships={relationships} />
                    <Flex items="center" justify="end" gap="1" mt="2">
                        <Button type="button" size="sm" disabled={isValidating} onClick={selectRelationship}>
                            {t("card.Select cards")}
                        </Button>
                    </Flex>
                </Box>
            </Popover.Content>
        </Popover.Root>
    );
}

export default BoardCardActionRelationshipButton;
