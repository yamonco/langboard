import { TEditorCollaborationType } from "@/constants/Editor";

type TStringCase = "flat" | "upper" | "camel" | "pascal" | "snake" | "upperSnake" | "kebab";

export interface IEditorCollaborationDocumentIDParams {
    collaborationType: TEditorCollaborationType;
    uid: number | string;
    section?: number | string;
}

class Case {
    #str: string;
    #case: TStringCase;
    #rawChunks: string[];

    constructor(str: string) {
        this.#str = str;
        this.#case = this.#detectCase();
        this.#rawChunks = this.#parseChunks();
    }

    get case(): TStringCase {
        return this.#case;
    }

    public toFlat(): string {
        return this.#rawChunks.join("");
    }

    public toUpper(): string {
        return this.#rawChunks.join("").toUpperCase();
    }

    public toCamel(): string {
        return this.#rawChunks
            .map((chunk, index) => {
                return index === 0 ? chunk.toLowerCase() : this.#capitalize(chunk);
            })
            .join("");
    }

    public toPascal(): string {
        return this.#rawChunks
            .map((chunk) => {
                return this.#capitalize(chunk);
            })
            .join("");
    }

    public toSnake(): string {
        return this.#rawChunks.join("_").toLowerCase();
    }

    public toUpperSnake(): string {
        return this.#rawChunks.join("_").toUpperCase();
    }

    public toKebab(): string {
        return this.#rawChunks.join("-").toLowerCase();
    }

    public toLanguageObjKey(): string {
        return this.#rawChunks
            .map((chunk, i) => {
                if (i === 0) {
                    return chunk.toLowerCase();
                } else {
                    return chunk.toUpperCase();
                }
            })
            .join("");
    }

    #detectCase(): TStringCase {
        if (this.#str.includes("_")) {
            return this.#str === this.#str.toUpperCase() ? "upperSnake" : "snake";
        } else if (this.#str.includes("-")) {
            return "kebab";
        } else if (this.#str === this.#str.toLowerCase()) {
            return "flat";
        } else if (this.#str === this.#str.toUpperCase()) {
            return "upper";
        } else if (this.#str.charAt(0) === this.#str.charAt(0).toUpperCase()) {
            return "pascal";
        } else {
            return "camel";
        }
    }

    #parseChunks(): string[] {
        if (this.#rawChunks) {
            return this.#rawChunks;
        }

        switch (this.#case) {
            case "flat":
            case "upper":
                return [this.#str];
            case "camel":
            case "pascal":
                return this.#str.split(/(?=[A-Z])/);
            case "snake":
            case "upperSnake":
                return this.#str.split("_");
            case "kebab":
                return this.#str.split("-");
        }
    }

    #capitalize(str: string): string {
        return `${str.charAt(0).toUpperCase()}${str.slice(1)}`;
    }
}

class Token {
    public static generate(n: number): string {
        const chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
        let token = "";
        for (let i = 0; i < n; ++i) {
            token += chars[Math.floor(Math.random() * chars.length)];
        }
        return token;
    }

    public static uuid(): string {
        return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
            const r = (Math.random() * 16) | 0;
            const v = c === "x" ? r : (r & 0x3) | 0x8;
            return v.toString(16);
        });
    }

    public static shortUUID(): string {
        return "xxxx-xxxx-xxxx-xxxx".replace(/x/g, () => {
            return ((Math.random() * 16) | 0).toString(16);
        });
    }

    public static reactKey(name: string): string {
        return `${name.replace(/(\.|\s)/g, "-")}-${Token.shortUUID()}`;
    }
}

const getInitials = (firstname?: string, lastname?: string): string => {
    return `${firstname?.charAt(0) ?? ""}${lastname?.charAt(0) ?? ""}`.toUpperCase();
};

type TExtractPlaceholders<TString extends string> = TString extends `${infer _TStart}{${infer TParam}}${infer TRest}`
    ? { [K in TParam]: string } & TExtractPlaceholders<TRest>
    : {};

const format = <TString extends string, TMap extends TExtractPlaceholders<TString>>(str: TString, map: TMap): string => {
    return str.replace(/{(\w+)}/g, (match, key) => {
        return (map[key as keyof TMap] || match) as string;
    });
};

