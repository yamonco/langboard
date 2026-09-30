import { useCallback, useEffect, useState } from "react";
import { create } from "zustand";
import { immer } from "zustand/middleware/immer";
import type { TOpenCardsByUser } from "@/pages/DashboardPage/components/OpenCardsData";

export const NOTIFICATIONS_TIME_RANGE_OPTIONS = ["3d", "7d", "1m", "all"] as const;
export interface IUserSettings {
    notifications_time_range?: (typeof NOTIFICATIONS_TIME_RANGE_OPTIONS)[number];
    graph_view_modes?: Record<string, "columns" | "network">;
    open_cards?: TOpenCardsByUser;
    explorer_open_cards_collapsed?: Record<string, boolean>;
    wiki_hint_dismissed?: Record<string, boolean>;
    workbench_context_open?: Record<string, boolean>;
}

interface IUserSettingsStore {
    settings: IUserSettings;
    updateSettingsByKey: <TKey extends keyof IUserSettings>(key: TKey, value: IUserSettings[TKey]) => void;
    updateSettings: (settings: Partial<IUserSettings>) => void;
    replaceSettings: (settings: Partial<IUserSettings>) => void;
    deleteSettingsByKey: (key: keyof IUserSettings) => void;
}

const USER_SETTINGS_STORE_STORAGE_KEY = "user-settings-store";

const useUserSettingsStore = create(
    immer<IUserSettingsStore>((set, get) => {
        const updateStorage = () => {
            setTimeout(() => {
                localStorage.setItem(USER_SETTINGS_STORE_STORAGE_KEY, JSON.stringify(get().settings));
            }, 0);
        };

        return {
            settings: JSON.parse(localStorage.getItem(USER_SETTINGS_STORE_STORAGE_KEY) || "{}"),
            updateSettingsByKey: (key, value) => {
                set((state) => {
                    state.settings[key] = value;
                });
                updateStorage();
            },
            updateSettings: (settings) => {
                set((state) => {
                    state.settings = {
                        ...state.settings,
                        ...settings,
                    };
                });
                updateStorage();
            },
            replaceSettings: (settings) => {
                set((state) => {
                    state.settings = settings as IUserSettings;
                });
                updateStorage();
            },
            deleteSettingsByKey: (key) => {
                set((state) => {
                    delete state.settings[key];
                });
                updateStorage();
            },
        };
    })
);

export const getUserSettingsStore = () => useUserSettingsStore.getState();

export const useUserSettings = <TKey extends keyof IUserSettings>(key: TKey): IUserSettings[TKey] => {
    const [settings, setSettings] = useState(getUserSettingsStore().settings[key]);

    useEffect(() => {
        const off = useUserSettingsStore.subscribe((state) => {
            const newSettings = state.settings[key];
            if (newSettings !== settings) {
                setSettings(newSettings);
            }
        });

        return off;
    }, [settings, setSettings, key]);

    return settings;
};

export const useWorkbenchContextOpen = (userUID?: string) => {
    const saved = useUserSettings("workbench_context_open");
    const open = userUID ? (saved?.[userUID] ?? true) : true;
    const setOpen = useCallback(
        (value: boolean | ((previous: boolean) => boolean)) => {
            if (!userUID) return;
            const store = getUserSettingsStore();
            const current = store.settings.workbench_context_open ?? {};
            const previous = current[userUID] ?? true;
            store.updateSettingsByKey("workbench_context_open", {
                ...current,
                [userUID]: typeof value === "function" ? value(previous) : value,
            });
        },
        [userUID]
    );
    return [open, setOpen] as const;
};

export default useUserSettingsStore;
