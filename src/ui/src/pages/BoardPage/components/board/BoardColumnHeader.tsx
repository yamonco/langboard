import Card from "@/components/base/Card";
import BoardColumnDescription from "@/pages/BoardPage/components/board/BoardColumnDescription";
import { ProjectColumn } from "@/core/models";
import BoardColumnMoreMenu from "@/pages/BoardPage/components/board/BoardColumnMoreMenu";
import BoardGraphApprovalTargetBadge from "@/pages/BoardPage/components/board/BoardGraphApprovalTargetBadge";
import BoardColumnName, { IBoardColumnNameRef } from "@/pages/BoardPage/components/board/BoardColumnName";
import { EGraphApprovalScopeTable } from "@/core/models/GraphApprovalRequestModel";
import { memo, useCallback, useRef } from "react";

export interface IBoardColumnHeaderProps {
    isDragging: bool;
    column: ProjectColumn.TModel;
    headerProps: React.DetailedHTMLProps<React.HTMLAttributes<HTMLDivElement>, HTMLDivElement>;
}

const BoardColumnHeader = memo(({ isDragging, column, headerProps }: IBoardColumnHeaderProps) => {
    const columnNameRef = useRef<IBoardColumnNameRef>(null);

    const handleRenameStart = useCallback(() => {
        columnNameRef.current?.startEditing();
    }, []);

    return (
        <Card.Header className="flex flex-row items-start justify-between space-y-0 pb-1 pr-3 pt-4 text-left font-semibold" {...headerProps}>
            <div className="flex min-w-0 flex-1 items-center gap-2">
                <BoardColumnName ref={columnNameRef} isDragging={isDragging} column={column} />
                <BoardColumnDescription column={column} />
                <BoardGraphApprovalTargetBadge
                    projectUID={column.project_uid}
                    scopeTable={EGraphApprovalScopeTable.ProjectColumn}
                    scopeUID={column.uid}
                    className="flex-shrink-0"
                />
            </div>
            <BoardColumnMoreMenu column={column} onRenameStart={handleRenameStart} />
        </Card.Header>
    );
});
BoardColumnHeader.displayName = "Board.ColumnHeader";

export default BoardColumnHeader;
