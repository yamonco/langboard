import { metadataDisplay } from "./MetadataDisplay.ts";
import type { ProjectLabel } from "@/core/models";

export const globalLabelDisplay = (name: string, description: string, display: ProjectLabel.Interface["global_display"], language: string) => {
    const translation = metadataDisplay({ name, description }, display?.translations, language);
    return {
        name: `${display?.emoji ? `${display.emoji} ` : ""}${translation.name}`,
        description: translation.description,
    };
};
