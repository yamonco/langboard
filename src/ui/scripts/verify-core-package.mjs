import { Routing, SocketEvents } from "@langboard/core/constants";

if (SocketEvents.SERVER.BOARD.CARD.CHECKLIST.PROGRESS_CHANGED !== "board:card:checklist:progress:changed:{uid}") {
    throw new Error("@langboard/core is stale. Build src/shared/ts and reinstall or relink it before building the UI.");
}

if (Routing.API.ACTIVITIY.CARD_COLUMN_HISTORY !== "/activity/project/{uid}/card/{card_uid}/column-history") {
    throw new Error("@langboard/core is stale: card history route missing. Build src/shared/ts and reinstall or relink it before building the UI.");
}
