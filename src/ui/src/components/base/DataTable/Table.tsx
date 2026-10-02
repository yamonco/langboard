/* eslint-disable @typescript-eslint/no-explicit-any */
import { useDataTable } from "@/components/base/DataTable/Provider";
import { TDataTableColumn } from "@/components/base/DataTable/types";
import Input from "@/components/base/Input";
import { cn } from "@/core/utils/ComponentUtils";
import { Utils } from "@langboard/core/utils";
import { ChevronDown, ChevronUp, Filter } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export type TDataTableTableProps<T> = {
    data: T[];
    columns: TDataTableColumn<T>[];
    searchable?: bool;
    showPagination?: bool;
    striped?: bool;
    hoverable?: bool;
    emptyMessage?: string;
    emptyIcon?: string | React.ReactNode;
    onRowClick?: (row: T) => void;
    variant?: "default" | "minimal";
    size?: "sm" | "default" | "lg";
};

function DataTableTable<T extends Record<string, any>>({
    data,
    columns,
    searchable,
    showPagination = true,
    striped = false,
    hoverable = true,
    emptyMessage,
    emptyIcon = "📊",
    onRowClick,
    variant = "default",
    size = "default",
}: TDataTableTableProps<T>) {
    const [t] = useTranslation();
    const { currentPage, itemsPerPage, sortConfig, searchText, columnFilters, paginate, setTotalRecords } = useDataTable();

    const filteredData = useMemo(() => {
        let filtered = [...data];

        // Global search
        if (searchText) {
            filtered = filtered.filter((row) =>
                columns.some((column) => {
                    const value = row[column.key];
                    return value?.toString().toLowerCase().includes(searchText.toLowerCase());
                })
            );
        }

        // Column filters
        Object.entries(columnFilters).forEach(([key, value]) => {
            if (value) {
                filtered = filtered.filter((row) => {
                    const rowValue = row[key as keyof T];
                    return rowValue?.toString().toLowerCase().includes(value.toLowerCase());
                });
            }
        });

        return filtered;
    }, [data, searchText, columnFilters, columns]);

    // Sort data
    const sortedData = useMemo(() => {
        if (!sortConfig.key) return filteredData;

        return [...filteredData].sort((a, b) => {
            const aValue = a[sortConfig.key!];
            const bValue = b[sortConfig.key!];

            if (aValue < bValue) {
                return sortConfig.direction === "asc" ? -1 : 1;
            }
            if (aValue > bValue) {
                return sortConfig.direction === "asc" ? 1 : -1;
            }
            return 0;
        });
    }, [filteredData, sortConfig]);

    useEffect(() => {
        setTotalRecords(sortedData.length);
    }, [setTotalRecords, sortedData.length]);

    // Pagination
    const paginatedData = useMemo(() => {
        if (!showPagination) return sortedData;

        const startIndex = (currentPage - 1) * itemsPerPage;
        return sortedData.slice(startIndex, startIndex + itemsPerPage);
    }, [sortedData, currentPage, itemsPerPage, showPagination]);

    const handleSort = useCallback(
        (key: keyof T) => {
            if (key !== sortConfig.key) {
                paginate({ sort: { key: key as string, direction: "asc" } });
                return;
            }

            if (sortConfig.direction === "desc") {
                paginate({ sort: { key: "", direction: "asc" } });
                return;
            }

            paginate({
                sort: {
                    key: key as string,
                    direction: "desc",
                },
            });
        },
        [sortConfig, paginate]
    );

    return (
        <div className={cn("overflow-hidden", variant === "minimal" && "border-none", !searchable && variant !== "minimal" && "rounded-ele")}>
            <div className="overflow-x-auto">
                <table className="w-full min-w-full">
                    <thead className={cn("bg-muted/20", variant === "minimal" && "border-b border-border bg-transparent")}>
                        <tr>
                            {columns.map((column) => (
                                <th
                                    key={String(column.key)}
                                    className={cn(
                                        "text-left font-semibold text-foreground",
                                        size === "sm" && "px-3 py-2 text-xs",
                                        size === "default" && "px-4 py-3 text-sm",
                                        size === "lg" && "px-6 py-4 text-base",
                                        column.sortable && "cursor-pointer transition-colors hover:bg-muted/30",
                                        column.align === "center" && "text-center",
                                        column.align === "right" && "text-right",
                                        column.width
                                    )}
                                    onClick={() => column.sortable && handleSort(column.key)}
                                    style={column.width ? { width: column.width } : undefined}
                                >
                                    <div
                                        className={cn(
                                            "flex items-center gap-2",
                                            column.align === "center" && "justify-center",
                                            column.align === "right" && "justify-end"
                                        )}
                                    >
                                        <span>{Utils.Type.isFunction(column.header) ? column.header(paginatedData) : column.header}</span>
                                        {column.sortable && (
                                            <div className="flex flex-col">
                                                <ChevronUp
                                                    className={cn(
                                                        "h-3 w-3 transition-colors",
                                                        sortConfig.key === column.key && sortConfig.direction === "asc"
                                                            ? "text-primary"
                                                            : "text-muted-foreground/40"
                                                    )}
                                                />
                                                <ChevronDown
                                                    className={cn(
                                                        "-mt-1 h-3 w-3 transition-colors",
                                                        sortConfig.key === column.key && sortConfig.direction === "desc"
                                                            ? "text-primary"
                                                            : "text-muted-foreground/40"
                                                    )}
                                                />
                                            </div>
                                        )}
                                    </div>
                                    {/* Column Filter */}
                                    {column.filterable && (
                                        <div className="mt-2" onClick={(e) => e.stopPropagation()}>
                                            <DataTableColumnFilter column={column} />
                                        </div>
                                    )}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="bg-card">
                        {paginatedData.length === 0 ? (
                            <tr>
                                <td
                                    colSpan={columns.length}
                                    className={cn(
                                        "bg-card text-center text-muted-foreground",
                                        size === "sm" && "px-3 py-8",
                                        size === "default" && "px-4 py-12",
                                        size === "lg" && "px-6 py-16"
                                    )}
                                >
                                    <div className="flex flex-col items-center space-y-3">
                                        <div className="text-4xl opacity-50">{emptyIcon}</div>
                                        <div className="font-medium">{emptyMessage ?? t("datatable.No data available")}</div>
                                        <div className="text-sm opacity-75">{t("datatable.Try adjusting your search or filter criteria")}</div>
                                    </div>
                                </td>
                            </tr>
                        ) : (
                            paginatedData.map((row, index) => (
                                <tr
                                    key={Utils.String.Token.shortUUID()}
                                    className={cn(
                                        "border-t border-border bg-card transition-colors",
                                        striped && index % 2 === 0 && "bg-muted/10",
                                        hoverable && "hover:bg-muted/20",
                                        onRowClick && "cursor-pointer",
                                        "group"
                                    )}
                                    onClick={() => onRowClick?.(row)}
                                >
                                    {columns.map((column) => (
                                        <td
                                            key={String(column.key)}
                                            className={cn(
                                                "text-foreground",
                                                size === "sm" && "px-3 py-2 text-xs",
                                                size === "default" && "px-4 py-3 text-sm",
                                                size === "lg" && "px-6 py-4 text-base",
                                                column.align === "center" && "text-center",
                                                column.align === "right" && "text-right"
                                            )}
                                        >
                                            {column.render
                                                ? column.render({ value: row[column.key], row, allRows: paginatedData })
                                                : String(row[column.key] ?? "")}
                                        </td>
                                    ))}
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

function DataTableColumnFilter<T extends Record<string, any>>({ column }: { column: TDataTableColumn<T> }) {
    const [t] = useTranslation();
    const { columnFilters, paginate } = useDataTable();
    const [inputValue, setInputValue] = useState(columnFilters[String(column.key)] || "");
    const lastInputValueRef = useRef(columnFilters[String(column.key)] || "");
    const throttleSearchTimeoutRef = useRef<NodeJS.Timeout | null>(null);
    const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        setInputValue(e.currentTarget.value);
        lastInputValueRef.current = e.currentTarget.value;
    };
    const handleKeyDown = () => {
        if (throttleSearchTimeoutRef.current) {
            clearTimeout(throttleSearchTimeoutRef.current);
            throttleSearchTimeoutRef.current = null;
        }
    };
    const handleKeyUp = () => {
        if (throttleSearchTimeoutRef.current) {
            clearTimeout(throttleSearchTimeoutRef.current);
            throttleSearchTimeoutRef.current = null;
        }

        throttleSearchTimeoutRef.current = setTimeout(() => {
            const newFilters = { ...columnFilters, [column.key]: lastInputValueRef.current };
            if (!lastInputValueRef.current) {
                delete newFilters[column.key as string];
            }

            paginate({
                page: 1,
                columnFilters: newFilters,
            });
        }, 500);
    };
    const clearColumnFilter = () => {
        const newFilters = { ...columnFilters };
        delete newFilters[column.key as string];

        setInputValue("");
        lastInputValueRef.current = "";
        paginate({ page: 1, columnFilters: newFilters });
    };

    useEffect(() => {
        setInputValue(columnFilters[column.key as string] || "");
        lastInputValueRef.current = columnFilters[column.key as string] || "";
    }, [columnFilters]);

    return (
        <Input
            placeholder={t("common.Filter...")}
            value={inputValue}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            onKeyUp={handleKeyUp}
            leftIcon={<Filter className="h-3 w-3 text-muted-foreground/50" />}
            clearable
            onClear={clearColumnFilter}
            h="sm"
            className="text-xs"
        />
    );
}

export default DataTableTable;
