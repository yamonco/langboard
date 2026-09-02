/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { Plate } from "platejs/react";
import { TUseCreateEditor, useCreateEditor } from "@/components/Editor/useCreateEditor";
import { Editor, EditorContainer } from "@/components/plate-ui/editor";
import { IEditorContent } from "@/core/models/Base";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type Value } from "platejs";
import { FocusScope } from "@radix-ui/react-focus-scope";
import { EditorDataProvider, TEditorDataProviderProps, useEditorData } from "@/core/providers/EditorDataProvider";
import { TEditor } from "@/components/Editor/editor-kit";
import { useMounted } from "@/core/hooks/useMounted";
import { YjsPlugin } from "@platejs/yjs/react";
import { PlateEditor as TPlateEditor } from "platejs/react";
import { MarkdownPlugin } from "@platejs/markdown";
import { useSocket } from "@/core/providers/SocketProvider";
import { EEditorType } from "@langboard/core/constants";
import { ESocketTopic } from "@langboard/core/enums";
import { Utils } from "@langboard/core/utils";
import type { TSocketScopedTopic } from "@/core/stores/socket/types";
import { useTranslation } from "react-i18next";
import SyncBlocker from "@/components/Collaborative/SyncBlocker";
import Badge from "@/components/base/Badge";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import useApproveGraphApproval from "@/controllers/api/board/graphApprovals/useApproveGraphApproval";
import useGetGraphApprovals from "@/controllers/api/board/graphApprovals/useGetGraphApprovals";
import useRejectGraphApproval from "@/controllers/api/board/graphApprovals/useRejectGraphApproval";
import useBoardGraphApprovalDeletedHandlers from "@/controllers/socket/board/graphApprovals/useBoardGraphApprovalDeletedHandlers";
import useBoardGraphApprovalRequestedHandlers from "@/controllers/socket/board/graphApprovals/useBoardGraphApprovalRequestedHandlers";
import useBoardGraphApprovalUpdatedHandlers from "@/controllers/socket/board/graphApprovals/useBoardGraphApprovalUpdatedHandlers";
import useSwitchSocketHandlers from "@/core/hooks/useSwitchSocketHandlers";
import { GraphApprovalRequestModel } from "@/core/models";
import { EGraphApprovalOriginType, EGraphApprovalStatus } from "@/core/models/GraphApprovalRequestModel";
import { useGraphApprovalSummary, useGraphApprovalTitle } from "@/pages/BoardPage/components/board/GraphApprovalUtils";

interface IEditorSyncRichPatchRequest {
    document_name: string;
    value: string;
}

interface IRichPatchSocketTarget {
    topic: TSocketScopedTopic;
    topicId: string;
}

const EDITOR_SYNC_RICH_PATCH_REQUEST_EVENT = "editor-sync:rich-draft-patch-request";
const EMPTY_EDITOR_VALUE: Value = [{ type: "p", children: [{ text: "" }] }];
const YJS_SELECTION_MISMATCH_ERROR = "Path doesn't match yText";

type TEditorOnChange = () => void;

const isYjsSelectionMismatchError = (error: unknown) => {
    return error instanceof Error && error.message.includes(YJS_SELECTION_MISMATCH_ERROR);
};

interface IBasePlateEditorProps extends Omit<TUseCreateEditor, "plugins"> {
    setValue?: (value: IEditorContent) => void;
    onEditorChange?: (editor: TEditor) => void;
    onEditorReady?: (editor: TEditor) => void;
    serializeOnChange?: bool;
    focusOnReady?: bool;
    variant?: React.ComponentProps<typeof Editor>["variant"];
    className?: string;
    containerClassName?: string;
    editorRef?: React.RefObject<TEditor | null>;
    editorComponentRef?: React.Ref<HTMLDivElement>;
    placeholder?: string;
    deserializedValue?: Value;
    onCollaborativeValueReady?: (updateValue: ((value: string) => void) | null) => void;
    onCollaborativeValueResetReady?: (resetValue: ((value: string) => void) | null) => void;
}

