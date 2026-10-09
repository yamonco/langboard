import "@/core/injection/StringExtensions";
import { ProjectCard } from "@/core/models";
import { getSocketMap } from "@/core/stores/socket/state";
import { ESocketTopic } from "@langboard/core/enums";
import deleted from "@/controllers/socket/dashboard/card/useDashboardCardDeletedHandlers";
import { useCardFlipStore } from "@/pages/BoardPage/components/card/CardFlipStore";
deleted({ project: { uid: "u866" } as never }).on();
const store = useCardFlipStore.getState();
store.flip("user", "u866", { uid: "not-loaded", title: "Not loaded" });
store.flip("user", "other", { uid: "keep", title: "Keep" });
if (ProjectCard.Model.getModel("not-loaded")) throw Error("Fixture must have no loaded card model");
const callbacks = getSocketMap().subscriptions[ESocketTopic.Dashboard]?.u866?.["dashboard:card:deleted:u866"];
if (!callbacks) throw Error("Native delete handler not registered");
for (const list of Object.values(callbacks)) for (const callback of list) callback({ uid: "not-loaded", project_column_uid: "unknown" });
if (useCardFlipStore.getState().trays["user:u866"].length) throw Error("Deleted unloaded card remains in Flip tray");
if (useCardFlipStore.getState().trays["user:other"].length !== 1) throw Error("Unrelated tray changed");
document.querySelector("#result")!.textContent =
    "PASS unloaded card removed by native registered Dashboard deletion handler; unrelated tray preserved";
