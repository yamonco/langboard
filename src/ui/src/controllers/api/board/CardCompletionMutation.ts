interface CompletionCard {
    completed?: boolean;
}

const pending = new WeakMap<CompletionCard, Promise<{ completed: boolean }>>();

/** Share one in-flight completion write between the board and card detail. */
export function setCardCompletion(card: CompletionCard, completed: boolean, save: () => Promise<{ completed: boolean }>) {
    const existing = pending.get(card);
    if (existing) return existing;
    const previous = card.completed;
    card.completed = completed;
    const request = Promise.resolve()
        .then(save)
        .then((result) => {
            if (card.completed === completed) card.completed = result.completed;
            return result;
        })
        .catch((error) => {
            // A newer model update takes precedence over this request's rollback.
            if (card.completed === completed) card.completed = previous;
            throw error;
        })
        .finally(() => pending.delete(card));
    pending.set(card, request);
    return request;
}
