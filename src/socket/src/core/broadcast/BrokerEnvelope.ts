type TInlineBrokerEnvelope = {
    type: "inline";
    data: unknown;
    eventId: string;
    occurredAt: string;
};

type TLegacyBrokerEnvelope = {
    type: "legacy";
    cacheKey: string;
};

export type TBrokerEnvelope = TInlineBrokerEnvelope | TLegacyBrokerEnvelope;

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);

export const decodeBrokerEnvelope = (value: unknown, topic: string, schemaVersion: string): TBrokerEnvelope | null => {
    if (!isRecord(value)) {
        return null;
    }

    if (value.schema_version !== undefined) {
        if (
            value.schema_version !== schemaVersion ||
            typeof value.event_id !== "string" ||
            !value.event_id ||
            value.event !== topic ||
            typeof value.occurred_at !== "string" ||
            Number.isNaN(Date.parse(value.occurred_at)) ||
            !Object.hasOwn(value, "data")
        ) {
            return null;
        }

        return {
            type: "inline",
            data: value.data,
            eventId: value.event_id,
            occurredAt: value.occurred_at,
        };
    }

    if (typeof value.cache_key !== "string" || !value.cache_key) {
        return null;
    }

    return {
        type: "legacy",
        cacheKey: value.cache_key,
    };
};
