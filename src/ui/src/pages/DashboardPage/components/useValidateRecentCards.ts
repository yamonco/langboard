import { useEffect } from "react";
import { isAxiosError } from "axios";
import { api } from "@/core/helpers/Api";
import { removeUnavailableCards } from "./OpenCardsStore";
import type { IOpenCard } from "./OpenCardsData";

export default function useValidateRecentCards(userUID: string, cards: IOpenCard[]): void {
    const identities = JSON.stringify(cards.map((card) => [card.projectUID, card.cardUID]).sort());
    useEffect(() => {
        const controller = new AbortController();
        let running = false;
        const validate = async () => {
            if (running || controller.signal.aborted) return;
            running = true;
            try {
                const groups = new Map<string, string[]>();
                for (const [projectUID, cardUID] of JSON.parse(identities) as [string, string][]) {
                    groups.set(projectUID, [...(groups.get(projectUID) ?? []), cardUID]);
                }
                // Serial bounded requests avoid a burst of full card-detail loads.
                for (const [projectUID, uids] of groups) {
                    for (let offset = 0; offset < uids.length; offset += 200) {
                        const batch = uids.slice(offset, offset + 200);
                        let available: string[];
                        try {
                            const response = await api.post<{ card_uids: string[] }>(
                                `/board/${encodeURIComponent(projectUID)}/cards/available`,
                                { card_uids: batch },
                                { signal: controller.signal, env: { interceptToast: true } as never }
                            );
                            if (!Array.isArray(response.data.card_uids) || !response.data.card_uids.every((uid) => typeof uid === "string")) continue;
                            available = response.data.card_uids;
                        } catch (error) {
                            if (controller.signal.aborted) return;
                            if (!isAxiosError(error) || error.response?.status !== 403) continue;
                            available = [];
                        }
                        if (controller.signal.aborted) return;
                        const key = (uid: string) => `${projectUID}:${uid}`;
                        const visible = new Set(available);
                        if (batch.some((uid) => !visible.has(uid))) {
                            removeUnavailableCards(userUID, new Set(batch.map(key)), new Set(available.map(key)));
                        }
                    }
                }
            } finally {
                running = false;
            }
        };
        void validate();
        window.addEventListener("focus", validate);
        return () => {
            controller.abort();
            window.removeEventListener("focus", validate);
        };
    }, [userUID, identities]);
}
