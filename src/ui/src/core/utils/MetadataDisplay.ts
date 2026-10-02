interface MetadataText {
    name: string;
    description: string;
}

/** Presentation only: immutable keys and canonical API fields remain unchanged. */
export function metadataDisplay(canonical: MetadataText, translations: Record<string, MetadataText> | undefined, language: string): MetadataText {
    const exact = translations?.[language];
    const base = translations?.[language.split("-")[0]];
    return {
        name: exact?.name || base?.name || canonical.name || translations?.["en-US"]?.name || translations?.en?.name || "",
        description:
            exact?.description ||
            base?.description ||
            canonical.description ||
            translations?.["en-US"]?.description ||
            translations?.en?.description ||
            "",
    };
}
