import { useAuth } from "@/core/providers/AuthProvider";
import { useSocket } from "@/core/providers/SocketProvider";
import { getEditorWebSocketAuth } from "@/core/stores/socket/transport";
import { TEditorCollaborationType } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import { HocuspocusProvider } from "@hocuspocus/provider";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as Y from "yjs";

export interface IUseCollaborativeTextProps {
    collaborationType?: TEditorCollaborationType;
    documentID?: string;
    field: string;
    section?: number | string;
    uid?: number | string;
    defaultValue?: string | number | readonly string[];
    disabled?: bool;
    preserveSyncedValue?: bool;
    resetSyncedValueToDefault?: bool;
    onValueChange?: (value: string) => void;
}

export interface ICollaborativeTextCursor {
    clientID: number;
    color: string;
    name: string;
    selectionEnd: number;
    selectionStart: number;
}

export interface ICollaborativeTextMeta<TValue = unknown> {
    clientID: number;
    color: string;
    name: string;
    userID?: string;
    value: TValue;
}

interface IAwarenessTextSelection {
    color: string;
    field: string;
    name: string;
    selectionEnd: number;
    selectionStart: number;
    userID?: string;
}

interface IAwarenessTextMeta<TValue = unknown> {
    color: string;
    field: string;
    name: string;
    userID?: string;
    value: TValue;
}

interface ISharedProviderState {
    isConnected: bool;
    isSynced: bool;
}

interface ISharedProviderEntry {
    document: Y.Doc;
    provider: HocuspocusProvider;
    refCount: number;
    cleanupTimeoutID?: number;
    state: ISharedProviderState;
    stateListeners: Set<(state: ISharedProviderState) => void>;
}

const sharedProviderEntries = new Map<string, ISharedProviderEntry>();

const normalizeValue = (value: IUseCollaborativeTextProps["defaultValue"]) => {
    if (Array.isArray(value)) {
        return value.join("");
    }

    return value?.toString() ?? "";
};

const notifySharedProviderState = (entry: ISharedProviderEntry) => {
    entry.stateListeners.forEach((listener) => listener(entry.state));
};

