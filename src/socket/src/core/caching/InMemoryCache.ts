import { CACHE_DIR } from "@/Constants";
import BaseCache from "@/core/caching/BaseCache";
import { Utils } from "@langboard/core/utils";
import path from "path";
import sqlite3 from "sqlite3";

class InMemoryCache extends BaseCache {
    #db: sqlite3.Database;

    constructor() {
        super();
        this.#db = new sqlite3.Database(path.join(CACHE_DIR, "cache.db"));
        this.#db.serialize();
        this.#db.run(`CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            expiry INTEGER NOT NULL
        )`);
    }

    public async get<T>(key: string): Promise<T | null> {
        this.#expire();

        const result = await new Promise<{ value: string } | undefined>((resolve, reject) => {
            this.#db.get<{ value: string }>("SELECT value FROM cache WHERE key = ?", [key], (err, row) => {
                if (err) {
                    reject(err);
                } else {
                    resolve(row);
                }
            });
        });

        if (!result) {
            return null;
        }

        let data;
        try {
            data = Utils.Json.Parse(result.value);
        } catch {
            return null;
        }

        return data;
    }

    public async has(key: string): Promise<bool> {
        this.#expire();

        const result = await new Promise<{ key: string } | undefined>((resolve, reject) => {
            this.#db.get<{ key: string }>("SELECT key FROM cache WHERE key = ?", [key], (err, row) => {
                if (err) {
                    reject(err);
                } else {
                    resolve(row);
                }
            });
        });

        return !!result;
    }

    public async set<T>(key: string, value: T, ttl?: number): Promise<void> {
        this.#expire();

        const expiry = Date.now() + (ttl ? ttl * 1000 : 0);
        await new Promise<void>((resolve, reject) => {
            this.#db.run("REPLACE INTO cache (key, value, expiry) VALUES (?, ?, ?)", [key, Utils.Json.Stringify(value), expiry], (err) => {
                if (err) {
                    reject(err);
                } else {
                    resolve();
                }
            });
        });
    }

    public async delete(key: string): Promise<void> {
        this.#expire();

        await new Promise<void>((resolve, reject) => {
            this.#db.run("DELETE FROM cache WHERE key = ?", [key], (err) => {
                if (err) {
                    reject(err);
                } else {
                    resolve();
                }
            });
        });
    }

    public async clear(): Promise<void> {
        this.#db.run("DELETE FROM cache");
    }

    public async stop(): Promise<void> {
        this.#db.close();
    }

    #expire() {
        const now = Date.now();
        this.#db.run("DELETE FROM cache WHERE expiry <= ?", [now]);
    }
}

export default InMemoryCache;
