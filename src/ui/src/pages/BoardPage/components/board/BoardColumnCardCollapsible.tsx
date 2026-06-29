import Button from "@/components/base/Button";
import Card from "@/components/base/Card";
import Collapsible from "@/components/base/Collapsible";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import ShineBorder from "@/components/base/ShineBorder";
import { UserAvatarList } from "@/components/UserAvatarList";
import { DISABLE_DRAGGING_ATTR } from "@/constants";
import { useBoardController } from "@/core/providers/BoardController";
import { useBoard } from "@/core/providers/BoardProvider";
import { ROUTES } from "@/core/routing/constants";
import { cn } from "@/core/utils/ComponentUtils";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import SelectRelationshipDialog from "@/pages/BoardPage/components/board/SelectRelationshipDialog";
import BoardColumnCardRelationship from "@/pages/BoardPage/components/board/BoardColumnCardRelationship";
import { LabelModelBadge } from "@/components/LabelBadge";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { IBoardColumnCardContextParams } from "@/pages/BoardPage/components/board/BoardConstants";
import useCardStore, { useCardIsCollapsed } from "@/core/stores/CardStore";
import { useHasRunningBot } from "@/core/stores/BotStatusStore";
import BoardGraphApprovalTargetBadge from "@/pages/BoardPage/components/board/BoardGraphApprovalTargetBadge";
import { EGraphApprovalScopeTable } from "@/core/models/GraphApprovalRequestModel";
import BoardTaskMetadataBadges from "@/pages/BoardPage/components/task/BoardTaskMetadataBadges";

export interface IBoardColumnCardCollapsibleProps {
    isDragging: bool;
}

