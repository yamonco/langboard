import assert from "node:assert/strict";
import { test } from "node:test";
import { formatDateDistance, formatDateTime } from "./LocaleFormat.ts";
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
