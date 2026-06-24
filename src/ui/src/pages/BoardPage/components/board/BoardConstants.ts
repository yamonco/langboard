import { TColumnRowSettings, TColumnRowSymbolSet } from "@/core/helpers/dnd/types";
import { ProjectCardRelationship } from "@/core/models";

export interface IBoardColumnCardContextParams {
    setFilters: (relationshipType: ProjectCardRelationship.TRelationship) => void;
}

export const BOARD_DND_SETTINGS: TColumnRowSettings = {
    isMoreObvious: false,
    isOverElementAutoScrollEnabled: true,
    rootScrollSpeed: "fast" as const,
    columnScrollSpeed: "standard" as const,
    isFPSPanelEnabled: false,
    isCPUBurnEnabled: false,
    isOverflowScrollingEnabled: true,
};

export const BOARD_DND_SYMBOL_SET: TColumnRowSymbolSet = {
    column: Symbol("column"),
    columnDroppable: Symbol("column-drop-target"),
    row: Symbol("card"),
    rowDroppable: Symbol("card-drop-target"),
};

export const BLOCK_BOARD_PANNING_ATTR = "data-block-board-panning" as const;
export const BOARD_CARD_TOUCH_DND_ATTR = "data-board-card-touch-dnd-uid" as const;
export const BOARD_COLUMN_TOUCH_DND_ATTR = "data-board-column-touch-dnd-uid" as const;

export const BOARD_COLUMN_MAX_HEIGHT_CLASS_NAMES =
    "max-h-[calc(100dvh_-_theme(spacing.28)_-_theme(spacing.2)_-_theme(spacing.16)_-_theme(spacing.10))]";
