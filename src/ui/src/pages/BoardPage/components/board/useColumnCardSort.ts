import { useAuth } from "@/core/providers/AuthProvider";
import { getUserSettingsStore, useUserSettings } from "@/core/stores/UserSettingsStore";
import { COLUMN_CARD_SORT_MODES, type TColumnCardSort } from "./columnCardSort";
export default function useColumnCardSort(projectUID: string, columnUID: string) {
    const { currentUser } = useAuth();
    const saved = useUserSettings("column_card_sorts");
    const key = `${currentUser?.uid}:${projectUID}:${columnUID}`;
    const value = saved?.[key];
    const mode = COLUMN_CARD_SORT_MODES.includes(value as TColumnCardSort) ? (value as TColumnCardSort) : "manual";
    const setMode = (next: TColumnCardSort) => {
        if (!currentUser) return;
        const store = getUserSettingsStore();
        store.updateSettingsByKey("column_card_sorts", { ...store.settings.column_card_sorts, [key]: next });
    };
    return { mode, setMode };
}
