export type TBoardGraphView = "columns" | "network";

/** Browser-local presentation preferences must not be shared between signed-in accounts. */
export function boardGraphViewForUser(preferences: unknown, userUID: string): TBoardGraphView {
    if (!preferences || typeof preferences !== "object" || !Object.hasOwn(preferences, userUID)) return "columns";
    return (preferences as Record<string, unknown>)[userUID] === "network" ? "network" : "columns";
}
