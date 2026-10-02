import type { ProjectLabel } from "@/core/models";

export const globalLabelDisplay = (name: string, description: string, display: ProjectLabel.Interface["global_display"], language: string) => {
    const translation = display?.translations?.[language] ?? display?.translations?.[language.split("-")[0]];
    return {
        name: `${display?.emoji ? `${display.emoji} ` : ""}${translation?.name || name}`,
        description: translation?.description || description,
    };
};
