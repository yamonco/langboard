export interface IOpenCard {
    projectUID: string;
    cardUID: string;
    title: string;
    pinned: boolean;
    lastFocusedAt: string;
}

export type TOpenCardsByUser = Record<string, IOpenCard[]>;

export const getOpenCards = (byUser: TOpenCardsByUser | undefined, userUID: string | undefined): IOpenCard[] => {
    const cards = userUID && byUser?.[userUID];
    return Array.isArray(cards)
        ? cards.filter(
              (card) =>
                  typeof card?.projectUID === "string" &&
                  typeof card?.cardUID === "string" &&
                  typeof card?.title === "string" &&
                  typeof card?.lastFocusedAt === "string"
          )
        : [];
};

const sortOpenCards = (cards: IOpenCard[]): IOpenCard[] =>
    cards.sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.lastFocusedAt.localeCompare(a.lastFocusedAt));

export const focusOpenCard = (cards: IOpenCard[], card: Omit<IOpenCard, "pinned" | "lastFocusedAt">, now: string): IOpenCard[] => {
    const previous = cards.find((item) => item.projectUID === card.projectUID && item.cardUID === card.cardUID);
    const next = sortOpenCards([...cards.filter((item) => item !== previous), { ...card, pinned: previous?.pinned ?? false, lastFocusedAt: now }]);
    let unpinned = 0;
    return next.filter((item) => item.pinned || ++unpinned <= 20);
};

export const closeOpenCard = (cards: IOpenCard[], projectUID: string, cardUID: string): IOpenCard[] =>
    cards.filter((item) => item.projectUID !== projectUID || item.cardUID !== cardUID);

export const closeProjectCards = (cards: IOpenCard[], projectUID: string): IOpenCard[] => cards.filter((item) => item.projectUID !== projectUID);

export const retainProjectCards = (cards: IOpenCard[], projectUIDs: Set<string>): IOpenCard[] =>
    cards.filter((item) => projectUIDs.has(item.projectUID));

export const toggleOpenCardPin = (cards: IOpenCard[], projectUID: string, cardUID: string): IOpenCard[] =>
    sortOpenCards(cards.map((item) => (item.projectUID === projectUID && item.cardUID === cardUID ? { ...item, pinned: !item.pinned } : item)));
