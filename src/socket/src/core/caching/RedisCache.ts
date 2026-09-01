import { CACHE_URL } from "@/Constants";
import BaseCache from "@/core/caching/BaseCache";
import Logger from "@/core/utils/Logger";
import { Utils } from "@langboard/core/utils";
import { createClient } from "redis";

type TRedisClient = ReturnType<typeof createClient>;

class RedisCache extends BaseCache {
    #redisClient?: TRedisClient;
    #connectPromise?: Promise<TRedisClient>;

    public async get<T>(key: string): Promise<T | null> {
        const redisClient = await this.#getClient();

        const cachedData = await redisClient.get(key);
        let data;
        if (cachedData) {
            const cachedModel = Utils.Json.Parse(cachedData);
            if (cachedModel) {
                data = cachedModel;
            }
        }

        return data ?? null;
    }

    public async has(key: string): Promise<bool> {
        const redisClient = await this.#getClient();

        const exists = await redisClient.exists(key);
        return exists > 0;
    }

    public async set<T>(key: string, value: T, ttl?: number): Promise<void> {
        const redisClient = await this.#getClient();

        if (ttl && ttl > 0) {
            await redisClient.setEx(key, ttl, JSON.stringify(value));
            return;
        }

        await redisClient.set(key, JSON.stringify(value));
    }

    public async delete(key: string): Promise<void> {
        const redisClient = await this.#getClient();

        await redisClient.del(key);
    }

    public async clear(): Promise<void> {
        const redisClient = await this.#getClient();

        await redisClient.flushAll();
    }

    public async stop(): Promise<void> {
        const redisClient = this.#redisClient;
        this.#redisClient = undefined;
        this.#connectPromise = undefined;

        if (redisClient?.isOpen) {
            await redisClient.quit();
        } else {
            redisClient?.destroy();
        }
    }

    async #getClient(): Promise<TRedisClient> {
        if (this.#redisClient?.isOpen) {
            return this.#redisClient;
        }
        if (this.#connectPromise) {
            return this.#connectPromise;
        }

        const redisClient = createClient({
            url: CACHE_URL,
            pingInterval: 10000,
        }).on("error", (err) => Logger.red("Redis Client Error", err, "\n"));
        this.#redisClient = redisClient;
        this.#connectPromise = redisClient
            .connect()
            .then(() => redisClient)
            .catch((error) => {
                redisClient.destroy();
                if (this.#redisClient === redisClient) {
                    this.#redisClient = undefined;
                }
                throw error;
            })
            .finally(() => {
                this.#connectPromise = undefined;
            });

        return this.#connectPromise;
    }
}

export default RedisCache;
