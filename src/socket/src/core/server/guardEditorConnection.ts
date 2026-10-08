import type { Connection } from "@hocuspocus/server";

/** Preserve message order while checking the current audience before delivery. */
export default function guardEditorConnection(connection: Connection, validate: () => Promise<void>): void {
    const send = connection.send.bind(connection);
    const close = connection.close.bind(connection);
    let pending = Promise.resolve();
    let closed = false;
    let closing = false;
    let queued = 0;
    connection.close = (event) => {
        if (closed) return;
        closed = true;
        closing = true;
        try {
            close(event);
        } finally {
            closing = false;
        }
    };
    connection.send = (message) => {
        if (closing) {
            send(message);
            return;
        }
        if (closed) return;
        if (++queued > 128) {
            connection.close({ code: 4403, reason: "authorization-backpressure" });
            return;
        }
        pending = pending.then(async () => {
            if (closed) return;
            try {
                await validate();
            } catch {
                connection.close({ code: 4403, reason: "permission-denied" });
                return;
            }
            --queued;
            if (!closed) send(message);
        });
    };
}
