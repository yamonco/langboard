import assert from "node:assert/strict";
import test from "node:test";
import { createInstance } from "i18next";
import { projectTypeLabel } from "./ProjectTypeCopy.ts";

test("missing and legacy project types use localized Other, never a translation key", async () => {
    const i18n = createInstance();
    await i18n.init({
        lng: "ko",
        keySeparator: false,
        resources: { ko: { translation: { "common.Other": "기타", "project.types.SI": "시스템 통합" } } },
    });
    assert.equal(projectTypeLabel(i18n.t, "SI"), "시스템 통합");
    assert.equal(projectTypeLabel(i18n.t, "Other"), "기타");
    assert.equal(projectTypeLabel(i18n.t, "Web"), "기타");
    assert.equal(projectTypeLabel(i18n.t, "Unknown"), "기타");
});
