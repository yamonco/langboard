import { draggable as draggableFn, dropTargetForElements } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import invariant from "tiny-invariant";
import { combine } from "@atlaskit/pragmatic-drag-and-drop/combine";
import { preserveOffsetOnSource } from "@atlaskit/pragmatic-drag-and-drop/element/preserve-offset-on-source";
import { setCustomNativeDragPreview } from "@atlaskit/pragmatic-drag-and-drop/element/set-custom-native-drag-preview";
import { TColumnData, TColumnDroppableTargetData, TColumnState, TColumnRowSettings, TColumnRowSymbolSet } from "@/core/helpers/dnd/types";
import createDndColumnRowDataHelper from "@/core/helpers/dnd/createDndColumnRowDataHelper";
import { attachClosestEdge, extractClosestEdge } from "@atlaskit/pragmatic-drag-and-drop-hitbox/closest-edge";
import { TOrderableModel, TOrderableModelName } from "@/core/models/ModelRegistry";
import { Utils } from "@langboard/core/utils";
import { autoScrollForElements } from "@/core/helpers/dnd/auto-scroll/entry-point/element";
import { unsafeOverflowAutoScrollForElements } from "@/core/helpers/dnd/auto-scroll/entry-point/unsafe-overflow/element";

export const COLUMN_IDLE = { type: "idle" } satisfies TColumnState;

export interface ICreateDndColumnEventsProps<TColumnModel extends TOrderableModel<TOrderableModelName>> {
    column: TColumnModel;
    symbolSet: TColumnRowSymbolSet;
    draggable: HTMLElement;
    dropTarget: HTMLElement;
    scrollable: HTMLElement;
    settings: TColumnRowSettings;
    isIndicator?: bool;
    canDrag?: boolean;
    setState: React.Dispatch<React.SetStateAction<TColumnState>>;
    renderPreview: Parameters<typeof setCustomNativeDragPreview>[0]["render"];
}

const createDndColumnEvents = <TColumnModel extends TOrderableModel<TOrderableModelName>>(props: ICreateDndColumnEventsProps<TColumnModel>) => {
    const { column, symbolSet, draggable, dropTarget, scrollable, settings, isIndicator, setState, renderPreview } = props;

    type TColumnModelData = TColumnData<TColumnModel>;
    type TColumnDroppableModelData = TColumnDroppableTargetData<TColumnModel>;

    const getColumnData = (context: TColumnModelData): TColumnModelData => {
        return {
            [symbolSet.column]: true,
            rect: context.rect,
            column: context.column,
        };
    };

    const getColumnDroppableTargetData = (context: TColumnDroppableModelData): TColumnDroppableModelData => {
        return {
            [symbolSet.columnDroppable]: true,
            column: context.column,
        };
    };

    const { isColumnData, isDraggingAColumn, isRowData, isDraggingARow, setIsRowOver, shouldHideIndicator } = createDndColumnRowDataHelper<
        TColumnModel,
        TOrderableModel<TOrderableModelName>
    >({
        symbolSet,
        setColumnState: setState,
    });

    return combine(
        draggableFn({
            element: draggable,
            canDrag: () => props.canDrag ?? true,
            getInitialData: ({ element }) => getColumnData({ column, rect: element.getBoundingClientRect() }),
            onGenerateDragPreview({ source, location, nativeSetDragImage }) {
                const data = source.data;
                invariant(isColumnData(data));
                setCustomNativeDragPreview({
                    nativeSetDragImage,
                    getOffset: preserveOffsetOnSource({ element: draggable, input: location.current.input }),
                    render: renderPreview,
                });
            },
            onDragStart() {
                setState({ type: "is-dragging" });
            },
            onDrop() {
                setState(COLUMN_IDLE);
            },
        }),
        dropTargetForElements({
            element: dropTarget,
            canDrop({ source }) {
                return isDraggingARow({ source }) || isDraggingAColumn({ source });
            },
            getIsSticky: () => true,
            getData: ({ element, input, source }) => {
                if (isRowData(source.data)) {
                    return getColumnData({ column, rect: element.getBoundingClientRect() });
                }

                const data = getColumnDroppableTargetData({ column });
                return attachClosestEdge(data, { element, input, allowedEdges: ["top", "bottom"] });
            },
            onDragStart({ source, location }) {
                if (isRowData(source.data)) {
                    setIsRowOver({ data: source.data, location });
                }
            },
            onDragEnter({ source, location, self }) {
                if (isRowData(source.data)) {
                    setIsRowOver({ data: source.data, location });
                    return;
                }

                if (!isColumnData(source.data)) {
                    setState({ type: "is-dragging" });
                    return;
                }

                if (source.data.column.uid === column.uid) {
                    return;
                }

                const closestEdge = extractClosestEdge(self.data);
                if (!closestEdge) {
                    return;
                }

                if (shouldHideIndicator(column.order, source.data.column.order, closestEdge)) {
                    // If the column is before or after the source, we don't want to show the "is-column-over" state.
                    setState(COLUMN_IDLE);
                    return;
                }

                setState({ type: "is-column-over", dragging: source.data.rect, closestEdge });
            },
            onDrag({ source, self }) {
                if (!isColumnData(source.data)) {
                    return;
                }

                if (source.data.column.uid === column.uid) {
                    setState({ type: "is-dragging" });
                    return;
                }

                const closestEdge = extractClosestEdge(self.data);
                if (!closestEdge) {
                    return;
                }

                if (isIndicator && shouldHideIndicator(column.order, source.data.column.order, closestEdge)) {
                    // If the column is before or after the source, we don't want to show the "is-column-over" state.
                    setState(COLUMN_IDLE);
                    return;
                }

                // optimization - Don't update react state if we don't need to.
                const proposed: TColumnState = { type: "is-column-over", dragging: source.data.rect, closestEdge };
                setState((current) => {
                    if (Utils.Object.isShallowEqual(proposed, current)) {
                        return current;
                    }
                    return proposed;
                });
            },
            onDropTargetChange({ source, location }) {
                if (isRowData(source.data)) {
                    setIsRowOver({ data: source.data, location });
                    return;
                }
            },
            onDragLeave() {
                setState(COLUMN_IDLE);
            },
            onDrop() {
                setState(COLUMN_IDLE);
            },
        }),
        autoScrollForElements({
            canScroll({ source }) {
                if (!settings.isOverElementAutoScrollEnabled) {
                    return false;
                }

                return isDraggingARow({ source });
            },
            getConfiguration: () => ({ maxScrollSpeed: settings.columnScrollSpeed }),
            element: scrollable,
        }),
        unsafeOverflowAutoScrollForElements({
            element: scrollable,
            getConfiguration: () => ({ maxScrollSpeed: settings.columnScrollSpeed }),
            canScroll({ source }) {
                if (!settings.isOverElementAutoScrollEnabled) {
                    return false;
                }

                if (!settings.isOverflowScrollingEnabled) {
                    return false;
                }

                return isDraggingARow({ source });
            },
            getOverflow() {
                return {
                    forTopEdge: {
                        top: 1000,
                    },
                    forBottomEdge: {
                        bottom: 1000,
                    },
                };
            },
        })
    );
};

export default createDndColumnEvents;
