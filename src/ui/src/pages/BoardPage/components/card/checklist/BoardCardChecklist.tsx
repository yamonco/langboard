import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Collapsible from "@/components/base/Collapsible";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Tooltip from "@/components/base/Tooltip";
import { ProjectChecklist, ProjectCheckitem } from "@/core/models";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { cn } from "@/core/utils/ComponentUtils";
import BoardCardChecklistAddItem from "@/pages/BoardPage/components/card/checklist/BoardCardChecklistAddItem";
import BoardCardChecklistCheckbox from "@/pages/BoardPage/components/card/checklist/BoardCardChecklistCheckbox";
import BoardCardChecklistMoreMenu from "@/pages/BoardPage/components/card/checklist/BoardCardChecklistMoreMenu";
import BoardCardChecklistNotify from "@/pages/BoardPage/components/card/checklist/BoardCardChecklistNotify";
import BoardCardCheckitem from "@/pages/BoardPage/components/card/checklist/BoardCardCheckitem";
import { memo, useEffect, useReducer, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import invariant from "tiny-invariant";
import { columnRowDndHelpers } from "@/core/helpers/dnd";
import { BOARD_CARD_CHECK_DND_SETTINGS, BOARD_CARD_CHECK_DND_SYMBOL_SET } from "@/pages/BoardPage/components/card/checklist/BoardCardCheckConstants";
import { DropIndicator } from "@atlaskit/pragmatic-drag-and-drop-react-drop-indicator/box";
import { TColumnState } from "@/core/helpers/dnd/types";
import { COLUMN_IDLE } from "@/core/helpers/dnd/createDndColumnEvents";
import useRowReordered from "@/core/hooks/useRowReordered";
import { Utils } from "@langboard/core/utils";
import { ProjectRole } from "@/core/models/roles";

export interface IBoardCardChecklistProps {
    checklist: ProjectChecklist.TModel;
    checkitemsMap: Record<string, ProjectCheckitem.TModel>;
}

const stateStyles: { [Key in TColumnState["type"]]: string } = {
    idle: "",
    "is-row-over": "ring-2 ring-primary",
    "is-dragging": "opacity-40",
    "is-column-over": "",
};

const BoardCardChecklist = memo(({ checklist, checkitemsMap }: IBoardCardChecklistProps): React.JSX.Element => {
    const { viewportRef, hasRoleAction } = useBoardCard();
    const outerFullHeightRef = useRef<HTMLDivElement | null>(null);
    const draggableRef = useRef<HTMLButtonElement | null>(null);
    const [state, setState] = useState<TColumnState>(COLUMN_IDLE);
    const isOpenedInBoardCard = checklist.useField("isOpenedInBoardCard");
    const order = checklist.useField("order");
    const canReorder = hasRoleAction(ProjectRole.EAction.CardUpdate);

    useEffect(() => {
        if (!canReorder) {
            return;
        }

        const outer = outerFullHeightRef.current;
        const scrollable = viewportRef.current;
        const draggable = draggableRef.current;
        invariant(outer);
        invariant(scrollable);
        invariant(draggable);

        return columnRowDndHelpers.column({
            column: checklist,
            symbolSet: BOARD_CARD_CHECK_DND_SYMBOL_SET,
            draggable,
            dropTarget: outer,
            scrollable,
            settings: BOARD_CARD_CHECK_DND_SETTINGS,
            isIndicator: true,
            setState,
            renderPreview: ({ container }) => {
                // Simple drag preview generation: just cloning the current element.
                // Not using react for this.
                const rect = outer.getBoundingClientRect();
                const preview = outer.cloneNode(true);
                invariant(Utils.Type.isElement(preview, "div"));
                preview.style.width = `${rect.width}px`;
                preview.style.height = `${rect.height}px`;

                container.appendChild(preview);
            },
        });
    }, [checklist, order]);

    return (
        <Box my="2" position="relative" className={cn("snap-center", stateStyles[state.type])} ref={outerFullHeightRef}>
            {state.type === "is-column-over" && <DropIndicator edge={state.closestEdge} />}
            <Collapsible.Root
                open={isOpenedInBoardCard || state.type === "is-row-over"}
                onOpenChange={(opened) => {
                    checklist.isOpenedInBoardCard = opened;
                }}
            >
                <BoardCardChecklistDisplay checklist={checklist} draggableRef={draggableRef} canReorder={canReorder} />
                <BoardCardCheckitemList checklist={checklist} checkitemsMap={checkitemsMap} />
            </Collapsible.Root>
        </Box>
    );
});

interface IBaordCardChecklistDisplayProps {
    checklist: ProjectChecklist.TModel;
    draggableRef: React.RefObject<HTMLButtonElement | null>;
    canReorder: bool;
}

const BoardCardChecklistDisplay = memo(({ checklist, draggableRef, canReorder }: IBaordCardChecklistDisplayProps) => {
    const { sharedClassNames } = useBoardCard();
    const [t] = useTranslation();
    const [isValidating, setIsValidating] = useState(false);
    const [isTitleOpened, setIsTitleOpened] = useState(false);
    const title = checklist.useField("title");
    const isChecked = checklist.useField("is_checked");
    const isOpenedInBoardCard = checklist.useField("isOpenedInBoardCard");

    return (
        <ModelRegistry.ProjectChecklist.Provider model={checklist} params={{ canEdit: canReorder, isValidating, setIsValidating }}>
            <Flex
                items="center"
                justify="between"
                gap="2"
                h={{
                    initial: "16",
                    md: "12",
                }}
                w="full"
                mr="1"
                className="truncate"
            >
                <Flex items="center" gap="2" w="full" className="truncate">
                    <Flex items="center" gap="1">
                        {canReorder && (
                            <>
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon-sm"
                                    className="h-8 w-5 sm:size-8"
                                    title={t("common.Drag to reorder")}
                                    disabled={isValidating}
                                    ref={draggableRef}
                                >
                                    <IconComponent icon="grip-vertical" size="4" />
                                </Button>
                                <BoardCardChecklistCheckbox key={`board-card-checklist-checkbox-${checklist.uid}`} />
                                <BoardCardChecklistNotify key={`board-card-checklist-notify-${checklist.uid}`} />
                            </>
                        )}
                        <Collapsible.Trigger asChild>
                            <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                className="h-8 w-6 transition-all sm:size-8 [&[data-state=open]>svg]:rotate-180"
                                title={t(`common.${isOpenedInBoardCard ? "Collapse" : "Expand"}`)}
                                aria-label={t(`common.${isOpenedInBoardCard ? "Collapse" : "Expand"}`)}
                            >
                                <IconComponent icon="chevron-down" size="4" />
                            </Button>
                        </Collapsible.Trigger>
                    </Flex>
                    <Flex
                        direction={{
                            initial: "col",
                            md: "row",
                        }}
                        items={{
                            md: "center",
                        }}
                        gap="0.5"
                        w="full"
                        className="truncate"
                    >
                        <Tooltip.Root open={isTitleOpened} onOpenChange={setIsTitleOpened}>
                            <Tooltip.Trigger asChild onClick={() => setIsTitleOpened(!isTitleOpened)}>
                                <span className={cn("truncate", isChecked && "text-muted-foreground/70 line-through")}>{title}</span>
                            </Tooltip.Trigger>
                            <Tooltip.Content className={sharedClassNames.popoverContent}>{title}</Tooltip.Content>
                        </Tooltip.Root>
                    </Flex>
                </Flex>
                <Flex items="center" gap="1.5">
                    {canReorder && (
                        <>
                            <BoardCardChecklistAddItem key={`board-card-checklist-add-item-${checklist.uid}`} />
                            <BoardCardChecklistMoreMenu key={`board-card-checklist-more-${checklist.uid}`} />
                        </>
                    )}
                </Flex>
            </Flex>
        </ModelRegistry.ProjectChecklist.Provider>
    );
});

interface IBoardCardCheckitemListProps {
    checklist: ProjectChecklist.TModel;
    checkitemsMap: Record<string, ProjectCheckitem.TModel>;
}

const BoardCardCheckitemList = memo(({ checklist, checkitemsMap }: IBoardCardCheckitemListProps) => {
    const { card, socket } = useBoardCard();
    const updater = useReducer((x) => x + 1, 0);
    const checklistCheckitems = checklist.useForeignFieldArray("checkitems");
    const checklistCheckitemUIDs = checklistCheckitems.map((checkitem) => checkitem.uid).join(",");
    const { rows: checkitems } = useRowReordered({
        type: "ProjectCheckitem",
        topicId: card.uid,
        eventNameParams: { uid: checklist.uid },
        rowFilter: (model) => {
            if (!checkitemsMap[model.uid]) {
                checkitemsMap[model.uid] = model;
            }
            return model.checklist_uid === checklist.uid;
        },
        rowDependencies: [checklist, checklistCheckitemUIDs],
        columnUID: checklist.uid,
        socket,
        updater,
    });

    return (
        <Collapsible.Content className="text-sm transition-all data-[state=closed]:animate-collapse-up data-[state=open]:animate-collapse-down">
            {checkitems.map((checkitem) => (
                <BoardCardCheckitem key={`board-checklist-${checklist.uid}-${checkitem.uid}`} checkitem={checkitem} />
            ))}
        </Collapsible.Content>
    );
});

export default BoardCardChecklist;
