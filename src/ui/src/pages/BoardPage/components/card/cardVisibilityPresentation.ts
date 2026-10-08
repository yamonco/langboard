export function cardVisibilityPresentation(visibility: string | undefined, hasExternalMember: boolean): "private" | "whisper" | undefined {
    if (visibility === "PRIVATE") return "private";
    return visibility === "INTERNAL" && hasExternalMember ? "whisper" : undefined;
}
