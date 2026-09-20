export interface IReactionActor {
    uid: string;
    name: string;
}

export const resolveReactionActorNames = (reactionUIDs: string[], actors: IReactionActor[], unknownActorName: string): string[] => {
    const namesByUID = new Map(actors.map(({ uid, name }) => [uid, name]));

    return reactionUIDs.map((uid) => namesByUID.get(uid) || unknownActorName);
};

export const summarizeReactionActorNames = (names: string[], maxVisible = 8) => ({
    visibleNames: names.slice(0, maxVisible),
    remainingCount: Math.max(names.length - maxVisible, 0),
});
