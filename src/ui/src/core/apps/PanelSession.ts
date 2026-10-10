import { PanelStateCache } from "@langboard/app-panel";
import useAuthStore from "@/core/stores/AuthStore";

export const panelStateCache = new PanelStateCache();
export const activePanelDisposals = new Map<string, () => void>();
export function deletePanelState(key: string) {
    activePanelDisposals.get(key)?.();
    panelStateCache.delete(key);
}
export function invalidatePanelSessions() {
    for (const dispose of activePanelDisposals.values()) dispose();
    activePanelDisposals.clear();
    panelStateCache.clear();
}
// Subscribe outside panel mounts so logout also clears closed-panel drafts.
useAuthStore.subscribe((state, previous) => {
    if (state.currentUser?.uid !== previous.currentUser?.uid) invalidatePanelSessions();
});
