export const SUPPORTED_LOCALES = ["en-US", "ko-KR", "ja-JP", "zh-CN"] as const;
export type TSupportedLocale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: TSupportedLocale = "en-US";
export const FALLBACK_LOCALE: TSupportedLocale = "en-US";

/** Canonicalize supported browser aliases; Traditional Chinese is not Simplified Chinese. */
export function normalizeLocale(value: unknown): TSupportedLocale {
    if (typeof value !== "string") return DEFAULT_LOCALE;
    const locale = value.trim().replaceAll("_", "-").toLowerCase();
    if (!/^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$/.test(locale)) return DEFAULT_LOCALE;
    if (locale === "ko" || locale === "ko-kr") return "ko-KR";
    if (locale === "ja" || locale === "ja-jp") return "ja-JP";
    if (["zh", "zh-cn", "zh-hans", "zh-hans-cn"].includes(locale)) return "zh-CN";
    return DEFAULT_LOCALE;
}
