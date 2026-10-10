/* eslint-disable quotes */

/* eslint-disable @/max-len */
"use client";

import * as React from "react";
import { BlockSelectionPlugin, useBlockSelected } from "@platejs/selection/react";
import { TablePlugin, TableProvider, useTableCellElement, useTableElement, useTableMergeState } from "@platejs/table/react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, CombineIcon, GripVertical, SquareSplitHorizontalIcon, Trash2Icon, XIcon } from "lucide-react";
import { type TTableCellElement, type TTableElement, type TTableRowElement, KEYS, PathApi, TElement } from "platejs";
import {
    type PlateElementProps,
    PlateElement,
    useComposedRef,
    useEditorPlugin,
    useEditorRef,
    useEditorSelector,
    useElement,
    useFocusedLast,
    usePluginOption,
    useReadOnly,
    useRemoveNodeButton,
    useSelected,
    withHOC,
} from "platejs/react";
import { useElementSelector } from "platejs/react";
import Button from "@/components/base/Button";
import Popover from "@/components/base/Popover";
import { cn } from "@/core/utils/ComponentUtils";
import { blockSelectionVariants } from "@/components/plate-ui/block-selection";
import { Toolbar, ToolbarButton, ToolbarGroup } from "@/components/plate-ui/toolbar";
import { useTranslation } from "react-i18next";
import { useDraggable, useDropLine } from "@platejs/dnd";

export const TableElement = withHOC(TableProvider, function TableElement({ children, ...props }: PlateElementProps<TTableElement>) {
    const readOnly = useReadOnly();
    const isSelectionAreaVisible = usePluginOption(BlockSelectionPlugin, "isSelectionAreaVisible");
    const hasControls = !readOnly && !isSelectionAreaVisible;
    const { marginLeft, props: tableProps } = useTableElement();
    const isSelectingCell = useEditorSelector((editor) => editor.getApi(TablePlugin).table.isSelectingCell(), []);

    const isSelectingTable = useBlockSelected(props.element.id as string);

    const content = (
        <PlateElement
            {...props}
            className={cn("overflow-x-auto py-5", hasControls && "-ml-2 *:data-[slot=block-selection]:left-2")}
            style={{ paddingLeft: marginLeft }}
        >
            <div className="group/table relative w-fit">
                <table
                    className={cn(
                        "ml-2 mr-0 table h-px w-[calc(100%_-_theme(spacing.2))] table-fixed border-collapse",
                        isSelectingCell && "selection:bg-transparent"
                    )}
                    {...tableProps}
                >
                    <tbody className="min-w-full">{children}</tbody>
                </table>

                {isSelectingTable && <div className={blockSelectionVariants()} contentEditable={false} />}
            </div>
        </PlateElement>
    );

    if (readOnly) {
        return content;
    }

    return <TableFloatingToolbar>{content}</TableFloatingToolbar>;
});

