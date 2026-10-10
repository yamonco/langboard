import type { Connection } from "@hocuspocus/server";

/** Authorize each pending burst without caching access across deliveries. */
export default function guardEditorConnection(connection: Connection, validate: () => Promise<void>): void {
    const send = connection.send.bind(connection);
    const close = connection.close.bind(connection);
    const pending: unknown[] = [];
    let flushing = false;
    let closed = false;
    let closing = false;
    connection.close = (event) => {
        if (closed) return;
        closed = true;
        pending.length = 0;
        closing = true;
        try {
            close(event);
        } finally {
            closing = false;
        }
    };
    const flush = async () => {
        while (!closed && pending.length) {
            try {
                await validate();
            } catch {
                connection.close({ code: 4403, reason: "permission-denied" });
                break;
            }
            if (closed) break;
            // Send this authorized burst synchronously; later messages require another read.
            const messages = pending.splice(0);
            for (const message of messages) {
                if (closed) break;
                send(message);
            }
        }
        flushing = false;
    };
    connection.send = (message) => {
        if (closing) {
            send(message);
            return;
        }
        if (closed) return;
        if (pending.length >= 128) {
            connection.close({ code: 4403, reason: "authorization-backpressure" });
            return;
        }
        pending.push(message);
        if (!flushing) {
            flushing = true;
            void flush();
        }
    };
}
