import { Hocuspocus } from "@hocuspocus/server";
import Auth from "@/core/security/Auth";
import Cache from "@/core/caching/Cache";
import EditorSyncStorage from "@/core/server/EditorSyncStorage";
import ISocketClient from "@/core/server/ISocketClient";
import Subscription from "@/core/server/Subscription";
import User from "@/models/User";
import { ESettingSocketTopicID, ESocketTopic } from "@langboard/core/enums";
import { EEditorCollaborationType } from "@langboard/core/constants";
import * as Y from "yjs";
import Logger from "@/core/utils/Logger";

const EDITOR_SYNC_ACTIVE_DOCUMENT_CACHE_TTL_SECONDS = 60 * 60;
const EDITOR_SYNC_RECENT_ACTIVE_DOCUMENT_CACHE_TTL_SECONDS = 60;
const EDITOR_SYNC_ACTIVE_DOCUMENT_CACHE_KEY_PREFIX = "editor-sync:active-document:";
const EDITOR_SYNC_ACTIVE_DOCUMENT_SCOPE_CACHE_KEY_PREFIX = "editor-sync:active-document-scope:";

interface IHocusDocumentAccess {
    topic: ESocketTopic;
    topicId: string;
}

interface IHocusDocumentName {
    entityId: string;
    sectionName: string | null;
    type: string;
}

interface IActiveDocumentScopeCache {
    document_names: string[];
    expires_at: number;
}

const createPermissionDeniedError = (reason: string) => {
    return Object.assign(new Error(reason), { reason });
};

const createActiveDocumentCacheKey = (documentName: string) => `${EDITOR_SYNC_ACTIVE_DOCUMENT_CACHE_KEY_PREFIX}${documentName}`;
const createActiveDocumentScopeCacheKey = (type: string, entityId: string) =>
    `${EDITOR_SYNC_ACTIVE_DOCUMENT_SCOPE_CACHE_KEY_PREFIX}${type}:${entityId}`;

const setActiveDocument = async (documentName: string, clientsCount: number, ttlSeconds: number = EDITOR_SYNC_ACTIVE_DOCUMENT_CACHE_TTL_SECONDS) => {
    await Cache.set(
        createActiveDocumentCacheKey(documentName),
        {
            clients_count: clientsCount,
            document_name: documentName,
            expires_at: Date.now() + ttlSeconds * 1000,
        },
        ttlSeconds
    );

    await addActiveDocumentToScope(documentName, ttlSeconds);
};

const deleteActiveDocument = async (documentName: string) => {
    await Cache.delete(createActiveDocumentCacheKey(documentName));
    await removeActiveDocumentFromScope(documentName);
};

const addActiveDocumentToScope = async (documentName: string, ttlSeconds: number = EDITOR_SYNC_ACTIVE_DOCUMENT_CACHE_TTL_SECONDS) => {
    const parsed = parseDocumentName(documentName);
    if (!parsed) {
        return;
    }

    const cacheKey = createActiveDocumentScopeCacheKey(parsed.type, parsed.entityId);
    const cached = await Cache.get<IActiveDocumentScopeCache>(cacheKey);
    const documentNames = cached?.document_names ?? [];
    if (!documentNames.includes(documentName)) {
        documentNames.push(documentName);
    }

    await Cache.set(
        cacheKey,
        {
            document_names: documentNames,
            expires_at: Date.now() + ttlSeconds * 1000,
        },
        ttlSeconds
    );
};

const removeActiveDocumentFromScope = async (documentName: string) => {
    const parsed = parseDocumentName(documentName);
    if (!parsed) {
        return;
    }

    const cacheKey = createActiveDocumentScopeCacheKey(parsed.type, parsed.entityId);
    const cached = await Cache.get<IActiveDocumentScopeCache>(cacheKey);
    if (!cached) {
        return;
    }

    const documentNames = cached.document_names.filter((name) => name !== documentName);
    if (documentNames.length === 0) {
        await Cache.delete(cacheKey);
        return;
    }

    await Cache.set(
        cacheKey,
        {
            document_names: documentNames,
            expires_at: Date.now() + EDITOR_SYNC_ACTIVE_DOCUMENT_CACHE_TTL_SECONDS * 1000,
        },
        EDITOR_SYNC_ACTIVE_DOCUMENT_CACHE_TTL_SECONDS
    );
};

