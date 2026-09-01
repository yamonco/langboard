import Consumer from "@/core/broadcast/Consumer";
import Cache from "@/core/caching/Cache";
import DB from "@/core/db/DB";
import Server from "@/core/server/Server";
import Logger from "@/core/utils/Logger";

const EXIT_SIGNALS: NodeJS.Signals[] = ["SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK"];

let isShuttingDown = false;

const runShutdownStep = async (name: string, stop: () => Promise<void>, timeoutMs?: number): Promise<void> => {
    let timeout: NodeJS.Timeout | undefined;
    try {
        const operation = stop();
        if (!timeoutMs) {
            await operation;
            return;
        }

        await Promise.race([
            operation,
            new Promise<void>((_, reject) => {
                timeout = setTimeout(() => reject(new Error(`${name} shutdown timed out`)), timeoutMs);
                timeout.unref();
            }),
        ]);
    } catch (error) {
        Logger.red(`Shutdown step failed: ${error}\n`);
    } finally {
        if (timeout) {
            clearTimeout(timeout);
        }
    }
};

const shutdown = async (exitCode: number): Promise<void> => {
    if (isShuttingDown) {
        return;
    }
    isShuttingDown = true;

    await runShutdownStep("server", () => Server.destroy());
    await runShutdownStep("consumer", () => Consumer.stop(), 10000);
    await runShutdownStep("cache", () => Cache.stop(), 10000);
    await runShutdownStep("database", () => DB.destroy(), 10000);
    process.exit(exitCode);
};

for (let i = 0; i < EXIT_SIGNALS.length; ++i) {
    const signal = EXIT_SIGNALS[i];
    try {
        process.on(signal, async () => {
            Logger.green("Shutting down gracefully...\n");
            await shutdown(0);
        });
    } catch {
        continue;
    }
}

const ERROR_SIGNALS = ["uncaughtException", "unhandledRejection"];

for (let i = 0; i < ERROR_SIGNALS.length; ++i) {
    const signal = ERROR_SIGNALS[i];
    process.on(signal, (error) => {
        Logger.red(`Error occurred: ${error}\n`);
        Logger.cyan("Stopping process for a clean supervisor restart...\n");
        void shutdown(1);
    });
}
