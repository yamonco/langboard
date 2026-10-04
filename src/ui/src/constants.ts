export const IS_PRODUCTION = process.env.IS_PRODUCTION === "true";

export const APP_NAME = process.env.PROJECT_NAME || "App";
export const APP_SHORT_NAME = process.env.PROJECT_SHORT_NAME || APP_NAME;

export const SOCKET_URL = process.env.SOCKET_URL || "http://localhost:5690";
export const API_URL = process.env.API_URL || "http://localhost:5381";
export const PUBLIC_UI_URL = process.env.PUBLIC_UI_URL || "http://localhost:5173";
export const IS_OLLAMA_RUNNING = process.env.IS_OLLAMA_RUNNING === "true" || false;

export const APP_ACCESS_TOKEN = `access_token_${APP_SHORT_NAME}`;
export const APP_REFRESH_TOKEN = `refresh_token_${APP_SHORT_NAME}`;

export const LANGUAGE_LOCALES = ["en-US"];

export const EMAIL_REGEX = /^\S+@\S+\.\S+$/;

export const DISABLE_DRAGGING_ATTR = "data-drag-disabled";

export const MAX_FILE_SIZE_MB = parseInt(process.env.MAX_FILE_SIZE_MB || "50");

export const QUERY_NAMES = {
    REDIRECT: "continue",
    SUB_EMAIL_VERIFY_TOKEN: "bEvt",
    RECOVERY_TOKEN: "rtK",
    SIGN_UP_ACTIVATE_TOKEN: "sAVk",
    PROJCT_INVITATION_TOKEN: "PikQ",
    SIGN_IN_TOKEN: "itkl",
    EMAIL_TOKEN: "TKE",
    BOARD: "bp",
    BOARD_CARD: "BpC",
    BOARD_CARD_CHUNK: "bPCC",
    BOARD_WIKI: "bPw",
    BOARD_WIKI_CHUNK: "BpWc",
} as const;

export const SIGN_IN_TOKEN_LENGTH = 64;
