import { PORT, SOCKET_MAX_PAYLOAD_MB } from "@/Constants";
import * as http from "http";
import { WebSocketServer } from "ws";
import Logger from "@/core/utils/Logger";
import Routes from "@/core/server/Routes";
import SocketManager from "@/core/server/SocketManager";
import Hocus from "@/core/server/Hocus";
import { ESocketStatus } from "@langboard/core/enums";

class _Server {
    #webSocketServer!: WebSocketServer;
    #httpServer!: http.Server;
    #socketManager!: SocketManager;
    #callbackMap: { before: () => Promise<void>; after?: () => void | Promise<void> } = {
        before: async () => {},
    };

    constructor() {
        this.#createServers();
    }

    public run(beforeRun?: () => Promise<void>, afterRun?: () => void | Promise<void>) {
        if (beforeRun) {
            this.#callbackMap.before = beforeRun;
        }
        this.#callbackMap.after = afterRun;

        this.#callbackMap.before().then(() => {
            this.#httpServer.listen(PORT, () => {
                Logger.cyan(`WebSocket server is running on ws://127.0.0.1:${PORT}\n`);
                this.#callbackMap.after?.();
            });
        });
    }

    public async destroy(): Promise<void> {
        if (this.#socketManager) {
            await this.#socketManager.destroy();
            this.#socketManager = null!;
        }
        if (this.#webSocketServer) {
            const server = this.#webSocketServer;
            Hocus.closeConnections();
            server.clients.forEach((client) => client.close(ESocketStatus.WS_1012_SERVICE_RESTART));
            await new Promise<void>((resolve) => {
                const closeTimeout = setTimeout(() => {
                    server.clients.forEach((client) => client.terminate());
                }, 5000);
                closeTimeout.unref();
                server.close(() => {
                    clearTimeout(closeTimeout);
                    resolve();
                });
            });
            this.#webSocketServer = null!;
        }
        if (this.#httpServer) {
            const server = this.#httpServer;
            await new Promise<void>((resolve) => server.close(() => resolve()));
            this.#httpServer = null!;
        }
    }

    #createServers() {
        this.#httpServer = http.createServer(async (req, res) => {
            await Routes.route(req, res);
        });
        this.#webSocketServer = new WebSocketServer({
            server: this.#httpServer,
            maxPayload: SOCKET_MAX_PAYLOAD_MB * 1024 * 1024,
        });
        this.#socketManager = new SocketManager(this.#webSocketServer);
    }
}

const Server = new _Server();

export default Server;
