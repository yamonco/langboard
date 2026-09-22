import "@/imports";
import { SOCKET_OWNER } from "@/Constants";
import Consumer from "@/core/broadcast/Consumer";
import DB from "@/core/db/DB";
import Server from "@/core/server/Server";

Server.run(async () => {
    if (SOCKET_OWNER !== "node") {
        return;
    }

    if (!DB.isInitialized) {
        await DB.initialize();
    }
    await Consumer.start();
});
