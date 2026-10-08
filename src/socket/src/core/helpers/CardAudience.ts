import { API_INTERNAL_URL } from "@/Constants";
import { api } from "@/core/helpers/Api";
import { createOneTimeToken } from "@/core/ai/BotOneTimeToken";
import SnowflakeID from "@/core/db/SnowflakeID";
import ISocketClient from "@/core/server/ISocketClient";

export const resolveCardAudience = async (
    clients: ISocketClient[],
    cardUIDs: string[],
    operation: "read" | "remove" = "read"
): Promise<Set<string>> => {
    const allowed = new Set<string>();
    const references = Array.from(new Set(cardUIDs));
    if (!references.length || references.length > 2) return allowed;
    for (let offset = 0; offset < clients.length; offset += 100) {
        const batch = clients.slice(offset, offset + 100);
        try {
            const response = await api.post(
                `${API_INTERNAL_URL}/socket/card-dispatch-context`,
                {
                    card_uids: references,
                    recipient_uids: batch.map((client) => client.user.uid),
                    operation,
                },
                {
                    timeout: 5000,
                    headers: { "X-Api-Token": createOneTimeToken(new SnowflakeID(batch[0].user.id), undefined, "socket_dispatch") },
                }
            );
            const recipients: unknown = response.data?.allowed_recipient_uids;
            if (Array.isArray(recipients)) {
                for (const uid of recipients) if (typeof uid === "string") allowed.add(uid);
            }
        } catch {
            return new Set();
        }
    }
    return allowed;
};