export const isEditorSyncDocumentActive = async (documentName: string) => {
    const cached = await Cache.get<{ expires_at?: number }>(createActiveDocumentCacheKey(documentName));
    if (!cached || !cached.expires_at) {
        return false;
    }

    if (cached.expires_at <= Date.now()) {
        await deleteActiveDocument(documentName);
        return false;
    }

    return true;
};

export const getActiveEditorSyncDocumentNames = async (type: string, entityId: string) => {
    const cacheKey = createActiveDocumentScopeCacheKey(type, entityId);
    const cached = await Cache.get<IActiveDocumentScopeCache>(cacheKey);
    if (!cached || !cached.expires_at) {
        return [];
    }

    if (cached.expires_at <= Date.now()) {
        await Cache.delete(cacheKey);
        return [];
    }

    const activeDocumentNames: string[] = [];
    for (const documentName of cached.document_names) {
        if (await isEditorSyncDocumentActive(documentName)) {
            activeDocumentNames.push(documentName);
        }
    }

    if (activeDocumentNames.length !== cached.document_names.length) {
        if (activeDocumentNames.length === 0) {
            await Cache.delete(cacheKey);
        } else {
            await Cache.set(
                cacheKey,
                {
                    document_names: activeDocumentNames,
                    expires_at: Date.now() + EDITOR_SYNC_ACTIVE_DOCUMENT_CACHE_TTL_SECONDS * 1000,
                },
                EDITOR_SYNC_ACTIVE_DOCUMENT_CACHE_TTL_SECONDS
            );
        }
    }

    return activeDocumentNames;
};

const validateDocumentAccess = async (documentName: string, user: User) => {
    const access = getDocumentAccess(documentName);
    if (!access) {
        throw createPermissionDeniedError("invalid-document");
    }

    const isAllowed = await Subscription.validate(access.topic, {
        client: createValidatorClient(user),
        topicId: access.topicId,
    });
    if (!isAllowed) {
        throw createPermissionDeniedError("permission-denied");
    }
};

const createValidatorClient = (user: User): ISocketClient => {
    return {
        get user() {
            return user;
        },
        subscribe: async () => {},
        unsubscribe: async () => {},
        send: () => {},
        registerCloseHandler: () => () => {},
        onClose: () => {},
    };
};

const getAuthenticatedUser = async ({
    context,
    requestParameters,
    token,
}: {
    context: Record<string, unknown>;
    requestParameters: URLSearchParams;
    token: string;
}) => {
    if (context.user) {
        return context.user as User;
    }

    const parameters = new URLSearchParams(requestParameters);
    if (token) {
        parameters.set("authorization", token);
    }

    return await Auth.validateToken("socket", parameters);
};

const parseDocumentName = (documentName: string): IHocusDocumentName | null => {
    const parts = documentName.split(":") as [string, string?, string?, ...string[]];
    const [type, entityId, sectionName, ...extraParts] = parts;
    if (!type || !entityId || extraParts.length > 0) {
        return null;
    }

    return {
        entityId,
        sectionName: sectionName ?? null,
        type,
    };
};

const getAppSettingsTopicID = (sectionName: string | null): ESettingSocketTopicID | null => {
    switch (sectionName) {
        case "bot":
        case "bot-value":
            return ESettingSocketTopicID.Bot;
        case "global-relationship":
            return ESettingSocketTopicID.GlobalRelationship;
        case "api-comfort-tool":
            return ESettingSocketTopicID.ApiComfortTool;
        case "api-key":
            return ESettingSocketTopicID.ApiKey;
        case "internal-bot":
        case "internal-bot-value":
            return ESettingSocketTopicID.InternalBot;
        case "mcp-tool-group":
            return ESettingSocketTopicID.McpToolGroup;
        case "notification-schedule-rule":
            return ESettingSocketTopicID.NotificationSchedule;
        case "user":
            return ESettingSocketTopicID.User;
        case "webhook":
            return ESettingSocketTopicID.Webhook;
        default:
            return null;
    }
};

