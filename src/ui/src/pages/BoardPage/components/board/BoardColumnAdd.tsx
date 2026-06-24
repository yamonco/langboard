import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Card from "@/components/base/Card";
import ScrollArea from "@/components/base/ScrollArea";
import Toast from "@/components/base/Toast";
import useCreateProjectColumn from "@/controllers/api/board/useCreateProjectColumn";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import useChangeEditMode from "@/core/hooks/useChangeEditMode";
import { ProjectRole } from "@/core/models/roles";
import { useBoard } from "@/core/providers/BoardProvider";
import { cn } from "@/core/utils/ComponentUtils";
import { BOARD_COLUMN_MAX_HEIGHT_CLASS_NAMES } from "@/pages/BoardPage/components/board/BoardConstants";
import { BoardColumnNameInput } from "@/pages/BoardPage/components/board/BoardColumnName";
import { memo, useState } from "react";
import { useTranslation } from "react-i18next";

const BoardColumnAdd = memo(() => {
    const { project, hasRoleAction } = useBoard();
    const [t] = useTranslation();
    const [isValidating, setIsValidating] = useState(false);
    const { mutateAsync: createProjectColumnMutateAsync } = useCreateProjectColumn({ interceptToast: true });
    const editorName = `${project.uid}-add-column`;
    const { valueRef, isEditing, changeMode } = useChangeEditMode({
        canEdit: () => hasRoleAction(ProjectRole.EAction.Update),
        valueType: "input",
        disableNewLine: true,
        editorName,
        save: (value, endCallback) => {
            setIsValidating(true);

            const promise = createProjectColumnMutateAsync({
                project_uid: project.uid,
                name: value,
            });

            Toast.Add.promise(promise, {
                loading: t("common.Adding..."),
                error: (error) => {
                    const messageRef = { message: "" };
                    const { handle } = setupApiErrorHandler({}, messageRef);

                    handle(error);
                    return messageRef.message;
                },
                success: () => {
                    return t("successes.Column added successfully.");
                },
                finally: () => {
                    setIsValidating(false);
                    endCallback();
                },
            });
        },
    });

    const sharedRootClassNames = "my-1 ring-primary";

    return (
        <>
            {!isEditing ? (
                <Button
                    className={cn(sharedRootClassNames, "justify-start rounded-md border-2 border-dashed bg-card p-4 text-card-foreground shadow")}
                    onClick={() => changeMode("edit")}
                >
                    {t("board.Add column")}
                </Button>
            ) : (
                <Card.Root
                    className={cn(
                        sharedRootClassNames,
                        BOARD_COLUMN_MAX_HEIGHT_CLASS_NAMES,
                        "grid w-80 flex-shrink-0 snap-center grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden"
                    )}
                >
                    <Card.Header className="flex flex-row items-start space-y-0 pb-1 pt-4 text-left font-semibold">
                        <BoardColumnNameInput isEditing={true} changeMode={changeMode} columnName="" disabled={isValidating} inputRef={valueRef} />
                    </Card.Header>
                    <ScrollArea.Root className="min-h-0 flex-1">
                        <Card.Content className="flex min-h-0 flex-col gap-2 p-3">
                            <Box pb="2.5" />
                        </Card.Content>
                    </ScrollArea.Root>
                </Card.Root>
            )}
        </>
    );
});
BoardColumnAdd.displayName = "Board.ColumnAdd";

export default BoardColumnAdd;
