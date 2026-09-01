import { DATA_DIR } from "@/Constants";
import BaseConsumer from "@/core/broadcast/BaseConsumer";
import { Utils } from "@langboard/core/utils";
import * as fs from "fs";
import * as path from "path";

class InMemoryConsumer extends BaseConsumer {
    public static get BROADCAST_DIR() {
        const dir = path.join(DATA_DIR, "broadcast");
        fs.mkdirSync(dir, { recursive: true });
        return dir;
    }
    #watcher!: fs.FSWatcher;

    public async start() {
        this.#runExistingFiles();

        this.#watcher = fs.watch(InMemoryConsumer.BROADCAST_DIR, {}, async (event, filename) => {
            if (event !== "rename" || !filename) {
                return;
            }

            filename = path.join(InMemoryConsumer.BROADCAST_DIR, filename);
            if (!fs.existsSync(filename) || !fs.statSync(filename).isFile()) {
                return;
            }

            const fileContent = fs.readFileSync(filename, "utf-8");

            try {
                const model: { event: string; data: unknown } = Utils.Json.Parse(fileContent);
                if (!model || !model.event) {
                    return;
                }

                await this.emit(model.event, model.data);
            } catch {
                // Ignore invalid JSON files
            }

            this.#tryDeleteFile(filename);
        });
    }

    public async stop() {
        this.#watcher?.close();
        this.#watcher = undefined!;
    }

    #runExistingFiles() {
        if (!fs.existsSync(InMemoryConsumer.BROADCAST_DIR)) {
            return;
        }

        const files = fs.readdirSync(InMemoryConsumer.BROADCAST_DIR);
        for (let i = 0; i < files.length; ++i) {
            const file = files[i];
            const filePath = path.join(InMemoryConsumer.BROADCAST_DIR, file);
            if (!fs.statSync(filePath).isFile()) {
                continue;
            }

            const fileContent = fs.readFileSync(filePath, "utf-8");
            try {
                const model: { event: string; data: unknown } = Utils.Json.Parse(fileContent);
                if (model && model.event) {
                    this.emit(model.event, model.data);
                }
            } catch {
                // Ignore invalid JSON files
            } finally {
                this.#tryDeleteFile(filePath);
            }
        }
    }

    async #tryDeleteFile(filePath: string) {
        for (let attempt = 0; attempt < 5; ++attempt) {
            try {
                fs.unlinkSync(filePath);
                return;
            } catch {
                if (!fs.existsSync(filePath)) {
                    return;
                }
            }

            await new Promise<void>((resolve) => {
                setTimeout(resolve, 1000);
            });
        }
    }
}

export default InMemoryConsumer;
