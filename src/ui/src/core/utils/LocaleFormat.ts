import { normalizeLocale } from "./LocalePolicy.ts";

/** Locale affects presentation only; callers retain the existing browser timezone unless explicitly supplied. */
export function formatDateTime(date: Date, locale: unknown, options: Intl.DateTimeFormatOptions = {}) {
    return new Intl.DateTimeFormat(normalizeLocale(locale), { dateStyle: "medium", timeStyle: "short", ...options }).format(date);
}

export function formatDateDistance(date: Date, locale: unknown, now: number = Date.now()) {
    const delta = date.getTime() - now;
    if (Math.abs(delta) >= 86400000) return formatDateTime(date, locale);
    // Keep metadata compact; seconds remain available in the exact timestamp tooltip.
    if (Math.abs(delta) < 60000) return new Intl.RelativeTimeFormat(normalizeLocale(locale), { numeric: "auto" }).format(0, "second");
    const unit = Math.abs(delta) >= 3600000 ? "hour" : "minute";
    const divisor = unit === "hour" ? 3600000 : 60000;
    const value = Math.trunc(delta / divisor);
    return new Intl.RelativeTimeFormat(normalizeLocale(locale), { numeric: "always" }).format(value, unit);
}

export function formatNumber(value: number, locale: unknown, options: Intl.NumberFormatOptions = {}) {
    return new Intl.NumberFormat(normalizeLocale(locale), options).format(value);
}

/** Preserve the timer's existing approximate year/month conversion and 100-hour compactness limit. */
export function formatTimerDuration(
    duration: { years?: number; months?: number; days?: number; hours?: number; minutes?: number; seconds?: number },
    locale: unknown
) {
    const hours = (duration.hours ?? 0) + (duration.years ?? 0) * 365 * 24 + (duration.months ?? 0) * 30 * 24 + (duration.days ?? 0) * 24;
    const parts: string[] = [];
    const unit = (value: number, name: string) => formatNumber(value, locale, { style: "unit", unit: name, unitDisplay: "narrow" });
    if (hours > 0) parts.push(unit(hours, "hour"));
    if (hours < 100) {
        if (duration.minutes) parts.push(unit(duration.minutes, "minute"));
        if (duration.seconds) parts.push(unit(duration.seconds, "second"));
    }
    return parts.length ? parts.join(" ") : unit(0, "second");
}
