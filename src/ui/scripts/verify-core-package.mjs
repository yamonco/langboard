import { SocketEvents } from "@langboard/core/constants";

if (SocketEvents.SERVER.BOARD.CARD.CHECKLIST.PROGRESS_CHANGED !== "board:card:checklist:progress:changed:{uid}") {
    throw new Error("@langboard/core is stale. Build src/shared/ts and reinstall or relink it before building the UI.");
}
