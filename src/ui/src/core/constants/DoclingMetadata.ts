export const DOCLING_DOCUMENTS_METADATA_KEY = "__system.docling_documents";

export enum EDoclingIndexStatus {
    Pending = "pending",
    Indexed = "indexed",
    Failed = "failed",
}

export interface IDoclingMetadataEntry {
    attachment_uid: string;
    document_type: string;
    status: EDoclingIndexStatus;
    content_hash?: string;
    indexed_at?: string;
    error_message?: string;
    content: Record<string, unknown>;
}

export function parseDoclingMetadata(metadata: Record<string, string> | undefined): IDoclingMetadataEntry[] {
    const value = metadata?.[DOCLING_DOCUMENTS_METADATA_KEY];
    if (!value) {
        return [];
    }

    try {
        const documents = JSON.parse(value);
        return Array.isArray(documents) ? documents.filter((document) => document && typeof document === "object") : [];
    } catch {
        return [];
    }
}
