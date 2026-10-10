import type { TFunction } from "i18next";

export const projectTypeLabel = (t: TFunction, projectType: string): string =>
    t(projectType === "Other" ? "common.Other" : `project.types.${projectType}`, { defaultValue: t("common.Other") });