const createEditorCollaborationDocumentID = ({ collaborationType, uid, section }: IEditorCollaborationDocumentIDParams): string => {
    return [collaborationType, uid, section]
        .filter((value): value is number | string => value !== undefined && value !== null && `${value}`.length > 0)
        .join(":");
};

const createEditorDocumentRouteKey = (documentID: string): string => {
    let hash = 0x811c9dc5;
    for (const byte of new TextEncoder().encode(documentID)) {
        hash = Math.imul(hash ^ byte, 0x01000193);
    }
    return (hash >>> 0).toString(16).padStart(8, "0");
};

const formatBytes = (
    bytes: number,
    opts: {
        decimals?: number;
        sizeType?: "accurate" | "normal";
    } = {}
) => {
    const { decimals = 0, sizeType = "normal" } = opts;
    const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
    const accurateSizes = ["Bytes", "KiB", "MiB", "GiB", "TiB"];

    if (bytes === 0) {
        return "0 Byte";
    }

    const i = Math.floor(Math.log(bytes) / Math.log(1024));

    return `${(bytes / Math.pow(1024, i)).toFixed(decimals)} ${sizeType === "accurate" ? (accurateSizes[i] ?? "Bytest") : (sizes[i] ?? "Bytes")}`;
};

const isValidIpv4OrRange = (str: string): bool => {
    const ipv4Pattern = /^(\d{1,3}\.){3}\d{1,3}(\/24)?$/;
    return ipv4Pattern.test(str);
};

const isJsonString = (str: string): bool => {
    if (str.length > 0 && ((str[0] === "{" && str[str.length - 1] === "}") || (str[0] === "[" && str[str.length - 1] === "]"))) {
        try {
            JSON.parse(str);
            return true;
        } catch (e) {
            return false;
        }
    }

    return false;
};

const convertSafeEnum = <T extends Record<string, string>>(EnumType: T, value: T[keyof T] | string): T[keyof T] => {
    if (value.includes(".")) {
        value = value.split(".").pop() || value;
    }
    const valueCase = new Case(value);
    let enumValue;
    if (EnumType[valueCase.toUpper()]) {
        enumValue = EnumType[valueCase.toUpper()];
    } else if (EnumType[valueCase.toPascal()]) {
        enumValue = EnumType[valueCase.toPascal()];
    } else {
        enumValue = value;
    }
    return enumValue as T[keyof T];
};

class Crontab {
    public static restoreTimezone(interval: string): string {
        const timezoneOffset = new Date().getTimezoneOffset() / -60;
        if (!timezoneOffset) {
            return interval;
        }

        const parts = interval.split(" ");
        const diffMinutes = (timezoneOffset % 1) * 60;
        const diffHours = Math.floor(timezoneOffset);

        if (diffMinutes !== 0 && parts[0] !== "*") {
            parts[0] = Crontab.#restoreTimezoneChunk(parts[0], diffMinutes, Crontab.#ensureValidMinute);
        }

        if (diffHours !== 0 && parts[1] !== "*") {
            parts[1] = Crontab.#restoreTimezoneChunk(parts[1], diffHours, Crontab.#ensureValidHour);
        }

        return parts.join(" ");
    }

    static #restoreTimezoneChunk(chunk: string, diff: number, ensure: (value: number) => number): string {
        const parts = chunk.split(",");
        const newChunks = [];

        for (let i = 0; i < parts.length; ++i) {
            const part = parts[i].trim();
            if (part.startsWith("*/")) {
                newChunks.push(part);
            } else if (part.includes("-")) {
                const [start, end] = part.split("-").map((num) => parseInt(num, 10));
                const newStart = ensure(start + diff);
                const newEnd = ensure(end + diff);
                newChunks.push(`${newStart}-${newEnd}`);
            } else {
                const newValue = ensure(parseInt(part, 10) + diff);
                newChunks.push(newValue.toString());
            }
        }

        return newChunks.join(",");
    }

    static #ensureValidMinute(minute: number): number {
        return ((minute % 60) + 60) % 60;
    }

    static #ensureValidHour(hour: number): number {
        return ((hour % 24) + 24) % 24;
    }
}

export const StringUtils = {
    Case,
    Token,
    createEditorCollaborationDocumentID,
    createEditorDocumentRouteKey,
    getInitials,
    format,
    formatBytes,
    isValidIpv4OrRange,
    isJsonString,
    convertSafeEnum,
    Crontab,
};

export type TStringUtils = typeof StringUtils;
