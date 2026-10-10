import { api } from "@/core/helpers/Api";
import { useQueryMutation } from "@/core/helpers/QueryMutation";

export interface ICardReader {
    user_uid: string;
    seen_at: string;
}
export const cardReadStateKey = (projectUID: string, cardUID: string) => ["card-read-state", projectUID, cardUID];

export default function useCardReadState(projectUID: string, cardUID: string, version = 0) {
    const { query, mutate, queryClient } = useQueryMutation();
    const path = `/board/${encodeURIComponent(projectUID)}/card/${encodeURIComponent(cardUID)}`;
    const readers = query(
        [...cardReadStateKey(projectUID, cardUID), version],
        async () => {
            const response = await api.get<{ readers: ICardReader[] }>(`${path}/read-state`);
            return response.data.readers;
        },
        { staleTime: 10000, retry: 0, refetchInterval: 30000 }
    );
    const unread = mutate(
        ["mark-card-unread", projectUID, cardUID],
        async () => {
            await api.post(`${path}/unread`);
        },
        {
            retry: 0,
            onSuccess: async () => {
                await Promise.all([
                    queryClient.invalidateQueries({ queryKey: cardReadStateKey(projectUID, cardUID) }),
                    queryClient.invalidateQueries({ queryKey: [`get-cards-${projectUID}`] }),
                ]);
            },
        }
    );
    return { readers, unread };
}