interface IPlateViewerProps extends IBasePlateEditorProps {
    setValue?: never;
    readOnly: true;
}

interface IPlateEditorProps extends IBasePlateEditorProps {
    setValue: (value: IEditorContent) => void;
    readOnly?: bool;
}

export type TPlateEditorProps = IPlateViewerProps | IPlateEditorProps;

export function PlateEditor(props: TPlateEditorProps & Omit<TEditorDataProviderProps, "children">) {
    return (
        <EditorDataProvider {...(props as any)}>
            <EditorWrapper {...props} />
        </EditorDataProvider>
    );
}

function EditorWrapper({
    value,
    readOnly,
    variant = "ai",
    serializeOnChange = true,
    focusOnReady = false,
    className,
    containerClassName,
    setValue,
    onEditorChange,
    onEditorReady,
    editorRef,
    editorComponentRef,
    placeholder,
    deserializedValue,
    onCollaborativeValueReady,
    onCollaborativeValueResetReady,
    ...props
}: TPlateEditorProps) {
    if (!editorRef) {
        editorRef = useRef<TEditor>(null);
    }

    const [t] = useTranslation();
    const internalEditorComponentRef = useRef<HTMLDivElement>(null);
    const [isCollaborativeReady, setIsCollaborativeReady] = useState(false);
    const [showSyncUnavailable, setShowSyncUnavailable] = useState(false);
    const [collaborativeRetryKey, setCollaborativeRetryKey] = useState(0);
    const handleCollaborativeSyncChange = useCallback((isSynced: bool) => {
        setIsCollaborativeReady(isSynced);
    }, []);
    const editor = useCreateEditor({
        value,
        readOnly,
        deserializedValue,
        onCollaborativeSyncChange: handleCollaborativeSyncChange,
        ...props,
    } as TUseCreateEditor);
    const mounted = useMounted();
    const socket = useSocket();
    const { documentID, editorType, form } = useEditorData();
    const projectUID = Utils.Type.isString(form?.project_uid) ? form.project_uid : undefined;
    const isWaitingForCollaborativeReady = !readOnly && !!documentID && !isCollaborativeReady;
    const valueRef = useRef(value);
    const deserializedValueRef = useRef(deserializedValue);
    valueRef.current = value;
    deserializedValueRef.current = deserializedValue;
    const richPatchSocketTarget = useMemo<IRichPatchSocketTarget | null>(() => {
        if (!documentID) {
            return null;
        }

        if (editorType === EEditorType.CardDescription && form?.card_uid) {
            return {
                topic: ESocketTopic.BoardCard,
                topicId: form.card_uid as string,
            };
        }

        if (editorType === EEditorType.WikiContent && form?.wiki_uid) {
            return {
                topic: ESocketTopic.BoardWikiPrivate,
                topicId: form.wiki_uid as string,
            };
        }

        return null;
    }, [documentID, editorType, form]);
    const focusEditor = useCallback(() => {
        if (!focusOnReady || readOnly) {
            return;
        }

        const focusElement = internalEditorComponentRef.current;
        if (!focusElement) {
            return;
        }

        window.setTimeout(() => {
            try {
                editor.tf.focus({ edge: "endEditor", retries: 3 });
            } catch (e) {
                console.log(e);
                focusElement.focus();
            }
        }, 0);
    }, [editor, focusOnReady, readOnly]);
    const normalizeEditorValue = useCallback((value: Value) => {
        if (value.length) {
            return value;
        }

        return EMPTY_EDITOR_VALUE;
    }, []);
    const getEditorValue = useCallback(
        (editor: TPlateEditor) => {
            if (deserializedValueRef.current) {
                return normalizeEditorValue(deserializedValueRef.current);
            }

            if (valueRef.current) {
                return normalizeEditorValue(editor.getApi(MarkdownPlugin).markdown.deserialize(valueRef.current.content));
            } else {
                return EMPTY_EDITOR_VALUE;
            }
        },
        [normalizeEditorValue]
    );

    const handleValueChange = useCallback(
        (opts: { editor: TPlateEditor }) => {
            if (readOnly) {
                return;
            }

            onEditorChange?.(opts.editor as TEditor);

            if (!serializeOnChange) {
                return;
            }

            const nextContent = opts.editor.getApi(MarkdownPlugin).markdown.serialize();
            if (nextContent === valueRef.current?.content) {
                return;
            }

            setValue?.({
                content: nextContent,
            });
        },
        [onEditorChange, readOnly, serializeOnChange, setValue]
    );

    editorRef.current = editor;

    const updateCollaborativeValue = useCallback(
        (nextContent: string) => {
            const nextValue = normalizeEditorValue(editor.getApi(MarkdownPlugin).markdown.deserialize(nextContent));
            editor.tf.reset();
            editor.tf.setValue(nextValue);
            setValue?.({
                content: nextContent,
            });
        },
        [editor, normalizeEditorValue, setValue]
    );

    const hasRemoteCollaborativeEditor = useCallback(() => {
        const awareness = editor.getOptions(YjsPlugin)?.awareness;
        if (!awareness) {
            return false;
        }

        return Array.from(awareness.getStates().keys()).some((clientID) => clientID !== awareness.clientID);
    }, [editor]);

    const resetCollaborativeValue = useCallback(
        (nextContent: string) => {
            if (hasRemoteCollaborativeEditor()) {
                return;
            }

            updateCollaborativeValue(nextContent);
        },
        [hasRemoteCollaborativeEditor, updateCollaborativeValue]
    );

    useEffect(() => {
        if (readOnly || !documentID || !isCollaborativeReady) {
            onCollaborativeValueReady?.(null);
            return;
        }

        onCollaborativeValueReady?.(updateCollaborativeValue);
        return () => {
            onCollaborativeValueReady?.(null);
        };
    }, [documentID, isCollaborativeReady, onCollaborativeValueReady, readOnly, updateCollaborativeValue]);

    useEffect(() => {
        if (readOnly || !documentID || !isCollaborativeReady) {
            onCollaborativeValueResetReady?.(null);
            return;
        }

        onCollaborativeValueResetReady?.(resetCollaborativeValue);
        return () => {
            onCollaborativeValueResetReady?.(null);
        };
    }, [documentID, isCollaborativeReady, onCollaborativeValueResetReady, readOnly, resetCollaborativeValue]);

    useEffect(() => {
        setIsCollaborativeReady(readOnly || !documentID);
    }, [documentID, readOnly]);

    useEffect(() => {
        if (!mounted || readOnly || !documentID || !richPatchSocketTarget) {
            return;
        }

        const callback = (data: IEditorSyncRichPatchRequest) => {
            if (data.document_name !== documentID) {
                return;
            }

            updateCollaborativeValue(data.value);
        };

        socket.on<IEditorSyncRichPatchRequest>({
            topic: richPatchSocketTarget.topic,
            topicId: richPatchSocketTarget.topicId,
            event: EDITOR_SYNC_RICH_PATCH_REQUEST_EVENT,
            eventKey: documentID,
            callback,
        });

        return () => {
            socket.off({
                topic: richPatchSocketTarget.topic,
                topicId: richPatchSocketTarget.topicId,
                event: EDITOR_SYNC_RICH_PATCH_REQUEST_EVENT,
                eventKey: documentID,
                callback: callback as unknown as (data: unknown) => void,
            });
        };
    }, [documentID, mounted, readOnly, richPatchSocketTarget, socket, updateCollaborativeValue]);

    useEffect(() => {
        if (!mounted || readOnly || !documentID) {
            return;
        }

        const yjsApi = editor.getApi(YjsPlugin)?.yjs;
        if (!yjsApi) {
            return;
        }

        setIsCollaborativeReady(false);
        const originalOnChange = editor.onChange;
        if (!Utils.Type.isFunction<TEditorOnChange>(originalOnChange)) {
            return;
        }

        editor.onChange = () => {
            try {
                originalOnChange();
            } catch (error) {
                if (!isYjsSelectionMismatchError(error)) {
                    throw error;
                }

                editor.selection = null;
                originalOnChange();
            }
        };

        try {
            editor.tf.blur();
        } catch {
            // The editor can be between mount and editable registration here.
        }
        editor.selection = null;
        let disposed = false;
        let initialized = false;
        let initStarted = false;
        let destroyed = false;
        const destroyYjs = () => {
            if (destroyed) {
                return;
            }

            destroyed = true;
            yjsApi.destroy();
        };
        const startYjs = () => {
            if (disposed) {
                return;
            }

            initStarted = true;
            void yjsApi
                .init({
                    id: documentID,
                    autoSelect: false,
                    selection: null,
                    value: getEditorValue(editor),
                    onReady: () => {
                        initialized = true;
                        if (!disposed && editor.getOptions(YjsPlugin)?._isSynced) {
                            setIsCollaborativeReady(true);
                        }
                    },
                })
                .then(() => {
                    initialized = true;
                    if (disposed) {
                        destroyYjs();
                    }
                })
                .catch(() => {
                    initialized = false;
                });
        };

        const initTimeoutID = window.setTimeout(startYjs, 0);

        return () => {
            disposed = true;
            editor.onChange = originalOnChange;
            setIsCollaborativeReady(false);
            if (!initStarted) {
                window.clearTimeout(initTimeoutID);
            }
            if (initialized) {
                destroyYjs();
            }
        };
    }, [collaborativeRetryKey, documentID, editor, focusEditor, getEditorValue, mounted, readOnly]);

    useEffect(() => {
        if (isCollaborativeReady) {
            focusEditor();
        }
    }, [focusEditor, isCollaborativeReady]);

    useEffect(() => {
        if (!isCollaborativeReady) {
            return;
        }

        onEditorReady?.(editor);
    }, [editor, isCollaborativeReady, onEditorReady]);

    useEffect(() => {
        if (!isWaitingForCollaborativeReady) {
            setShowSyncUnavailable(false);
            return;
        }

        const timeoutID = window.setTimeout(() => {
            setShowSyncUnavailable(true);
        }, 5_000);

        return () => {
            window.clearTimeout(timeoutID);
        };
    }, [isWaitingForCollaborativeReady]);

    useEffect(() => {
        if (!mounted || readOnly || !focusOnReady || documentID) {
            return;
        }

        focusEditor();
    }, [documentID, focusEditor, focusOnReady, mounted, readOnly]);

    const setEditorComponentRefs = useCallback(
        (node: HTMLDivElement | null) => {
            internalEditorComponentRef.current = node;

            if (!editorComponentRef) {
                return;
            }

            if (Utils.Type.isFunction(editorComponentRef)) {
                editorComponentRef(node);
                return;
            }

            editorComponentRef.current = node;
        },
        [editorComponentRef]
    );

    return (
        <FocusScope trapped={false} loop={false} className="w-full outline-none">
            <Plate editor={editor} readOnly={readOnly} onValueChange={handleValueChange}>
                <div className="relative">
                    <EditorContainer className={containerClassName}>
                        <Editor variant={variant} className={className} placeholder={placeholder} readOnly={readOnly} ref={setEditorComponentRefs} />
                    </EditorContainer>
                    {isWaitingForCollaborativeReady && (
                        <SyncBlocker
                            actionLabel={showSyncUnavailable ? t("common.Refresh") : undefined}
                            label={t(showSyncUnavailable ? "common.Realtime sync unavailable." : "common.Syncing draft...")}
                            onAction={showSyncUnavailable ? () => setCollaborativeRetryKey((prev) => prev + 1) : undefined}
                        />
                    )}
                    <EditorGraphApprovalBanner projectUID={projectUID} documentID={documentID} />
                </div>
            </Plate>
        </FocusScope>
    );
}

