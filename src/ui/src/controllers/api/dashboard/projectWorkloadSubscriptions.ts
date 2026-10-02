import type { QueryClient } from "@tanstack/react-query";

interface SocketLease {
    subscribe: (uids: string[], onSubscribed?: () => void) => void;
    unsubscribe: (uids: string[]) => void;
    listen: (uid: string, callback: () => void) => () => void;
    listenOpen: (callback: () => void) => () => void;
}

// One Dashboard topic owner per QueryClient, shared by Explorer, palette and home.
const clients = new WeakMap<
    QueryClient,
    {
        projects: Map<string, { references: number; off: () => void }>;
        timer?: ReturnType<typeof setTimeout>;
        offOpen: () => void;
    }
>();

export function acquireProjectWorkload(client: QueryClient, uids: string[], socket: SocketLease): () => void {
    let state = clients.get(client);
    if (!state) {
        const projects = new Map<string, { references: number; off: () => void }>();
        state = {
            projects,
            offOpen: socket.listenOpen(() => {
                socket.subscribe([...projects.keys()]);
                void client.invalidateQueries({ queryKey: ["get-dashboard-projects"] });
            }),
        };
        clients.set(client, state);
    }
    const owned = state;
    const refresh = () => {
        if (clients.get(client) !== owned || !owned.projects.size || owned.timer) return;
        // Bounded bursts share one authorized batch read; no per-card fetch or poll.
        owned.timer = setTimeout(() => {
            owned.timer = undefined;
            void client.cancelQueries({ queryKey: ["get-dashboard-projects"] }).then(() => {
                if (clients.get(client) === owned && owned.projects.size) {
                    return client.invalidateQueries({ queryKey: ["get-dashboard-projects"] });
                }
            });
        }, 250);
    };
    const newUIDs: string[] = [];
    for (const uid of new Set(uids)) {
        const current = owned.projects.get(uid);
        if (current) current.references++;
        else {
            owned.projects.set(uid, { references: 1, off: socket.listen(uid, refresh) });
            newUIDs.push(uid);
        }
    }
    if (newUIDs.length) socket.subscribe(newUIDs, refresh);
    return () => {
        const removed: string[] = [];
        for (const uid of new Set(uids)) {
            const current = owned.projects.get(uid);
            if (!current || --current.references > 0) continue;
            current.off();
            owned.projects.delete(uid);
            removed.push(uid);
        }
        if (removed.length) socket.unsubscribe(removed);
        if (!owned.projects.size) {
            if (owned.timer) clearTimeout(owned.timer);
            owned.offOpen();
            clients.delete(client);
        }
    };
}
