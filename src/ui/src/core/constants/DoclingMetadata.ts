export const DOCLING_DOCUMENTS_METADATA_KEY = "__system.docling_documents";

export enum EDoclingIndexStatus {
    Pending = "pending",
    Processing = "processing",
    Disabled = "disabled",
    Indexed = "indexed",
    Failed = "failed",
}

export interface IDoclingMetadataEntry {
    attachment_uid: string;
    document_type: string;
    status: EDoclingIndexStatus;
    completed_pages?: number;
    total_pages?: number;
    progress_percent?: number;
    content_hash?: string;
    indexed_at?: string;
    error_message?: string;
    embedding?: { status?: "pending" | "indexed" | "failed"; error?: string };
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

export function documentDisplayTags(content: Record<string, unknown> | undefined, preferredLanguage?: string): string[] {
    const keywords = content?.search_keywords;
    if (!keywords || typeof keywords !== "object" || Array.isArray(keywords)) return [];
    const language = (preferredLanguage || "en").toLowerCase().split(/[-_]/)[0];
    const attributes = keywords as Record<string, unknown>;
    const clean = (value: unknown): string[] =>
        Array.isArray(value)
            ? [
                  ...new Set(
                      value
                          .filter((word): word is string => typeof word === "string")
                          .map((word) => word.trim().replace(/^#+/, ""))
                          .filter((word) => word.length > 0 && word.length <= 80)
                  ),
              ].slice(0, 5)
            : [];
    const localized = clean(attributes[language]);
    return localized.length ? localized : clean(attributes.en);
}