function EditorGraphApprovalBanner({ projectUID, documentID }: { projectUID?: string; documentID?: string }): React.JSX.Element | null {
    const socket = useSocket();
    const effectiveProjectUID = projectUID || "";
    const isEnabled = !!projectUID && !!documentID;
    useGetGraphApprovals(
        {
            project_uid: effectiveProjectUID,
            status: EGraphApprovalStatus.Pending,
            origin_type: EGraphApprovalOriginType.Editor,
            limit: 100,
        },
        {
            enabled: isEnabled,
            interceptToast: false,
        }
    );
    const graphApprovalRequestedHandlers = useBoardGraphApprovalRequestedHandlers({ projectUID: effectiveProjectUID });
    const graphApprovalUpdatedHandlers = useBoardGraphApprovalUpdatedHandlers({ projectUID: effectiveProjectUID });
    const graphApprovalDeletedHandlers = useBoardGraphApprovalDeletedHandlers({ projectUID: effectiveProjectUID });
    const graphApprovalHandlers = useMemo(
        () => [graphApprovalRequestedHandlers, graphApprovalUpdatedHandlers, graphApprovalDeletedHandlers],
        [graphApprovalRequestedHandlers, graphApprovalUpdatedHandlers, graphApprovalDeletedHandlers]
    );
    useSwitchSocketHandlers({ socket, handlers: graphApprovalHandlers, dependencies: [graphApprovalHandlers] });
    const approvals = GraphApprovalRequestModel.Model.useModels((approval) => {
        return (
            isEnabled &&
            approval.project_uid === projectUID &&
            approval.origin_type === EGraphApprovalOriginType.Editor &&
            approval.status === EGraphApprovalStatus.Pending &&
            approval.document_name === documentID
        );
    });
    const approval = approvals[0];
    const approveMutation = useApproveGraphApproval({ interceptToast: true });
    const rejectMutation = useRejectGraphApproval({ interceptToast: true });

    if (!approval) {
        return null;
    }

    return (
        <EditorGraphApprovalBannerContent
            approval={approval}
            effectiveProjectUID={effectiveProjectUID}
            approveMutation={approveMutation}
            rejectMutation={rejectMutation}
        />
    );
}

