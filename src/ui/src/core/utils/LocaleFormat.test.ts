import assert from "node:assert/strict";
import { test } from "node:test";
import { formatDateDistance, formatDateTime, formatNumber, formatTimerDuration } from "./LocaleFormat.ts";
import { SUPPORTED_LOCALES } from "./LocalePolicy.ts";

const now = Date.parse("2026-10-03T12:00:00Z");
test("account locale controls dates and past/future relative time in all four languages", () => {
    for (const locale of SUPPORTED_LOCALES) {
        const date = new Date(now);
        assert.equal(
            formatDateTime(date, locale, { timeZone: "UTC" }),
            new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(date)
        );
        for (const minutes of [-120, -5, 5, 120]) {
            const unit = Math.abs(minutes) >= 60 ? "hour" : "minute";
            assert.equal(
                formatDateDistance(new Date(now + minutes * 60000), locale, now),
                new Intl.RelativeTimeFormat(locale, { numeric: "always" }).format(unit === "hour" ? minutes / 60 : minutes, unit)
            );
        }
        assert.equal(formatDateDistance(new Date(now - 86400000), locale, now), formatDateTime(new Date(now - 86400000), locale));
    }
});
test("invalid locale falls back to English without changing timezone policy", () => {
    const date = new Date(now);
    assert.equal(formatDateTime(date, "zh-Hant"), formatDateTime(date, "en-US"));
    assert.equal(formatDateDistance(date, "invalid", now), formatDateDistance(date, "en-US", now));
    assert.notEqual(formatDateTime(date, "en-US", { timeZone: "UTC" }), formatDateTime(date, "en-US", { timeZone: "Asia/Seoul" }));
});

test("localized count and duration preserve zero, mixed units and 100-hour compactness", () => {
    for (const locale of SUPPORTED_LOCALES) {
        const unit = (value: number, name: string) =>
            new Intl.NumberFormat(locale, { style: "unit", unit: name, unitDisplay: "narrow" }).format(value);
        assert.equal(formatNumber(12345, locale), new Intl.NumberFormat(locale).format(12345));
        assert.equal(formatTimerDuration({}, locale), unit(0, "second"));
        assert.equal(
            formatTimerDuration({ hours: 1, minutes: 2, seconds: 3 }, locale),
            [unit(1, "hour"), unit(2, "minute"), unit(3, "second")].join(" ")
        );
        assert.equal(formatTimerDuration({ days: 4, hours: 4, minutes: 2 }, locale), unit(100, "hour"));
    }
});

test("sub-minute metadata uses localized now without future zero or seconds", () => {
    for (const locale of SUPPORTED_LOCALES) {
        const justNow = new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(0, "second");
        for (const milliseconds of [-59999, -1, 0, 1, 59999]) {
            assert.equal(formatDateDistance(new Date(now + milliseconds), locale, now), justNow);
        }
        for (const minutes of [-1, 1]) {
            assert.equal(
                formatDateDistance(new Date(now + minutes * 60000), locale, now),
                new Intl.RelativeTimeFormat(locale, { numeric: "always" }).format(minutes, "minute")
            );
        }
    }
});
