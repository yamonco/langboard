/** Only canonical references can target native history; aliases are not identities. */
export function secretReferenceHistoryHref(uri: unknown): string | undefined {
    if (typeof uri !== "string") return undefined;
    const match = /^secret:\/\/ref\/([A-Za-z0-9]{1,11})$/.exec(uri);
    return match ? `/secret-references/${match[1]}/history` : undefined;
}