function TableFloatingToolbar({ children, ...props }: React.ComponentProps<typeof Popover.Content>) {
    const [t] = useTranslation();
    const { tf } = useEditorPlugin(TablePlugin);
    const selected = useSelected();
    const element = useElement<TTableElement>();
    const { props: buttonProps } = useRemoveNodeButton({ element });
    const singleCellInside = useEditorSelector(
        (editor) => selected && (editor.getApi(TablePlugin).table.getSelectedCellIds()?.length ?? 0) === 0,
        [selected]
    );
    const isFocusedLast = useFocusedLast();

    const { canMerge, canSplit } = useTableMergeState();

    return (
        <Popover.Root open={isFocusedLast && (canMerge || canSplit || singleCellInside)} modal={false}>
            <Popover.Anchor asChild>{children}</Popover.Anchor>
            <Popover.Content asChild onOpenAutoFocus={(e) => e.preventDefault()} contentEditable={false} {...props}>
                <Toolbar
                    className="flex w-auto max-w-[80vw] flex-row overflow-x-auto rounded-md border bg-popover p-1 shadow-md scrollbar-hide print:hidden"
                    contentEditable={false}
                >
                    <ToolbarGroup>
                        {canMerge && (
                            <ToolbarButton onClick={() => tf.table.merge()} onMouseDown={(e) => e.preventDefault()} tooltip={t("editor.Merge cells")}>
                                <CombineIcon className="size-4" />
                            </ToolbarButton>
                        )}
                        {canSplit && (
                            <ToolbarButton onClick={() => tf.table.split()} onMouseDown={(e) => e.preventDefault()} tooltip={t("editor.Split cells")}>
                                <SquareSplitHorizontalIcon className="size-4" />
                            </ToolbarButton>
                        )}
                        {singleCellInside && (
                            <ToolbarButton tooltip={t("editor.Delete table")} {...buttonProps}>
                                <Trash2Icon className="size-4" />
                            </ToolbarButton>
                        )}
                    </ToolbarGroup>

                    {singleCellInside && (
                        <ToolbarGroup>
                            <ToolbarButton
                                onClick={() => {
                                    tf.insert.tableRow({ before: true });
                                }}
                                onMouseDown={(e) => e.preventDefault()}
                                tooltip={t("editor.Insert row before")}
                                aria-label={t("editor.Insert row before")}
                            >
                                <ArrowUp className="size-4" />
                            </ToolbarButton>
                            <ToolbarButton
                                onClick={() => {
                                    tf.insert.tableRow();
                                }}
                                onMouseDown={(e) => e.preventDefault()}
                                tooltip={t("editor.Insert row after")}
                                aria-label={t("editor.Insert row after")}
                            >
                                <ArrowDown className="size-4" />
                            </ToolbarButton>
                            <ToolbarButton
                                onClick={() => {
                                    tf.remove.tableRow();
                                }}
                                onMouseDown={(e) => e.preventDefault()}
                                tooltip={t("editor.Delete row")}
                                aria-label={t("editor.Delete row")}
                            >
                                <XIcon className="size-4" />
                            </ToolbarButton>
                        </ToolbarGroup>
                    )}

                    {singleCellInside && (
                        <ToolbarGroup>
                            <ToolbarButton
                                onClick={() => {
                                    tf.insert.tableColumn({ before: true });
                                }}
                                onMouseDown={(e) => e.preventDefault()}
                                tooltip={t("editor.Insert column before")}
                                aria-label={t("editor.Insert column before")}
                            >
                                <ArrowLeft className="size-4" />
                            </ToolbarButton>
                            <ToolbarButton
                                onClick={() => {
                                    tf.insert.tableColumn();
                                }}
                                onMouseDown={(e) => e.preventDefault()}
                                tooltip={t("editor.Insert column after")}
                                aria-label={t("editor.Insert column after")}
                            >
                                <ArrowRight className="size-4" />
                            </ToolbarButton>
                            <ToolbarButton
                                onClick={() => {
                                    tf.remove.tableColumn();
                                }}
                                onMouseDown={(e) => e.preventDefault()}
                                tooltip={t("editor.Delete column")}
                                aria-label={t("editor.Delete column")}
                            >
                                <XIcon className="size-4" />
                            </ToolbarButton>
                        </ToolbarGroup>
                    )}
                </Toolbar>
            </Popover.Content>
        </Popover.Root>
    );
}

