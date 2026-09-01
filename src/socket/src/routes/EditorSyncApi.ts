import { EDITOR_SYNC_MAX_CONCURRENCY, EDITOR_SYNC_MAX_REQUEST_SIZE_MB } from "@/Constants";
import { JsonResponse } from "@/core/server/ApiResponse";
import Routes, { TRouteHandler } from "@/core/server/Routes";
import {
    clearInactiveEditorSyncDocument,
    getEditorSyncText,
    isEditorSyncDocumentActive,
    patchEditorSyncText,
    requestEditorSyncRichPatch,
} from "@/core/server/Hocus";
import { EHttpStatus } from "@langboard/core/enums";
import { Utils } from "@langboard/core/utils";
import { IncomingMessage } from "http";

let activeRequests = 0;

const registerEditorSyncRoute = (path: string, handler: TRouteHandler) => {
    Routes.post(path, async (context) => {
        if (activeRequests >= EDITOR_SYNC_MAX_CONCURRENCY) {
            context.req.resume();
            return JsonResponse({ message: "Too many concurrent editor sync requests." }, EHttpStatus.HTTP_503_SERVICE_UNAVAILABLE);
        }

        activeRequests++;
        try {
            return await handler(context);
        } finally {
            activeRequests--;
        }
    });
};

const readJsonBody = async (req: IncomingMessage) => {
    const chunks: Buffer[] = [];
    let bodyBytes = 0;
    for await (const chunk of req) {
        const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
        bodyBytes += buffer.byteLength;
        if (bodyBytes > EDITOR_SYNC_MAX_REQUEST_SIZE_MB * 1024 * 1024) {
            req.resume();
            throw new Error(`Editor sync request exceeded ${EDITOR_SYNC_MAX_REQUEST_SIZE_MB} MB`);
        }
        chunks.push(buffer);
    }

    const rawBody = Buffer.concat(chunks).toString("utf-8");
    if (!rawBody) {
        return {};
    }

    return JSON.parse(rawBody);
};

const validateTextPayload = (body: unknown) => {
    if (!Utils.Type.isObject(body)) {
        return null;
    }

    const record = body as Record<string, unknown>;
    const documentName = record.document_name;
    const field = record.field;
    if (!Utils.Type.isString(documentName) || !Utils.Type.isString(field)) {
        return null;
    }

    return { documentName, field, record };
};

registerEditorSyncRoute("/editor-sync/text", async ({ req, user }) => {
    try {
        const body = await readJsonBody(req);
        const payload = validateTextPayload(body);
        if (!payload) {
            return JsonResponse({ message: "Invalid editor sync text payload." }, EHttpStatus.HTTP_400_BAD_REQUEST);
        }
        if (!(await isEditorSyncDocumentActive(payload.documentName))) {
            return JsonResponse({ message: "The collaborative draft is not active." }, EHttpStatus.HTTP_409_CONFLICT);
        }

        const value = await getEditorSyncText(payload.documentName, payload.field, user);
        return JsonResponse({ value });
    } catch (error) {
        const reason = error instanceof Error ? error.message : "Failed to get editor sync text.";
        return JsonResponse({ message: reason }, EHttpStatus.HTTP_403_FORBIDDEN);
    }
});

registerEditorSyncRoute("/editor-sync/active", async ({ req }) => {
    try {
        const body = await readJsonBody(req);
        if (!Utils.Type.isObject(body)) {
            return JsonResponse({ message: "Invalid editor sync active payload." }, EHttpStatus.HTTP_400_BAD_REQUEST);
        }

        const record = body as Record<string, unknown>;
        if (!Array.isArray(record.document_names)) {
            return JsonResponse({ message: "Invalid editor sync active payload." }, EHttpStatus.HTTP_400_BAD_REQUEST);
        }

        const documentNames = record.document_names.filter(Utils.Type.isString);
        const activeDocumentNames: string[] = [];

        for (const documentName of documentNames) {
            if (await isEditorSyncDocumentActive(documentName)) {
                activeDocumentNames.push(documentName);
            }
        }

        return JsonResponse({ active_document_names: activeDocumentNames });
    } catch (error) {
        const reason = error instanceof Error ? error.message : "Failed to get active editor sync documents.";
        return JsonResponse({ message: reason }, EHttpStatus.HTTP_400_BAD_REQUEST);
    }
});

registerEditorSyncRoute("/editor-sync/text/patch", async ({ req, user }) => {
    try {
        const body = await readJsonBody(req);
        const payload = validateTextPayload(body);
        if (!payload || !Utils.Type.isString(payload.record.value)) {
            return JsonResponse({ message: "Invalid editor sync text patch payload." }, EHttpStatus.HTTP_400_BAD_REQUEST);
        }
        if (!(await isEditorSyncDocumentActive(payload.documentName))) {
            return JsonResponse({ message: "The collaborative draft is not active." }, EHttpStatus.HTTP_409_CONFLICT);
        }

        await patchEditorSyncText(payload.documentName, payload.field, payload.record.value, user);
        return JsonResponse({});
    } catch (error) {
        const reason = error instanceof Error ? error.message : "Failed to patch editor sync text.";
        return JsonResponse({ message: reason }, EHttpStatus.HTTP_403_FORBIDDEN);
    }
});

registerEditorSyncRoute("/editor-sync/rich/patch-request", async ({ req, user }) => {
    try {
        const body = await readJsonBody(req);
        if (!Utils.Type.isObject(body)) {
            return JsonResponse({ message: "Invalid editor sync rich patch request payload." }, EHttpStatus.HTTP_400_BAD_REQUEST);
        }

        const record = body as Record<string, unknown>;
        if (!Utils.Type.isString(record.document_name) || !Utils.Type.isString(record.value)) {
            return JsonResponse({ message: "Invalid editor sync rich patch request payload." }, EHttpStatus.HTTP_400_BAD_REQUEST);
        }
        if (!(await isEditorSyncDocumentActive(record.document_name))) {
            return JsonResponse({ message: "The collaborative draft is not active." }, EHttpStatus.HTTP_409_CONFLICT);
        }

        await requestEditorSyncRichPatch(record.document_name, record.value, user);
        return JsonResponse({});
    } catch (error) {
        const reason = error instanceof Error ? error.message : "Failed to request editor sync rich patch.";
        return JsonResponse({ message: reason }, EHttpStatus.HTTP_403_FORBIDDEN);
    }
});

registerEditorSyncRoute("/editor-sync/clear", async ({ req, user }) => {
    try {
        const body = await readJsonBody(req);
        if (!Utils.Type.isObject(body)) {
            return JsonResponse({ message: "Invalid editor sync clear payload." }, EHttpStatus.HTTP_400_BAD_REQUEST);
        }

        const record = body as Record<string, unknown>;
        if (!Array.isArray(record.document_names)) {
            return JsonResponse({ message: "Invalid editor sync clear payload." }, EHttpStatus.HTTP_400_BAD_REQUEST);
        }

        const documentNames = record.document_names.filter(Utils.Type.isString);
        for (const documentName of documentNames) {
            await clearInactiveEditorSyncDocument(documentName, user);
        }

        return JsonResponse({});
    } catch (error) {
        const reason = error instanceof Error ? error.message : "Failed to clear editor sync documents.";
        return JsonResponse({ message: reason }, EHttpStatus.HTTP_403_FORBIDDEN);
    }
});
