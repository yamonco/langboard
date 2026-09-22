import Consumer from "@/core/broadcast/Consumer";
import Cache from "@/core/caching/Cache";
import DB from "@/core/db/DB";
import Server from "@/core/server/Server";
import Logger from "@/core/utils/Logger";

const EXIT_SIGNALS: NodeJS.Signals[] = ["SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK"];

let isShuttingDown = false;

const runShutdownStep = async (name: string, stop: () => Promise<void>, timeoutMs?: number): Promise<boolean> => {
    let timeout: NodeJS.Timeout | undefined;
    try {
        const operation = stop();
        if (!timeoutMs) {
            await operation;
            return true;
        }

        await Promise.race([
            operation,
            new Promise<void>((_, reject) => {
                timeout = setTimeout(() => reject(new Error(`${name} shutdown timed out`)), timeoutMs);
                timeout.unref();
            }),
        ]);
        return true;
    } catch (error) {
        Logger.red(`Shutdown step failed: ${error}\n`);
        return false;
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

    const results = [
        await runShutdownStep("server", () => Server.destroy()),
        await runShutdownStep("consumer", () => Consumer.stop(), 10000),
        await runShutdownStep("cache", () => Cache.stop(), 10000),
        await runShutdownStep("database", () => (DB.isInitialized ? DB.destroy() : Promise.resolve()), 10000),
    ];
    process.exit(results.every(Boolean) ? exitCode : 1);
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
