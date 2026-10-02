import { normalizeLocale } from "./LocalePolicy.ts";

/** Locale affects presentation only; callers retain the existing browser timezone unless explicitly supplied. */
export function formatDateTime(date: Date, locale: unknown, options: Intl.DateTimeFormatOptions = {}) {
    return new Intl.DateTimeFormat(normalizeLocale(locale), { dateStyle: "medium", timeStyle: "short", ...options }).format(date);
}

export function formatDateDistance(date: Date, locale: unknown, now: number = Date.now()) {
    const delta = date.getTime() - now;
    if (Math.abs(delta) >= 86400000) return formatDateTime(date, locale);
    // Keep metadata compact; seconds remain available in the exact timestamp tooltip.
    const unit = Math.abs(delta) >= 3600000 ? "hour" : "minute";
    const divisor = unit === "hour" ? 3600000 : 60000;
    const value = Math.trunc(delta / divisor);
    return new Intl.RelativeTimeFormat(normalizeLocale(locale), { numeric: "always" }).format(value === 0 ? 0 : value, unit);
}