export function TableRowElement(props: PlateElementProps<TTableRowElement>) {
    const { element } = props;
    const readOnly = useReadOnly();
    const selected = useSelected();
    const editor = useEditorRef();
    const isSelectionAreaVisible = usePluginOption(BlockSelectionPlugin, "isSelectionAreaVisible");
    const hasControls = !readOnly && !isSelectionAreaVisible;

    const { isDragging, nodeRef, previewRef, handleRef } = useDraggable({
        element,
        type: element.type,
        canDropNode: ({ dragEntry, dropEntry }) => !!dragEntry && PathApi.equals(PathApi.parent(dragEntry[1]), PathApi.parent(dropEntry[1])),
        onDropHandler: (_, { dragItem }) => {
            const dragElement = (dragItem as { element: TElement }).element;

            if (dragElement) {
                editor.tf.select(dragElement);
            }
        },
    });

    return (
        <PlateElement
            {...props}
            ref={useComposedRef(props.ref, previewRef, nodeRef)}
            as="tr"
            className={cn("group/row", isDragging && "opacity-50")}
            attributes={{
                ...props.attributes,
                "data-selected": selected ? "true" : undefined,
            }}
        >
            {hasControls && (
                <td className="w-2 select-none" contentEditable={false}>
                    <RowDragHandle dragRef={handleRef} />
                    <RowDropLine />
                </td>
            )}

            {props.children}
        </PlateElement>
    );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function RowDragHandle({ dragRef }: { dragRef: React.Ref<any> }) {
    const editor = useEditorRef();
    const element = useElement();

    return (
        <Button
            ref={dragRef}
            variant="outline"
            className={cn(
                "z-51 absolute left-0 top-1/2 h-6 w-4 -translate-y-1/2 p-0 focus-visible:ring-0 focus-visible:ring-offset-0",
                "cursor-grab active:cursor-grabbing",
                'group-has-data-[resizing="true"]/row:opacity-0 opacity-0 transition-opacity duration-100 group-hover/row:opacity-100'
            )}
            onClick={() => {
                editor.tf.select(element);
            }}
        >
            <GripVertical className="text-muted-foreground" />
        </Button>
    );
}

function RowDropLine() {
    const { dropLine } = useDropLine();

    if (!dropLine) return null;

    return <div className={cn("absolute inset-x-0 left-2 z-50 h-0.5 bg-brand/50", dropLine === "top" ? "-top-px" : "-bottom-px")} />;
}

export function TableCellElement({
    isHeader,
    ...props
}: PlateElementProps<TTableCellElement> & {
    isHeader?: bool;
}) {
    const { api } = useEditorPlugin(TablePlugin);
    const readOnly = useReadOnly();
    const element = props.element;

    const tableId = useElementSelector(([node]) => node.id as string, [], {
        key: KEYS.table,
    });
    const rowId = useElementSelector(([node]) => node.id as string, [], {
        key: KEYS.tr,
    });
    const isSelectingTable = useBlockSelected(tableId);
    const isSelectingRow = useBlockSelected(rowId) || isSelectingTable;
    const isSelectionAreaVisible = usePluginOption(BlockSelectionPlugin, "isSelectionAreaVisible");

    const { borders, colIndex, minHeight, selected, width } = useTableCellElement();

    return (
        <PlateElement
            {...props}
            as={isHeader ? "th" : "td"}
            className={cn(
                "h-full overflow-visible border-none p-0",
                isHeader && "text-left *:m-0",
                "before:size-full",
                selected && "before:z-10 before:bg-brand/5",
                "before:absolute before:box-border before:select-none before:content-['']",
                borders.bottom?.size && "before:border-b before:border-b-border",
                borders.right?.size && "before:border-r before:border-r-border",
                borders.left?.size && "before:border-l before:border-l-border",
                borders.top?.size && "before:border-t before:border-t-border"
            )}
            style={
                {
                    "--cellBackground": element.background,
                    maxWidth: width,
                    minWidth: width,
                } as React.CSSProperties
            }
            attributes={{
                ...props.attributes,
                colSpan: api.table.getColSpan(element),
                rowSpan: api.table.getRowSpan(element),
            }}
        >
            <div className="relative z-20 box-border h-full px-3 py-2" style={{ minHeight }}>
                {props.children}
            </div>

            {!isSelectionAreaVisible && (
                <div className="group absolute top-0 size-full select-none" contentEditable={false} suppressContentEditableWarning={true}>
                    {!readOnly && (
                        <>
                            <div className={cn("absolute top-0 z-30 hidden h-full w-1 bg-ring", "right-[-1.5px]")} />
                            {colIndex === 0 && (
                                <div
                                    className={cn(
                                        "absolute top-0 z-30 h-full w-1 bg-ring",
                                        "left-[-1.5px]",
                                        'hidden animate-in fade-in group-has-[[data-resizer-left]:hover]/table:block group-has-[[data-resizer-left][data-resizing="true"]]/table:block'
                                    )}
                                />
                            )}
                        </>
                    )}
                </div>
            )}

            {isSelectingRow && <div className={blockSelectionVariants()} contentEditable={false} />}
        </PlateElement>
    );
}

export function TableCellHeaderElement(props: React.ComponentProps<typeof TableCellElement>) {
    return <TableCellElement {...props} isHeader />;
}