export const useCollaborativeText = ({
    collaborationType,
    documentID,
    field,
    section,
    uid,
    defaultValue,
    disabled,
    preserveSyncedValue,
    resetSyncedValueToDefault,
    onValueChange,
}: IUseCollaborativeTextProps) => {
    const socket = useSocket();
    const { currentUser } = useAuth();
    const currentUserUID = currentUser?.uid ?? "";
    const resolvedDocumentID = useMemo(() => {
        if (documentID) {
            return documentID;
        }

        if (!collaborationType || uid === undefined || uid === null) {
            return "";
        }

        return Utils.String.createEditorCollaborationDocumentID({ collaborationType, uid, section });
    }, [collaborationType, documentID, section, uid]);
    const fallbackValue = useMemo(() => normalizeValue(defaultValue), [defaultValue]);
    const fallbackValueRef = useRef(fallbackValue);
    const onValueChangeRef = useRef(onValueChange);
    const userName = useMemo(() => {
        if (!currentUser) {
            return "";
        }

        return `${currentUser.firstname} ${currentUser.lastname}`.trim() || currentUser.username;
    }, [currentUser]);
    const userColor = useMemo(() => new Utils.Color.Generator(userName || "Anonymous").generateRandomColor(), [userName]);
    const [value, setValue] = useState(fallbackValue);
    const [isConnected, setIsConnected] = useState(false);
    const [isSynced, setIsSynced] = useState(false);
    const [remoteCursors, setRemoteCursors] = useState<ICollaborativeTextCursor[]>([]);
    const [remoteMeta, setRemoteMeta] = useState<ICollaborativeTextMeta[]>([]);
    const providerRef = useRef<HocuspocusProvider | null>(null);
    const ytextRef = useRef<Y.Text | null>(null);
    const isApplyingRemoteChangeRef = useRef(false);
    const hasLocalDirtyValueRef = useRef(false);
    const activeBindingKeyRef = useRef("");
    const valueRef = useRef(fallbackValue);

    const hasActiveRemoteFieldEditor = useCallback(() => {
        const provider = providerRef.current;
        const document = ytextRef.current?.doc;
        const awareness = provider?.awareness;
        if (!provider || !document || !awareness) {
            return false;
        }

        return Array.from(awareness.getStates().entries()).some(([clientID, state]) => {
            if (clientID === document.clientID) {
                return false;
            }

            const selection = state.collaborativeTextSelection as IAwarenessTextSelection | undefined;
            const meta = state.collaborativeTextMeta as IAwarenessTextMeta | undefined;
            return selection?.field === field || meta?.field === field;
        });
    }, [field]);

    useEffect(() => {
        fallbackValueRef.current = fallbackValue;
    }, [fallbackValue]);

    useEffect(() => {
        if (ytextRef.current) {
            return;
        }

        valueRef.current = fallbackValue;
        setValue(fallbackValue);
    }, [fallbackValue]);

    useEffect(() => {
        onValueChangeRef.current = onValueChange;
    }, [onValueChange]);

    useEffect(() => {
        const bindingKey = `${currentUserUID}:${resolvedDocumentID}:${field}`;
        if (activeBindingKeyRef.current !== bindingKey) {
            activeBindingKeyRef.current = bindingKey;
            hasLocalDirtyValueRef.current = false;
        }

        let disposed = false;

        if (disabled || !resolvedDocumentID) {
            hasLocalDirtyValueRef.current = false;
            valueRef.current = fallbackValueRef.current;
            setValue(fallbackValueRef.current);
            setIsConnected(false);
            setIsSynced(false);
            setRemoteCursors([]);
            setRemoteMeta([]);
            return;
        }

        if (!currentUserUID) {
            hasLocalDirtyValueRef.current = false;
            valueRef.current = fallbackValueRef.current;
            setValue(fallbackValueRef.current);
            setIsConnected(false);
            setIsSynced(false);
            setRemoteCursors([]);
            setRemoteMeta([]);
            return;
        }

        const url = socket.getAuthorizedWebSocketUrl("editor-sync");
        const auth = url ? getEditorWebSocketAuth(url, resolvedDocumentID) : null;
        if (!auth) {
            hasLocalDirtyValueRef.current = false;
            valueRef.current = fallbackValueRef.current;
            setValue(fallbackValueRef.current);
            setIsConnected(false);
            setIsSynced(false);
            setRemoteCursors([]);
            setRemoteMeta([]);
            return;
        }

        const providerKey = `${resolvedDocumentID}:${auth.token}`;
        let sharedEntry = sharedProviderEntries.get(providerKey);

        if (!sharedEntry) {
            const document = new Y.Doc();
            sharedEntry = {
                document,
                provider: null as unknown as HocuspocusProvider,
                refCount: 0,
                state: {
                    isConnected: false,
                    isSynced: false,
                },
                stateListeners: new Set(),
            };

            const provider = new HocuspocusProvider({
                document,
                name: resolvedDocumentID,
                token: auth.token,
                url: auth.url,
                onAuthenticated: () => {},
                onConnect: () => {
                    sharedEntry!.state = {
                        ...sharedEntry!.state,
                        isConnected: true,
                    };
                    notifySharedProviderState(sharedEntry!);
                },
                onDisconnect: () => {
                    sharedEntry!.state = {
                        isConnected: false,
                        isSynced: false,
                    };
                    notifySharedProviderState(sharedEntry!);
                },
                onAuthenticationFailed: () => {
                    sharedEntry!.state = {
                        isConnected: false,
                        isSynced: false,
                    };
                    notifySharedProviderState(sharedEntry!);
                },
                onSynced: () => {
                    sharedEntry!.state = {
                        ...sharedEntry!.state,
                        isSynced: true,
                    };
                    notifySharedProviderState(sharedEntry!);
                },
                onClose: () => {
                    sharedEntry!.state = {
                        isConnected: false,
                        isSynced: false,
                    };
                    notifySharedProviderState(sharedEntry!);
                },
            });

            sharedEntry.provider = provider;
            sharedProviderEntries.set(providerKey, sharedEntry);
        } else if (sharedEntry.cleanupTimeoutID !== undefined) {
            window.clearTimeout(sharedEntry.cleanupTimeoutID);
            sharedEntry.cleanupTimeoutID = undefined;
        }

        sharedEntry.refCount += 1;
        const document = sharedEntry.document;
        const provider = sharedEntry.provider;
        const text = document.getText(field);
        ytextRef.current = text;
        providerRef.current = provider;

        const applySyncedText = () => {
            if (disposed) {
                return;
            }

            setIsSynced(true);
            const fallbackValue = fallbackValueRef.current;
            const currentValue = text.toString();
            if (resetSyncedValueToDefault && currentValue !== fallbackValue && !hasLocalDirtyValueRef.current && !hasActiveRemoteFieldEditor()) {
                text.doc?.transact(() => {
                    text.delete(0, text.length);
                    if (fallbackValue) {
                        text.insert(0, fallbackValue);
                    }
                });
                hasLocalDirtyValueRef.current = false;
                valueRef.current = fallbackValue;
                setValue(fallbackValue);
                onValueChangeRef.current?.(fallbackValue);
                return;
            }

            if (!currentValue && fallbackValue && !preserveSyncedValue && !hasLocalDirtyValueRef.current && !hasActiveRemoteFieldEditor()) {
                text.doc?.transact(() => {
                    text.delete(0, text.length);
                    text.insert(0, fallbackValue);
                });
                hasLocalDirtyValueRef.current = false;
                valueRef.current = fallbackValue;
                setValue(fallbackValue);
                onValueChangeRef.current?.(fallbackValue);
                return;
            }

            if (currentValue === fallbackValue) {
                hasLocalDirtyValueRef.current = false;
            }
            valueRef.current = currentValue;
            setValue(currentValue);
            onValueChangeRef.current?.(currentValue);
        };

        const handleSharedProviderStateChange = (state: ISharedProviderState) => {
            queueMicrotask(() => {
                if (disposed) {
                    return;
                }

                setIsConnected(state.isConnected);
                setIsSynced(state.isSynced);
                if (state.isSynced) {
                    applySyncedText();
                }
            });
        };

        sharedEntry.stateListeners.add(handleSharedProviderStateChange);
        handleSharedProviderStateChange(sharedEntry.state);

        const updateRemoteCursors = () => {
            if (disposed) {
                return;
            }

            const awareness = provider.awareness;
            if (!awareness) {
                setRemoteCursors([]);
                setRemoteMeta([]);
                return;
            }

            const cursors = Array.from(awareness.getStates().entries()).flatMap(([clientID, state]) => {
                const selection = state.collaborativeTextSelection as IAwarenessTextSelection | undefined;
                if (clientID === document.clientID || selection?.field !== field) {
                    return [];
                }

                return [
                    {
                        clientID,
                        color: selection.color,
                        name: selection.name,
                        selectionEnd: selection.selectionEnd,
                        selectionStart: selection.selectionStart,
                    },
                ];
            });

            setRemoteCursors(cursors);

            const nextRemoteMeta = Array.from(awareness.getStates().entries()).flatMap(([clientID, state]) => {
                const meta = state.collaborativeTextMeta as IAwarenessTextMeta | undefined;
                if (clientID === document.clientID || meta?.field !== field) {
                    return [];
                }

                return [
                    {
                        clientID,
                        color: meta.color,
                        name: meta.name,
                        userID: meta.userID,
                        value: meta.value,
                    },
                ];
            });

            setRemoteMeta(nextRemoteMeta);
        };

        const handleTextChange = () => {
            if (disposed) {
                return;
            }

            const nextValue = text.toString();
            const fallbackValue = fallbackValueRef.current;
            if (resetSyncedValueToDefault && nextValue !== fallbackValue && !hasLocalDirtyValueRef.current && !hasActiveRemoteFieldEditor()) {
                text.doc?.transact(() => {
                    text.delete(0, text.length);
                    if (fallbackValue) {
                        text.insert(0, fallbackValue);
                    }
                });
                hasLocalDirtyValueRef.current = false;
                valueRef.current = fallbackValue;
                setValue(fallbackValue);
                onValueChangeRef.current?.(fallbackValue);
                return;
            }

            isApplyingRemoteChangeRef.current = true;
            valueRef.current = nextValue;
            setValue(nextValue);
            onValueChangeRef.current?.(nextValue);
            queueMicrotask(() => {
                isApplyingRemoteChangeRef.current = false;
            });
        };

        text.observe(handleTextChange);
        provider.awareness?.on("change", updateRemoteCursors);

        return () => {
            disposed = true;
            text.unobserve(handleTextChange);
            provider.awareness?.off("change", updateRemoteCursors);
            const localAwarenessState = provider.awareness?.getLocalState();
            const currentSelection = localAwarenessState?.collaborativeTextSelection as IAwarenessTextSelection | undefined;
            const currentMeta = localAwarenessState?.collaborativeTextMeta as IAwarenessTextMeta | undefined;

            if (currentSelection?.field === field) {
                provider.setAwarenessField("collaborativeTextSelection", null);
            }
            if (currentMeta?.field === field) {
                provider.setAwarenessField("collaborativeTextMeta", null);
            }
            sharedEntry!.stateListeners.delete(handleSharedProviderStateChange);
            sharedEntry!.refCount -= 1;
            if (sharedEntry!.refCount <= 0) {
                sharedEntry!.cleanupTimeoutID = window.setTimeout(() => {
                    if (!sharedEntry || sharedEntry.refCount > 0) {
                        return;
                    }

                    provider.destroy();
                    document.destroy();
                    sharedProviderEntries.delete(providerKey);
                }, 30_000);
            }
            providerRef.current = null;
            ytextRef.current = null;
        };
    }, [currentUserUID, disabled, field, hasActiveRemoteFieldEditor, preserveSyncedValue, resetSyncedValueToDefault, resolvedDocumentID, socket]);

    const updateValue = useCallback((nextValue: string) => {
        hasLocalDirtyValueRef.current = nextValue !== fallbackValueRef.current;
        valueRef.current = nextValue;
        setValue(nextValue);
        onValueChangeRef.current?.(nextValue);

        const text = ytextRef.current;
        if (!text || isApplyingRemoteChangeRef.current) {
            return;
        }

        if (text.toString() === nextValue) {
            return;
        }

        text.doc?.transact(() => {
            text.delete(0, text.length);
            text.insert(0, nextValue);
        });
    }, []);

    const resetValue = useCallback(
        (nextValue: string) => {
            hasLocalDirtyValueRef.current = false;
            valueRef.current = nextValue;
            setValue(nextValue);
            onValueChangeRef.current?.(nextValue);

            const text = ytextRef.current;
            if (!text || hasActiveRemoteFieldEditor()) {
                return;
            }

            if (text.toString() === nextValue) {
                return;
            }

            text.doc?.transact(() => {
                text.delete(0, text.length);
                if (nextValue) {
                    text.insert(0, nextValue);
                }
            });
        },
        [hasActiveRemoteFieldEditor]
    );

    const updateSelection = useCallback(
        (selectionStart: number, selectionEnd: number = selectionStart) => {
            providerRef.current?.setAwarenessField("collaborativeTextSelection", {
                color: userColor,
                field,
                name: userName,
                selectionEnd,
                selectionStart,
                userID: currentUser?.uid,
            } satisfies IAwarenessTextSelection);
        },
        [currentUser, field, userColor, userName]
    );

    const updateMeta = useCallback(
        (nextValue: unknown | null) => {
            providerRef.current?.setAwarenessField(
                "collaborativeTextMeta",
                nextValue === null
                    ? null
                    : ({
                          color: userColor,
                          field,
                          name: userName,
                          userID: currentUser?.uid,
                          value: nextValue,
                      } satisfies IAwarenessTextMeta)
            );
        },
        [currentUser, field, userColor, userName]
    );

    const retrySync = useCallback(() => {
        const provider = providerRef.current;
        if (!provider) {
            socket.reconnect();
            return;
        }

        setIsConnected(false);
        setIsSynced(false);
        provider.disconnect();
        provider.connect().catch(() => {
            setIsConnected(false);
            setIsSynced(false);
        });
    }, [socket]);

    return {
        isConnected,
        isSynced,
        remoteMeta,
        remoteCursors,
        retrySync,
        updateMeta,
        updateSelection,
        value,
        resetValue,
        updateValue,
    };
};
