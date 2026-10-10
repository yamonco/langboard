import { metadataDisplay } from "@/core/utils/MetadataDisplay";
import Button from "@/components/base/Button";
import IconComponent from "@/components/base/IconComponent";
import Input from "@/components/base/Input";
import Collaborative from "@/components/Collaborative";
import Toast from "@/components/base/Toast";
import useChangeProjectColumnName from "@/controllers/api/board/useChangeProjectColumnName";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import useChangeEditMode from "@/core/hooks/useChangeEditMode";
import { ProjectColumn } from "@/core/models";
import { ProjectRole } from "@/core/models/roles";
import { useBoardController } from "@/core/providers/BoardController";
import { useBoard } from "@/core/providers/BoardProvider";
import { cn } from "@/core/utils/ComponentUtils";
import { EEditorCollaborationType } from "@langboard/core/constants";
import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export interface IBoardColumnNameProps {
    isDragging: bool;
    column: ProjectColumn.TModel;
}

export interface IBoardColumnNameRef {
    startEditing: () => void;
}

const BoardColumnName = memo(
    forwardRef<IBoardColumnNameRef, IBoardColumnNameProps>(({ isDragging, column }: IBoardColumnNameProps, ref) => {
        const { selectCardViewType } = useBoardController();
        const { project, hasRoleAction } = useBoard();
        const [t, i18n] = useTranslation();
        const [isValidating, setIsValidating] = useState(false);
        const columnName = column.useField("name");
        const translations = column.useField("translations");
        const displayName = metadataDisplay(
            { name: columnName, description: "" },
            { ...translations, en: { name: columnName, description: "" }, "en-US": { name: columnName, description: "" } },
            i18n.resolvedLanguage ?? i18n.language
        ).name;
        const editorName = `${column.uid}-column-title`;
        const isArchiveColumn = column.useField("is_archive");
        const { mutateAsync: changeProjectColumnNameMutateAsync } = useChangeProjectColumnName({ interceptToast: true });
        const canEdit = hasRoleAction(ProjectRole.EAction.Update) && !isArchiveColumn;
        const resetCollaborativeNameRef = useRef<((value: string) => void) | null>(null);
        const { valueRef, isEditing, setIsEditing, changeMode } = useChangeEditMode({
            canEdit: () => canEdit && !isDragging && !selectCardViewType,
            valueType: "input",
            disableNewLine: true,
            editorName,
            save: (value, endCallback) => {
                if (isArchiveColumn) {
                    return;
                }

                setIsValidating(true);

                const promise = changeProjectColumnNameMutateAsync({
                    project_uid: project.uid,
                    project_column_uid: column.uid,
                    name: value,
                });

                Toast.Add.promise(promise, {
                    loading: t("common.Changing..."),
                    error: (error) => {
                        const messageRef = { message: "" };
                        const { handle } = setupApiErrorHandler({}, messageRef);

                        handle(error);
                        return messageRef.message;
                    },
                    success: () => {
                        return t("successes.Column name changed successfully.");
                    },
                    finally: () => {
                        setIsValidating(false);
                        endCallback();
                    },
                });
            },
            originalValue: columnName,
        });
        const saveEdit = useCallback(() => {
            changeMode("view");
        }, [changeMode]);
        const cancelEdit = useCallback(() => {
            resetCollaborativeNameRef.current?.(columnName);
            setIsEditing(false);
        }, [columnName, setIsEditing]);

        useImperativeHandle(
            ref,
            () => ({
                startEditing: () => {
                    changeMode("edit");
                },
            }),
            [changeMode]
        );

        useEffect(() => {
            if (!isEditing || !valueRef.current) {
                return;
            }

            requestAnimationFrame(() => {
                valueRef.current?.focus();
                valueRef.current?.select();
            });
        }, [isEditing]);

        return (
            <BoardColumnNameInput
                isEditing={isEditing}
                viewClassName={!isDragging && canEdit ? "cursor-grab" : ""}
                projectUID={project.uid}
                columnUID={column.uid}
                columnName={columnName}
                displayName={displayName}
                disabled={isValidating}
                isArchive={isArchiveColumn}
                inputRef={valueRef}
                changeMode={changeMode}
                onSave={saveEdit}
                onCancel={cancelEdit}
                onCollaborativeValueResetReady={(resetValue) => {
                    resetCollaborativeNameRef.current = resetValue;
                }}
            />
        );
    })
);
BoardColumnName.displayName = "Board.ColumnName";

