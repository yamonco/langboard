import Toast from "@/components/base/Toast";
import useCreateCard from "@/controllers/api/board/useCreateCard";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import useChangeEditMode from "@/core/hooks/useChangeEditMode";
import { ProjectColumn } from "@/core/models";
import { ProjectRole } from "@/core/models/roles";
import { useBoard } from "@/core/providers/BoardProvider";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

export interface IBoardAddCardContext {
    isEditing: bool;
    setIsEditing: (isEditing: bool) => void;
    isValidating: bool;
    changeMode: (mode: "edit" | "view") => void;
    scrollToBottom: () => void;
    textareaRef: React.RefObject<HTMLTextAreaElement | null>;
    disableChangeModeAttr: string;
    canWrite: bool;
}

interface IBoardAddCardProviderProps {
    column: ProjectColumn.TModel;
    viewportRef: React.RefObject<HTMLDivElement | null>;
    toLastPage: () => void;
    isDefaultCardColumn: boolean;
    children: React.ReactNode;
}

const initialContext = {
    isEditing: false,
    setIsEditing: () => {},
    isValidating: false,
    changeMode: () => {},
    scrollToBottom: () => {},
    textareaRef: { current: null! },
    disableChangeModeAttr: "data-disable-change-mode",
    canWrite: false,
};

const BoardAddCardContext = createContext<IBoardAddCardContext>(initialContext);

export const BoardAddCardProvider = ({
    column,
    viewportRef,
    toLastPage,
    isDefaultCardColumn,
    children,
}: IBoardAddCardProviderProps): React.ReactNode => {
    const { project, hasRoleAction } = useBoard();
    const [t] = useTranslation();
    const [isValidating, setIsValidating] = useState(false);
    const [searchParams, setSearchParams] = useSearchParams();
    const newCardCommandHandled = useRef(false);
    const disableChangeModeAttr = "data-disable-change-mode";
    const canWrite = hasRoleAction(ProjectRole.EAction.CardWrite) && !column.is_archive;
    const { mutateAsync: createCardMutateAsync } = useCreateCard({ interceptToast: true });
    const editorName = `${column.uid}-add-card`;

    const scrollToCreatedCard = (cardUID: string, attemptsLeft = 40) => {
        if (document.getElementById(`board-card-${cardUID}`)) {
            scrollToBottom();
            return;
        }
        if (attemptsLeft > 0) {
            window.setTimeout(() => scrollToCreatedCard(cardUID, attemptsLeft - 1), 50);
        }
    };

    const { valueRef, isEditing, setIsEditing, changeMode } = useChangeEditMode({
        canEdit: () => hasRoleAction(ProjectRole.EAction.CardWrite) && !column.is_archive,
        valueType: "textarea",
        disableNewLine: true,
        editorName,
        customStartEditing: () => {
            const pointerDownEvent = (e: PointerEvent) => {
                const target = e.target;
                if (!target || !(target instanceof HTMLElement) || target.closest(`[${disableChangeModeAttr}]`)) {
                    return;
                }

                changeMode("view");
                window.removeEventListener("pointerdown", pointerDownEvent);
            };

            window.addEventListener("pointerdown", pointerDownEvent);

            toLastPage();

            setTimeout(() => {
                if (valueRef.current) {
                    valueRef.current.focus();
                }
                scrollToBottom();
            }, 0);
        },
        save: (value, endCallback) => {
            setIsValidating(true);

            const promise = createCardMutateAsync({
                project_uid: project.uid,
                project_column_uid: column.uid,
                title: value,
            });

            Toast.Add.promise(promise, {
                loading: t("common.Adding..."),
                error: (error) => {
                    const messageRef = { message: "" };
                    const { handle } = setupApiErrorHandler({}, messageRef);

                    handle(error);
                    return messageRef.message;
                },
                success: ({ uid }) => {
                    // Card creation stays lightweight: insert into the board without opening the viewer.
                    // The user opens the viewer only through an explicit card or widget interaction.
                    toLastPage();
                    scrollToCreatedCard(uid);
                    return t("successes.Card added successfully.");
                },
                finally: () => {
                    setIsValidating(false);
                    setIsEditing(() => false);
                    endCallback();
                },
            });
        },
    });

    useEffect(() => {
        if (searchParams.get("new-card") !== "1") {
            newCardCommandHandled.current = false;
            return;
        }
        if (!isDefaultCardColumn || !canWrite || newCardCommandHandled.current) return;
        newCardCommandHandled.current = true;
        changeMode("edit");
        setSearchParams(
            (params) => {
                params.delete("new-card");
                return params;
            },
            { replace: true }
        );
    }, [isDefaultCardColumn, canWrite, searchParams, changeMode, setSearchParams]);

    const scrollToBottom = () => {
        const viewport = viewportRef.current;
        if (!viewport) {
            return;
        }

        viewport.scrollTo({ top: viewport.scrollHeight });
    };

    return (
        <BoardAddCardContext.Provider
            value={{
                isEditing,
                setIsEditing,
                isValidating,
                changeMode,
                scrollToBottom,
                textareaRef: valueRef,
                disableChangeModeAttr,
                canWrite,
            }}
        >
            {children}
        </BoardAddCardContext.Provider>
    );
};

export const useBoardAddCard = () => {
    const context = useContext(BoardAddCardContext);
    if (!context) {
        throw new Error("useBoardAddCard must be used within a BoardAddCardProvider");
    }
    return context;
};
