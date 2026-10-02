import { formatNumber } from "@/core/utils/LocaleFormat";
import Button from "@/components/base/Button";
import { useDataTable } from "@/components/base/DataTable/Provider";
import IconComponent from "@/components/base/IconComponent";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

function DataTablePagination() {
    const [t, i18n] = useTranslation();
    const { currentPage, itemsPerPage, totalRecords } = useDataTable();
    const totalPages = useMemo(() => Math.ceil(totalRecords / itemsPerPage), [totalRecords, itemsPerPage]);
    const pageNumbers = useMemo(() => {
        const pageNumbers: (number | "ellipsis")[] = [];
        const maxVisiblePages = 5;

        if (totalPages <= maxVisiblePages) {
            for (let i = 1; i <= totalPages; ++i) {
                pageNumbers.push(i);
            }
        } else {
            if (currentPage <= 3) {
                for (let i = 1; i <= 4; ++i) {
                    pageNumbers.push(i);
                }
                pageNumbers.push("ellipsis");
                pageNumbers.push(totalPages);
            } else if (currentPage >= totalPages - 2) {
                pageNumbers.push(1);
                pageNumbers.push("ellipsis");
                for (let i = totalPages - 3; i <= totalPages; ++i) {
                    pageNumbers.push(i);
                }
            } else {
                pageNumbers.push(1);
                pageNumbers.push("ellipsis");
                for (let i = currentPage - 1; i <= currentPage + 1; ++i) {
                    pageNumbers.push(i);
                }
                pageNumbers.push("ellipsis");
                pageNumbers.push(totalPages);
            }
        }

        return pageNumbers;
    }, [totalPages]);

    return (
        <div className="flex flex-col items-center justify-between gap-4 border-t border-border bg-card p-6 pt-4 sm:flex-row">
            <div className="order-2 text-sm text-muted-foreground sm:order-1">
                {t("datatable.Showing {start} to {end} of {total} results", {
                    start: !totalPages ? 0 : (currentPage - 1) * itemsPerPage + 1,
                    end: Math.min(currentPage * itemsPerPage, totalRecords),
                    total: totalRecords,
                })}
            </div>
            <div className="order-1 flex items-center gap-2 sm:order-2">
                <DataTablePaginationPage type="previous" totalPages={totalPages} />
                <div className="hidden items-center gap-1 sm:flex">
                    {pageNumbers.map((pageNumber, index) => (
                        <DataTablePaginationPage key={index} type={pageNumber} totalPages={totalPages} />
                    ))}
                </div>
                <DataTablePaginationPage type="next" totalPages={totalPages} />
            </div>
        </div>
    );
}

function DataTablePaginationPage({ type, totalPages }: { type: "previous" | "next" | "ellipsis" | number; totalPages: number }) {
    const [t, i18n] = useTranslation();
    const { currentPage, paginate } = useDataTable();
    const isDisabled = useMemo(() => {
        switch (type) {
            case "next":
                return currentPage === totalPages || !totalPages;
            case "previous":
                return currentPage === 1 || !totalPages;
            case "ellipsis":
                return true;
            default:
                return false;
        }
    }, [currentPage, totalPages, type]);
    let variant;
    let content;
    let title;
    switch (type) {
        case "next":
            content = <IconComponent icon="chevron-right" size="4" />;
            variant = "outline" as const;
            title = t("datatable.Next Page");
            break;
        case "previous":
            content = <IconComponent icon="chevron-left" size="4" />;
            variant = "outline" as const;
            title = t("datatable.Previous Page");
            break;
        case "ellipsis":
            content = <IconComponent icon="more-horizontal" size="4" />;
            variant = "ghost" as const;
            title = t("datatable.More Pages");
            break;
        default:
            content = formatNumber(type, i18n.language);
            variant = currentPage === type ? ("default" as const) : ("ghost" as const);
            title = t("datatable.Page {page}", { page: type });
            break;
    }

    const handleClick = () => {
        switch (type) {
            case "next":
                paginate({ page: Math.min(currentPage + 1, totalPages) });
                break;
            case "previous":
                paginate({ page: Math.max(currentPage - 1, 1) });
                break;
            case "ellipsis":
                break;
            default:
                paginate({ page: type });
                break;
        }
    };

    return (
        <Button variant={variant} size="icon-sm" onClick={handleClick} disabled={isDisabled} title={title}>
            {content}
        </Button>
    );
}

export default DataTablePagination;