function BoardColumnCardCollapsible({ isDragging }: IBoardColumnCardCollapsibleProps) {
    const { selectCardViewType, selectedRelationshipUIDs, currentCardUIDRef, isDisabledCard } = useBoardController();
    const { project, filters, cardsMap, globalRelationshipTypes, navigateWithFilters } = useBoard();
    const [t] = useTranslation();
    const { model: card } = ModelRegistry.ProjectCard.useContext<IBoardColumnCardContextParams>();
    const title = card.useField("title");
    const projectMembers = project.useForeignFieldArray("all_members");
    const cardMemberUIDs = card.useField("member_uids") ?? [];
    const cardMembers = useMemo(
        () => projectMembers.filter((member) => member.isValidUser() && cardMemberUIDs.includes(member.uid)),
        [projectMembers, cardMemberUIDs]
    );
    const commentCount = card.useField("count_comment");
    const { updateCollapsed } = useCardStore();
    const isCollapsed = useCardIsCollapsed(card.uid);
    const labels = card.useForeignFieldArray("labels");
    const cardRelationships = card.useForeignFieldArray("relationships");
    const hasRunningBot = useHasRunningBot({ type: "card", targetUID: card.uid });
    const [isSelectRelationshipDialogOpened, setIsSelectRelationshipDialogOpened] = useState(false);
    const selectedRelationship = useMemo(
        () => (selectCardViewType ? selectedRelationshipUIDs.find(([selectedCardUID]) => selectedCardUID === card.uid)?.[1] : undefined),
        [card, selectCardViewType, selectedRelationshipUIDs]
    );
    const openCard = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            if ((e.target as HTMLElement)?.closest?.(`[${DISABLE_DRAGGING_ATTR}]`)) {
                return;
            }

            if (selectCardViewType) {
                if (isDisabledCard(card.uid)) {
                    return;
                }

                setIsSelectRelationshipDialogOpened(true);
                return;
            }

            if (isDragging) {
                return;
            }

            navigateWithFilters(ROUTES.BOARD.CARD(project.uid, card.uid));
        },
        [card, isDragging, isDisabledCard, navigateWithFilters, project, selectCardViewType]
    );

    const handleOpenCollapsible = useCallback(
        (e: React.MouseEvent<HTMLButtonElement>) => {
            e.preventDefault();
            e.stopPropagation();
            updateCollapsed(card.uid, !isCollapsed);
        },
        [card, isCollapsed, updateCollapsed]
    );
    const presentableRelationships = useMemo(() => {
        const relationships: [string, string][] = [];

        const filteredRelationships = cardRelationships.filter((relationship) => {
            if (!globalRelationshipTypes.length) {
                return false;
            }

            if (filters.parents) {
                return filters.parents.includes(relationship.child_card_uid);
            } else if (filters.children) {
                return filters.children.includes(relationship.parent_card_uid);
            } else {
                return false;
            }
        });

        const selectedRelationshipType = selectedRelationship
            ? globalRelationshipTypes.find((relationship) => relationship.uid === selectedRelationship)
            : undefined;

        for (let i = 0; i < filteredRelationships.length; ++i) {
            const relationship = filteredRelationships[i];
            const relationshipType = relationship.relationship_type;
            if (relationshipType) {
                const isParent = relationship.parent_card_uid === card.uid;
                const oppositeCard = cardsMap[isParent ? relationship.child_card_uid : relationship.parent_card_uid];
                if (!oppositeCard) {
                    continue;
                }
                relationships.push([oppositeCard.title, isParent ? relationshipType.child_name : relationshipType.parent_name]);
            }
        }

        if (selectedRelationshipType && currentCardUIDRef.current && cardsMap[currentCardUIDRef.current]) {
            const isParent = selectCardViewType === "parents";
            relationships.push([
                cardsMap[currentCardUIDRef.current].title,
                isParent ? selectedRelationshipType.parent_name : selectedRelationshipType.child_name,
            ]);
        }

        return relationships;
    }, [card, cardsMap, cardRelationships, filters, globalRelationshipTypes, selectCardViewType, selectedRelationship]);

    useEffect(() => {
        if (selectCardViewType && selectedRelationship) {
            updateCollapsed(card.uid, false);
        }
    }, [card, selectCardViewType, selectedRelationship, updateCollapsed]);

    useEffect(() => {
        if (presentableRelationships.length) {
            updateCollapsed(card.uid, false);
        }
    }, [card, filters, presentableRelationships.length, updateCollapsed]);

    const attributes = {
        [DISABLE_DRAGGING_ATTR]: "",
    };

    return (
        <>
            <Card.Root
                id={`board-card-${card.uid}`}
                className={cn(
                    "relative hover:border-primary",
                    !!selectCardViewType && isDisabledCard(card.uid) ? "cursor-not-allowed" : "cursor-pointer"
                )}
                onClick={openCard}
            >
                {hasRunningBot && <ShineBorder className="z-50" />}
                <Collapsible.Root
                    open={!isCollapsed}
                    onOpenChange={(opened) => {
                        updateCollapsed(card.uid, !opened);
                    }}
                >
                    <Card.Header className="relative block space-y-0 py-4">
                        {!isCollapsed && !!labels.length && (
                            <Flex items="center" gap="1" mb="1.5" wrap>
                                {labels.map((label) => (
                                    <LabelModelBadge key={`board-card-label-${label.uid}`} model={label} />
                                ))}
                            </Flex>
                        )}
                        {!isCollapsed && <BoardTaskMetadataBadges cardUID={card.uid} compact className="mb-1.5" />}
                        <Card.Title className="max-w-[calc(100%_-_theme(spacing.8))] break-all leading-tight">{title}</Card.Title>
                        <BoardGraphApprovalTargetBadge
                            projectUID={project.uid}
                            scopeTable={EGraphApprovalScopeTable.Card}
                            scopeUID={card.uid}
                            className="absolute right-11 top-3"
                        />
                        <Button
                            variant="ghost"
                            className={cn("absolute right-2.5 top-2.5 mt-0")}
                            size="icon-sm"
                            title={t(`common.${!isCollapsed ? "Collapse" : "Expand"}`)}
                            titleSide="top"
                            onClick={handleOpenCollapsible}
                            {...attributes}
                        >
                            <IconComponent icon="chevron-down" size="4" className={cn("transition-all", !isCollapsed && "rotate-180")} />
                        </Button>
                    </Card.Header>
                    <Collapsible.Content
                        className={cn(
                            "overflow-hidden text-sm transition-all",
                            "data-[state=closed]:animate-collapse-up data-[state=open]:animate-collapse-down"
                        )}
                    >
                        {!!presentableRelationships.length && (
                            <Card.Content className="px-6 pb-4">
                                {presentableRelationships.map(([relatedCardTitle, relationshipName], index) => (
                                    <Flex
                                        key={`board-card-presentable-relationship-${card.uid}-${relationshipName}-${relatedCardTitle}-${index}`}
                                        items="center"
                                        gap="2"
                                        className="truncate text-accent-foreground/70"
                                    >
                                        <span>{relationshipName}</span>
                                        <span className="text-muted-foreground">&gt;</span>
                                        <span className="truncate">{relatedCardTitle}</span>
                                    </Flex>
                                ))}
                            </Card.Content>
                        )}
                        <BoardColumnCardRelationship attributes={attributes} />
                        <Card.Footer className="flex items-end justify-between gap-1.5 pb-4">
                            <Flex items="center" gap="2">
                                <IconComponent icon="message-square" size="4" className="text-secondary" strokeWidth="4" />
                                <span>{commentCount}</span>
                            </Flex>
                            <UserAvatarList
                                maxVisible={3}
                                userOrBots={cardMembers}
                                scope={{
                                    projectUID: project.uid,
                                    cardUID: card.uid,
                                }}
                                size="sm"
                                {...attributes}
                                className="cursor-default"
                            />
                        </Card.Footer>
                    </Collapsible.Content>
                </Collapsible.Root>
            </Card.Root>
            <SelectRelationshipDialog isOpened={isSelectRelationshipDialogOpened} setIsOpened={setIsSelectRelationshipDialogOpened} />
        </>
    );
}
BoardColumnCardCollapsible.displayName = "Board.ColumnCard.Collapsible";

export default BoardColumnCardCollapsible;
