import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export interface IFlippedCard {
    uid: string;
    title: string;
}
const key = (userUID: string, projectUID: string) => `${userUID}:${projectUID}`;
interface ICardFlipStore {
    trays: Record<string, IFlippedCard[]>;
    flip: (userUID: string, projectUID: string, card: IFlippedCard) => void;
    swap: (userUID: string, projectUID: string, selectedUID: string, current?: IFlippedCard) => void;
    remove: (userUID: string, projectUID: string, cardUID: string) => void;
    retain: (userUID: string, projectUID: string, available: Set<string>) => void;
    removeCard: (cardUID: string) => void;
    removeProject: (projectUID: string) => void;
}
export const useCardFlipStore = create<ICardFlipStore>()(
    persist(
        (set) => ({
            trays: {},
            flip: (userUID, projectUID, card) =>
                set((state) => {
                    const scope = key(userUID, projectUID);
                    return { trays: { ...state.trays, [scope]: [card, ...(state.trays[scope] ?? []).filter((item) => item.uid !== card.uid)] } };
                }),
            swap: (userUID, projectUID, selectedUID, current) =>
                set((state) => {
                    const scope = key(userUID, projectUID);
                    const rest = (state.trays[scope] ?? []).filter((item) => item.uid !== selectedUID && item.uid !== current?.uid);
                    return { trays: { ...state.trays, [scope]: current ? [current, ...rest] : rest } };
                }),
            remove: (userUID, projectUID, cardUID) =>
                set((state) => {
                    const scope = key(userUID, projectUID);
                    return { trays: { ...state.trays, [scope]: (state.trays[scope] ?? []).filter((card) => card.uid !== cardUID) } };
                }),
            retain: (userUID, projectUID, available) =>
                set((state) => {
                    const scope = key(userUID, projectUID);
                    return { trays: { ...state.trays, [scope]: (state.trays[scope] ?? []).filter((card) => available.has(card.uid)) } };
                }),
            removeCard: (cardUID) =>
                set((state) => ({
                    trays: Object.fromEntries(
                        Object.entries(state.trays).map(([scope, cards]) => [scope, cards.filter((card) => card.uid !== cardUID)])
                    ),
                })),
            removeProject: (projectUID) =>
                set((state) => ({
                    trays: Object.fromEntries(Object.entries(state.trays).filter(([scope]) => !scope.endsWith(`:${projectUID}`))),
                })),
        }),
        {
            name: "langboard-card-flip-session",
            storage: createJSONStorage(() => ({
                getItem: (name) => {
                    try {
                        return sessionStorage.getItem(name);
                    } catch {
                        return null;
                    }
                },
                setItem: (name, value) => {
                    try {
                        sessionStorage.setItem(name, value);
                    } catch {
                        /* Keep in-memory state when storage is unavailable. */
                    }
                },
                removeItem: (name) => {
                    try {
                        sessionStorage.removeItem(name);
                    } catch {
                        /* Storage may be unavailable. */
                    }
                },
            })),
            partialize: (state) => ({ trays: state.trays }),
            merge: (persisted, current) => {
                const trays = (persisted as { trays?: unknown } | null)?.trays;
                if (!trays || typeof trays !== "object" || Array.isArray(trays)) return current;
                const valid = Object.entries(trays).filter(
                    ([, cards]) =>
                        Array.isArray(cards) &&
                        (cards as unknown[]).every((value) => {
                            const card = value as Partial<IFlippedCard> | null;
                            return card && typeof card.uid === "string" && typeof card.title === "string";
                        })
                );
                return { ...current, trays: Object.fromEntries(valid) };
            },
        }
    )
);
const EMPTY: IFlippedCard[] = [];
export const useFlippedCards = (userUID: string, projectUID: string) => useCardFlipStore((state) => state.trays[key(userUID, projectUID)] ?? EMPTY);