export interface IBoardColumnNameInput {
    isEditing: bool;
    viewClassName?: string;
    projectUID?: string;
    columnUID?: string;
    columnName: string;
    displayName?: string;
    isArchive?: bool;
    disabled?: bool;
    inputRef: React.Ref<HTMLInputElement>;
    changeMode: (mode: "edit" | "view") => void;
    onSave?: () => void;
    onCancel?: () => void;
    onCollaborativeValueResetReady?: (resetValue: ((value: string) => void) | null) => void;
}

export const BoardColumnNameInput = memo(
    ({
        isEditing,
        viewClassName,
        projectUID,
        columnUID,
        changeMode,
        columnName,
        displayName,
        isArchive,
        disabled,
        inputRef,
        onSave,
        onCancel,
        onCollaborativeValueResetReady,
    }: IBoardColumnNameInput) => {
        const [t] = useTranslation();
        const handleInputClick = useCallback((e: React.MouseEvent) => {
            e.preventDefault();
            e.stopPropagation();
        }, []);
        const handleInputBlur = useCallback(() => {
            if (onSave || onCancel) {
                return;
            }
            changeMode("view");
        }, [changeMode, onCancel, onSave]);
        const handleSave = useCallback(() => {
            (onSave ?? (() => changeMode("view")))();
        }, [changeMode, onSave]);
        const handleCancel = useCallback(() => {
            if (onCancel) {
                onCancel();
                return;
            }

            changeMode("view");
        }, [changeMode, onCancel]);
        const handleActionMouseDown = useCallback((e: React.MouseEvent) => {
            e.preventDefault();
            e.stopPropagation();
        }, []);
        const handleInputKeyDown = useCallback(
            (e: React.KeyboardEvent) => {
                if (e.key === "Escape" && onCancel) {
                    e.preventDefault();
                    e.stopPropagation();
                    onCancel();
                    return;
                }

                if (e.key !== "Enter") {
                    return;
                }

                e.preventDefault();
                e.stopPropagation();
                handleSave();
            },
            [handleSave, onCancel]
        );

        const inputClassName = cn(
            "h-7 rounded-none border-x-0 border-t-0 p-0 pb-1 text-base font-semibold",
            "focus-visible:border-b-primary focus-visible:ring-0"
        );

        const input =
            projectUID && columnUID ? (
                <Collaborative.Input
                    ref={inputRef}
                    collaborationType={EEditorCollaborationType.BoardColumnName}
                    uid={projectUID}
                    section={columnUID}
                    field="name"
                    className={inputClassName}
                    placeholder={t("board.Enter a name")}
                    disabled={disabled}
                    defaultValue={columnName}
                    onClick={handleInputClick}
                    onBlur={handleInputBlur}
                    onKeyDown={handleInputKeyDown}
                    onCollaborativeValueResetReady={onCollaborativeValueResetReady}
                />
            ) : (
                <Input
                    ref={inputRef}
                    className={inputClassName}
                    placeholder={t("board.Enter a name")}
                    disabled={disabled}
                    defaultValue={columnName}
                    onClick={handleInputClick}
                    onBlur={handleInputBlur}
                    onKeyDown={handleInputKeyDown}
                />
            );

        return (
            <>
                {!isEditing || isArchive ? (
                    <span className={cn("h-7 truncate", isArchive && "text-secondary-foreground/70", viewClassName)}>
                        {displayName ?? columnName}
                    </span>
                ) : (
                    <div className="flex min-w-0 flex-1 items-center gap-1">
                        {input}
                        {(onSave || onCancel) && (
                            <div className="flex shrink-0 items-center gap-0.5">
                                <Button
                                    type="button"
                                    size="icon-sm"
                                    variant="ghost"
                                    disabled={disabled}
                                    title={t("common.Save")}
                                    aria-label={t("common.Save")}
                                    onMouseDown={handleActionMouseDown}
                                    onClick={handleSave}
                                >
                                    <span className="sr-only">{t("common.Save")}</span>
                                    <IconComponent icon="check" size="4" />
                                </Button>
                                <Button
                                    type="button"
                                    size="icon-sm"
                                    variant="ghost"
                                    disabled={disabled}
                                    title={t("common.Cancel")}
                                    aria-label={t("common.Cancel")}
                                    onMouseDown={handleActionMouseDown}
                                    onClick={handleCancel}
                                >
                                    <span className="sr-only">{t("common.Cancel")}</span>
                                    <IconComponent icon="x" size="4" />
                                </Button>
                            </div>
                        )}
                    </div>
                )}
            </>
        );
    }
);
BoardColumnNameInput.displayName = "Board.ColumnNameInput";

export default BoardColumnName;