function EditorGraphApprovalBannerContent({
    approval,
    effectiveProjectUID,
    approveMutation,
    rejectMutation,
}: {
    approval: GraphApprovalRequestModel.TModel;
    effectiveProjectUID: string;
    approveMutation: ReturnType<typeof useApproveGraphApproval>;
    rejectMutation: ReturnType<typeof useRejectGraphApproval>;
}): React.JSX.Element {
    const [t] = useTranslation();
    const approvalUID = approval.useField("uid");
    const title = useGraphApprovalTitle(approval, t("bot.Editor approval requested"));
    const summary = useGraphApprovalSummary(approval);

    return (
        <Flex
            direction="col"
            gap="2"
            className="absolute inset-x-3 top-3 z-20 rounded-xl border border-primary/30 bg-background/95 p-3 shadow-lg backdrop-blur"
        >
            <Flex items="start" gap="2">
                <Box className="mt-0.5 rounded-full bg-primary/10 p-1.5 text-primary">
                    <IconComponent icon="hand" size="4" />
                </Box>
                <Box className="min-w-0 flex-1">
                    <Flex items="center" gap="1.5" wrap={true}>
                        <Box textSize="sm" weight="semibold" className="break-words">
                            {title}
                        </Box>
                        <Badge variant="secondary" className="px-2 py-0 text-[11px]">
                            {t("bot.Human input required")}
                        </Badge>
                    </Flex>
                    {summary && (
                        <Box textSize="xs" className="mt-1 line-clamp-3 break-words text-muted-foreground">
                            {summary}
                        </Box>
                    )}
                </Box>
            </Flex>
            <Flex items="center" justify="end" gap="1.5">
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 px-3"
                    disabled={approveMutation.isPending || rejectMutation.isPending}
                    onClick={() => rejectMutation.mutate({ project_uid: effectiveProjectUID, approval_uid: approvalUID })}
                >
                    {t("bot.Reject")}
                </Button>
                <Button
                    type="button"
                    size="sm"
                    className="h-7 px-3"
                    disabled={approveMutation.isPending || rejectMutation.isPending}
                    onClick={() => approveMutation.mutate({ project_uid: effectiveProjectUID, approval_uid: approvalUID })}
                >
                    {t("bot.Approve")}
                </Button>
            </Flex>
        </Flex>
    );
}
