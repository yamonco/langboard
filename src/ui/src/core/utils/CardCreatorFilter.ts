interface ICardCreator {
    uid: string;
    type: "user" | "bot";
}

// OR within the creator group; the board combines separate filter groups with AND.
export function matchesCardCreator(creator: ICardCreator | undefined, selected: string[] | undefined, currentUserUID: string): boolean {
    if (!selected?.length) return true;
    if (!creator) return false;
    return (
        selected.includes(`${creator.type}/${creator.uid}`) || (creator.type === "user" && selected.includes("me") && creator.uid === currentUserUID)
    );
}
