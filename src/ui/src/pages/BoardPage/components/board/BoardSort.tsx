import Button from "@/components/base/Button";
import DropdownMenu from "@/components/base/DropdownMenu";
import IconComponent from "@/components/base/IconComponent";
import { useBoard } from "@/core/providers/BoardProvider";
import { getUserSettingsStore, useUserSettings } from "@/core/stores/UserSettingsStore";
import { useTranslation } from "react-i18next";
import { COLUMN_CARD_SORT_MODES, type TColumnCardSort } from "./columnCardSort";

/** Apply the existing personal column preferences together; never write card order. */
export default function BoardSort() {
    const { project, columns, currentUser } = useBoard();
    const [t] = useTranslation();
    const saved = useUserSettings("column_card_sorts");
    const activeColumns = columns.filter((column) => !column.is_archive);
    const key = (uid: string) => `${currentUser.uid}:${project.uid}:${uid}`;
    const modes = activeColumns.map((column) => {
        const value = saved?.[key(column.uid)];
        return COLUMN_CARD_SORT_MODES.includes(value as TColumnCardSort) ? value : "manual";
    });
    const mode = modes.every((value) => value === modes[0]) ? modes[0] : undefined;
    const change = (next: string) => {
        if (!COLUMN_CARD_SORT_MODES.includes(next as TColumnCardSort)) return;
        const store = getUserSettingsStore();
        const preferences = { ...store.settings.column_card_sorts };
        activeColumns.forEach((column) => {
            preferences[key(column.uid)] = next;
        });
        store.updateSettingsByKey("column_card_sorts", preferences);
    };
    return (
        <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
                <Button type="button" variant="ghost" className="h-8 gap-1.5 px-2" aria-label={t("board.Sort cards")}>
                    <IconComponent icon="arrow-down-wide-narrow" className="size-4" />
                    <span>
                        {t("board.Sort cards")}
                        {mode ? `: ${t(`board.cardSort.${mode}`)}` : ""}
                    </span>
                </Button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Content align="end" className="max-w-[calc(100vw-2rem)]">
                <DropdownMenu.RadioGroup value={mode ?? ""} onValueChange={change}>
                    {COLUMN_CARD_SORT_MODES.map((value) => (
                        <DropdownMenu.RadioItem key={value} value={value}>
                            {t(`board.cardSort.${value}`)}
                        </DropdownMenu.RadioItem>
                    ))}
                </DropdownMenu.RadioGroup>
                <DropdownMenu.Separator />
                <p className="max-w-56 px-2 py-1 text-xs text-muted-foreground">
                    {t("board.Manual order is preserved; switch to Manual to drag cards")}
                </p>
            </DropdownMenu.Content>
        </DropdownMenu.Root>
    );
}
