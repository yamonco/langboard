import { sanitizeEditorContent } from "@/components/Editor/utils";
import { IEditorContent } from "@/core/models/Base";
import { getEditorStore, useIsCurrentEditor } from "@/core/stores/EditorStore";
import { measureTextAreaHeight } from "@/core/utils/ComponentUtils";
import { Utils } from "@langboard/core/utils";
import { useCallback, useRef, useState } from "react";

export type TValueType = "string" | "textarea" | "input" | "editor";

export type TElementValueRef<TValue extends TValueType> = TValue extends "textarea"
    ? HTMLTextAreaElement
    : TValue extends "input"
      ? HTMLInputElement
      : undefined;

export type TObjectValueRef<TValue extends TValueType> = TValue extends "editor" ? IEditorContent : string | undefined;

export type TValueRef<TValue extends TValueType> = TValue extends "textarea"
    ? HTMLTextAreaElement
    : TValue extends "input"
      ? HTMLInputElement
      : TValue extends "editor"
        ? IEditorContent
        : string | undefined;

interface IBaseUseChangeEditModeProps<TValue extends TValueType> {
    canEdit: () => bool;
    customStartEditing?: () => void;
    valueType: TValue;
    disableNewLine?: bool;
    canEmpty?: bool;
    onStopEditing?: () => void;
    editorName: string;
}

interface IEditorUseChangeEditModeProps extends IBaseUseChangeEditModeProps<"editor"> {
    save: (value: IEditorContent, endCallback: () => void) => void;
    originalValue?: IEditorContent;
}

interface IOtherUseChangeEditModeProps<TValue extends TValueType> extends IBaseUseChangeEditModeProps<TValue> {
    save: (value: string, endCallback: () => void) => void;
    originalValue?: string;
}

export type TUseChangeEditModeProps<TValue extends TValueType> = TValue extends "editor"
    ? IEditorUseChangeEditModeProps
    : IOtherUseChangeEditModeProps<TValue>;

interface IUseChangeEditMode<TValue extends TValueType> {
    valueRef: TValue extends "textarea" | "input" ? React.RefObject<TElementValueRef<TValue>> : React.RefObject<TObjectValueRef<TValue>>;
    height: TValue extends "textarea" ? number : undefined;
    updateHeight: TValue extends "textarea" ? () => void : undefined;
    isEditing: bool;
    setIsEditing: React.Dispatch<React.SetStateAction<bool>>;
    changeMode: (mode: "edit" | "view") => void;
}

const useEditorState = (editorName: string): [bool, React.Dispatch<React.SetStateAction<bool>>] => {
    const isCurrentEditor = useIsCurrentEditor(editorName);
    const setCurrentEditor = useCallback(
        (state: bool | ((prevState: bool) => bool)) => {
            if (Utils.Type.isFunction(state)) {
                state = state(isCurrentEditor);
            }

            if (!state) {
                const editorStore = getEditorStore();
                if (editorStore.currentEditor === editorName) {
                    editorStore.setCurrentEditor(null);
                }
                return;
            }

            getEditorStore().setCurrentEditor(editorName);
        },
        [isCurrentEditor]
    );

    return [isCurrentEditor, setCurrentEditor];
};

const useChangeEditMode = <
    TValue extends TValueType,
    TRef extends TValue extends "textarea" | "input" ? React.RefObject<TElementValueRef<TValue>> : React.RefObject<TObjectValueRef<TValue>>,
>({
    canEdit,
    save,
    customStartEditing,
    originalValue,
    disableNewLine,
    valueType,
    canEmpty = false,
    editorName,
    onStopEditing,
}: TUseChangeEditModeProps<TValue>): IUseChangeEditMode<TValue> => {
    const valueRef = useRef<TRef>((valueType === "editor" ? originalValue : undefined) as unknown as TRef);
    const [height, setHeight] = useState(0);
    const [isEditing, setIsEditing] = useEditorState(editorName);

    const trimValue = <T extends string | undefined, TReturn extends T extends string ? string : undefined>(value: T): TReturn => {
        if (!value) {
            return value as unknown as TReturn;
        }

        value = value.trim() as unknown as T;
        if (!disableNewLine) {
            return value as unknown as TReturn;
        }
        return value!.replace(/\n/g, " ") as unknown as TReturn;
    };

    const changeMode = useCallback(
        (mode: "edit" | "view") => {
            if (!canEdit()) {
                return;
            }

            if (mode === "edit") {
                if (customStartEditing) {
                    setIsEditing(() => true);
                    customStartEditing();
                    return;
                }

                setIsEditing(() => true);
                setTimeout(() => {
                    if (Utils.Type.isElement(valueRef.current, "input")) {
                        valueRef.current.focus();
                        return;
                    }

                    if (!Utils.Type.isElement(valueRef.current, "textarea")) {
                        return;
                    }

                    setHeight(measureTextAreaHeight(valueRef.current));
                    valueRef.current.selectionStart = valueRef.current.value.length;
                    valueRef.current.selectionEnd = valueRef.current.value.length;
                    valueRef.current.focus();
                }, 0);
                return;
            }

            let value: string | IEditorContent = "";
            let oldValue: string | undefined = "";
            if (Utils.Type.isElement(valueRef.current, "textarea")) {
                value = trimValue(valueRef.current.value);
                oldValue = trimValue(originalValue as unknown as string);
            } else if (Utils.Type.isElement(valueRef.current, "input")) {
                value = trimValue(valueRef.current.value);
                oldValue = trimValue(originalValue as unknown as string);
            } else if (Utils.Type.isString(valueRef.current)) {
                value = trimValue(valueRef.current);
                oldValue = trimValue(originalValue as unknown as string);
            } else if (Utils.Type.isObject<IEditorContent>(valueRef.current)) {
                value = sanitizeEditorContent(valueRef.current.content);
                oldValue = sanitizeEditorContent((originalValue as unknown as IEditorContent)?.content ?? "");
            }

            if ((!canEmpty && !value) || ((canEmpty || !!oldValue) && oldValue === value)) {
                onStopEditing?.();
                setIsEditing(() => false);
                return;
            }

            if (!Utils.Type.isElement(valueRef.current) && Utils.Type.isObject<IEditorContent>(valueRef.current)) {
                (valueRef.current as IEditorContent) = {
                    ...(valueRef.current as IEditorContent),
                    content: value,
                };
                value = valueRef.current;
            }

            onStopEditing?.();
            save(value as IEditorContent & string, () => {
                if (customStartEditing) {
                    return;
                }

                setIsEditing(() => false);
            });
        },
        [canEdit, customStartEditing, originalValue, save, canEmpty, disableNewLine]
    );

    const updateHeight = useCallback(() => {
        if (!Utils.Type.isElement(valueRef.current, "textarea")) {
            return;
        }

        setHeight(measureTextAreaHeight(valueRef.current));
    }, [setHeight]);

    return {
        valueRef: valueRef as unknown as TRef,
        height: height as TValue extends "textarea" ? number : undefined,
        updateHeight: updateHeight as TValue extends "textarea" ? () => void : undefined,
        isEditing,
        setIsEditing,
        changeMode,
    };
};

export default useChangeEditMode;
