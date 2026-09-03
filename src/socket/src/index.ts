import "@/imports";
import Consumer from "@/core/broadcast/Consumer";
import DB from "@/core/db/DB";
import Server from "@/core/server/Server";

Server.run(async () => {
    if (!DB.isInitialized) {
        await DB.initialize();
    }
    await Consumer.start();
});
