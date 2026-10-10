import { getUserSettingsStore, useUserSettings } from "@/core/stores/UserSettingsStore";
import { closeOpenCard, closeProjectCards, focusOpenCard, getOpenCards, retainProjectCards, toggleOpenCardPin } from "./OpenCardsData";
import type { IOpenCard } from "./OpenCardsData";

export const useOpenCards = (userUID: string | undefined): IOpenCard[] => getOpenCards(useUserSettings("open_cards"), userUID);

const changeOpenCards = (userUID: string, change: (cards: IOpenCard[]) => IOpenCard[]): void => {
    const store = getUserSettingsStore();
    const byUser = store.settings.open_cards ?? {};
    store.updateSettingsByKey("open_cards", { ...byUser, [userUID]: change(getOpenCards(byUser, userUID)) });
};

export const focusCard = (userUID: string, card: Omit<IOpenCard, "pinned" | "lastFocusedAt">): void =>
    changeOpenCards(userUID, (cards) => focusOpenCard(cards, card, new Date().toISOString()));

export const closeCard = (userUID: string, projectUID: string, cardUID: string): void =>
    changeOpenCards(userUID, (cards) => closeOpenCard(cards, projectUID, cardUID));

export const closeProject = (userUID: string, projectUID: string): void => changeOpenCards(userUID, (cards) => closeProjectCards(cards, projectUID));

export const retainProjects = (userUID: string, projectUIDs: Set<string>): void =>
    changeOpenCards(userUID, (cards) => retainProjectCards(cards, projectUIDs));

export const toggleCardPin = (userUID: string, projectUID: string, cardUID: string): void =>
    changeOpenCards(userUID, (cards) => toggleOpenCardPin(cards, projectUID, cardUID));

export const removeUnavailableCards = (userUID: string, checked: Set<string>, available: Set<string>): void =>
    changeOpenCards(userUID, (cards) =>
        cards.filter((card) => {
            const key = `${card.projectUID}:${card.cardUID}`;
            return !checked.has(key) || available.has(key);
        })
    );
