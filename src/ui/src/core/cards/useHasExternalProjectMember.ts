import { useSyncExternalStore } from "react";
import { Project, User } from "@/core/models";
import ModelEdgeStore from "@/core/models/ModelEdgeStore";

// Share one membership subscription set across every card on the same board.
const stores = new WeakMap<Project.TModel, ReturnType<typeof createStore>>();
function createStore(project: Project.TModel) {
    const listeners = new Set<() => void>();
    let cleanup: (() => void)[] = [];
    let memberCleanup: (() => void)[] = [];
    let value = false;
    const read = () => project.all_members.some((member) => member.isValidUser() && member.membership_classification === "external");
    const refresh = () => {
        const next = read();
        if (next === value) return;
        value = next;
        listeners.forEach((listener) => listener());
    };
    const bindMembers = () => {
        memberCleanup.forEach((off) => off());
        memberCleanup = project.all_members.flatMap((member) => [
            member.subscribeFields(["membership_classification", "type"], refresh),
            ModelEdgeStore.subscribe({
                event: "DISCONNECTED",
                key: `card-presentation-${project.uid}`,
                source: project,
                target: member,
                callback: bindMembers,
            }),
        ]);
        refresh();
    };
    return {
        getSnapshot: () => (listeners.size ? value : read()),
        subscribe(listener: () => void) {
            if (!listeners.size) {
                value = read();
                cleanup = [
                    ModelEdgeStore.subscribe({
                        event: "CONNECTED",
                        key: `card-presentation-${project.uid}`,
                        source: project,
                        targetClass: User.Model,
                        callback: bindMembers,
                    }),
                ];
                bindMembers();
            }
            listeners.add(listener);
            return () => {
                listeners.delete(listener);
                if (!listeners.size) {
                    [...cleanup, ...memberCleanup].forEach((off) => off());
                    cleanup = [];
                    memberCleanup = [];
                }
            };
        },
    };
}
export default function useHasExternalProjectMember(project: Project.TModel): boolean {
    let store = stores.get(project);
    if (!store) {
        store = createStore(project);
        stores.set(project, store);
    }
    return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}
