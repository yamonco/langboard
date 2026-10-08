import { metadataDisplay } from "@/core/utils/MetadataDisplay";

export const CARD_PRESENTATION_KEY = "card.presentation.v1";
export interface ICardPresentation {
    version: 1;
    key: string;
    axis: "type" | "origin";
    name: string;
    description: string;
    icon?: string;
    translations?: Record<string, { name: string; description: string }>;
}

/** Display metadata never grants access, changes workflow, or marks work complete. */
export function parseCardPresentation(value: string | undefined): ICardPresentation | undefined {
    if (!value || value.length > 8192) return undefined;
    try {
        const item = JSON.parse(value);
        const allowed = ["version", "key", "axis", "name", "description", "icon", "translations"];
        if (!item || typeof item !== "object" || Array.isArray(item) || Object.keys(item).some((key) => !allowed.includes(String(key)))) return;
        if (item.version !== 1 || !["type", "origin"].includes(item.axis)) return;
        if (typeof item.key !== "string" || !/^app\.[a-z][a-z0-9_-]{0,31}\.[a-z][a-z0-9_-]{0,63}$/.test(item.key)) return;
        const text = (value: unknown, max: number) => typeof value === "string" && value.trim().length > 0 && value.length <= max;
        if (!text(item.name, 80) || !text(item.description, 1000) || (item.icon !== undefined && !text(item.icon, 32))) return;
        if (item.translations !== undefined) {
            if (!item.translations || typeof item.translations !== "object" || Array.isArray(item.translations)) return;
            const locales = Object.entries(item.translations);
            if (locales.length > 16) return;
            for (const [locale, value] of locales) {
                if (!/^[a-z]{2,3}(-[A-Za-z0-9]{2,8}){0,2}$/.test(String(locale))) return;
                const translation = value as Record<string, unknown>;
                if (!translation || typeof translation !== "object" || Array.isArray(translation)) return;
                if (Object.keys(translation).some((key) => !["name", "description"].includes(String(key)))) return;
                if (!text(translation.name, 80) || !text(translation.description, 1000)) return;
            }
        }
        return item;
    } catch {
        return undefined;
    }
}

export const CARD_VISIBILITY_PRESENTATIONS = {
    private: { key: "visibility.private", icon: "🔐", nameKey: "card.Private", descriptionKey: "card.Private visibility guidance" },
    whisper: { key: "visibility.whisper", icon: "🤫", nameKey: "card.Whisper", descriptionKey: "card.Whisper visibility guidance" },
} as const;

export function cardVisibilityPresentation(visibility: string | undefined, hasExternalMember: boolean): "private" | "whisper" | undefined {
    if (visibility === "PRIVATE") return "private";
    return visibility === "INTERNAL" && hasExternalMember ? "whisper" : undefined;
}

export function cardPresentationText(item: ICardPresentation, language: string): { name: string; description: string } {
    return metadataDisplay(item, item.translations, language);
}
