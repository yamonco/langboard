import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export interface ICardFlipDraft {
    title?: string;
    description?: { content: string };
    deadline_at?: string;
}
export const flipDraftKey = (userUID: string, projectUID: string, cardUID: string) => `${userUID}:${projectUID}:${cardUID}`;
export const useCardFlipDraftStore = create<{
    drafts: Record<string, ICardFlipDraft>;
    save: (key: string, draft: ICardFlipDraft) => void;
    clear: (key: string) => void;
}>()(
    persist(
        (set) => ({
            drafts: {},
            save: (key, draft) => set((state) => ({ drafts: { ...state.drafts, [key]: draft } })),
            clear: (key) => set((state) => ({ drafts: Object.fromEntries(Object.entries(state.drafts).filter(([entry]) => entry !== key)) })),
        }),
        {
            name: "langboard-card-flip-drafts",
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
                        /* Retain in memory. */
                    }
                },
                removeItem: (name) => {
                    try {
                        sessionStorage.removeItem(name);
                    } catch {
                        /* Storage may be disabled. */
                    }
                },
            })),
            merge: (persisted, current) => {
                const drafts = (persisted as { drafts?: unknown } | null)?.drafts;
                if (!drafts || typeof drafts !== "object" || Array.isArray(drafts)) return current;
                const valid = Object.entries(drafts).filter(([, value]) => {
                    if (!value || typeof value !== "object" || Array.isArray(value)) return false;
                    const draft = value as ICardFlipDraft;
                    return (
                        (draft.title === undefined || typeof draft.title === "string") &&
                        (draft.description === undefined || typeof draft.description?.content === "string") &&
                        (draft.deadline_at === undefined ||
                            draft.deadline_at === "" ||
                            (typeof draft.deadline_at === "string" && Number.isFinite(Date.parse(draft.deadline_at))))
                    );
                });
                return { ...current, drafts: Object.fromEntries(valid) };
            },
        }
    )
);