const getDocumentAccess = (documentName: string): IHocusDocumentAccess | null => {
    const parsed = parseDocumentName(documentName);
    if (!parsed) {
        return null;
    }

    switch (parsed.type) {
        case EEditorCollaborationType.AppSettings: {
            const topicId = getAppSettingsTopicID(parsed.sectionName);
            return topicId ? { topic: ESocketTopic.AppSettings, topicId } : null;
        }
        case EEditorCollaborationType.Card:
            return { topic: ESocketTopic.BoardCard, topicId: parsed.entityId };
        case EEditorCollaborationType.BoardColumnName:
            return { topic: ESocketTopic.Board, topicId: parsed.entityId };
        case EEditorCollaborationType.BoardSettings:
        case EEditorCollaborationType.BotSchedule:
            return { topic: ESocketTopic.BoardSettings, topicId: parsed.entityId };
        case EEditorCollaborationType.Wiki:
            return { topic: ESocketTopic.BoardWikiPrivate, topicId: parsed.entityId };
        default:
            return null;
    }
};

const Hocus = new Hocuspocus({
    async connected({ documentName }) {
        await setActiveDocument(documentName, 1);
    },
    async onAuthenticate({ context, documentName, requestParameters, token }) {
        const user = await getAuthenticatedUser({ context, requestParameters, token });
        if (!user) {
            throw createPermissionDeniedError("unauthorized");
        }

        await validateDocumentAccess(documentName, user);

        return { user };
    },
    async onLoadDocument({ documentName, document }) {
        const state = await EditorSyncStorage.load(documentName);
        if (!state) {
            return;
        }

        Y.applyUpdate(document, state);
    },
    async onStoreDocument({ documentName, document }) {
        await EditorSyncStorage.save(documentName, Y.encodeStateAsUpdate(document));
    },
    async onDisconnect({ clientsCount, documentName }) {
        try {
            if (clientsCount > 0) {
                await setActiveDocument(documentName, clientsCount);
                return;
            }

            await setActiveDocument(documentName, 0, EDITOR_SYNC_RECENT_ACTIVE_DOCUMENT_CACHE_TTL_SECONDS);
        } catch (error) {
            Logger.error(error, "\n");
        }
    },
    async beforeUnloadDocument({ documentName }) {
        try {
            await setActiveDocument(documentName, 0, EDITOR_SYNC_RECENT_ACTIVE_DOCUMENT_CACHE_TTL_SECONDS);
        } catch (error) {
            Logger.error(error, "\n");
        }
    },
});

export const getEditorSyncText = async (documentName: string, field: string, user: User) => {
    await validateDocumentAccess(documentName, user);

    const connection = await Hocus.openDirectConnection(documentName, { user });
    try {
        const document = connection.document;
        if (!document) {
            return "";
        }

        return document.getText(field).toString();
    } finally {
        await connection.disconnect();
    }
};

export const patchEditorSyncText = async (documentName: string, field: string, value: string, user: User) => {
    await validateDocumentAccess(documentName, user);

    const connection = await Hocus.openDirectConnection(documentName, { user });
    try {
        await connection.transact((document) => {
            const text = document.getText(field);
            text.delete(0, text.length);
            text.insert(0, value);
        });
    } finally {
        await connection.disconnect();
    }
};

export const requestEditorSyncRichPatch = async (documentName: string, value: string, user: User) => {
    await validateDocumentAccess(documentName, user);

    const access = getDocumentAccess(documentName);
    if (!access) {
        throw createPermissionDeniedError("invalid-document");
    }

    await Subscription.publish(access.topic, access.topicId, "editor-sync:rich-draft-patch-request", {
        document_name: documentName,
        value,
    });
};

export const clearInactiveEditorSyncDocument = async (documentName: string, user: User) => {
    await validateDocumentAccess(documentName, user);

    if (await isEditorSyncDocumentActive(documentName)) {
        throw createPermissionDeniedError("active-document");
    }

    await EditorSyncStorage.delete(documentName);
};

export default Hocus;
