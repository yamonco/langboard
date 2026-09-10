import { Routing } from "@langboard/core/constants";
import { AuthUser, BotModel } from "@/core/models";
import useSocketStore from "@/core/stores/SocketStore";
import { AxiosInstance } from "axios";
import { create } from "zustand";
import { immer } from "zustand/middleware/immer";
import { APP_SHORT_NAME } from "@/constants";

type TOidcCallbackRequestStatus = "pending" | "done";

interface IAuthStore {
    state: "initial" | "pending" | "loaded";
    currentUser: AuthUser.TModel | null;
    pageLoaded: bool;
    getToken: () => string | null;
    updateToken: (token: string, api: AxiosInstance) => Promise<void>;
    removeToken: () => void;
    hasSetPreferredLang: () => bool;
    setPreferredLangHandled: () => void;
    getOidcCallbackRequestStatus: (requestKey: string) => TOidcCallbackRequestStatus | null;
    setOidcCallbackRequestStatus: (requestKey: string, status: TOidcCallbackRequestStatus) => void;
    removeOidcCallbackRequestStatus: (requestKey: string) => void;
}

let accessToken: string | null = null;
let tokenUpdateVersion = 0;
const HAS_SET_LANG_STORAGE_KEY = `has-set-lang-${APP_SHORT_NAME}`;

const useAuthStore = create(
    immer<IAuthStore>((set, get) => {
        return {
            state: "initial",
            currentUser: null,
            pageLoaded: false,
            getToken: () => accessToken,
            updateToken: async (token: string, api: AxiosInstance) => {
                const updateVersion = ++tokenUpdateVersion;
                accessToken = token;
                if (get().state === "initial") {
                    set({ state: "pending" });
                }

                const tryGetUser = async () => {
                    const MAX_ATTEMPTS = 5;
                    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
                        if (updateVersion !== tokenUpdateVersion) {
                            return undefined;
                        }
                        try {
                            const response = await api.get<{
                                user: AuthUser.Interface;
                                bots: BotModel.Interface[];
                            }>(Routing.API.AUTH.ABOUT_ME, {
                                headers: {
                                    Authorization: `Bearer ${token}`,
                                },
                                withCredentials: true,
                            });

                            if (!response) {
                                throw new Error();
                            }

                            return response.data;
                        } catch {
                            if (updateVersion !== tokenUpdateVersion || attempt === MAX_ATTEMPTS - 1) {
                                return undefined;
                            }

                            await new Promise((resolve) => setTimeout(resolve, 1000));
                        }
                    }

                    return undefined;
                };

                const data = await tryGetUser();
                if (updateVersion !== tokenUpdateVersion || accessToken !== token) {
                    return;
                }
                if (!data) {
                    set({ currentUser: null, state: "loaded" });
                    return;
                }

                const user = AuthUser.Model.fromOne(data.user);
                BotModel.Model.fromArray(data.bots, true);

                set({ currentUser: user, state: "loaded" });
            },
            removeToken: () => {
                useSocketStore.getState().close();
                tokenUpdateVersion += 1;
                accessToken = null;
                set({ currentUser: null, state: "loaded" });
            },
            hasSetPreferredLang: () => localStorage.getItem(HAS_SET_LANG_STORAGE_KEY) === "true",
            setPreferredLangHandled: () => localStorage.setItem(HAS_SET_LANG_STORAGE_KEY, "true"),
            getOidcCallbackRequestStatus: (requestKey) => {
                const status = sessionStorage.getItem(requestKey);
                return status === "pending" || status === "done" ? status : null;
            },
            setOidcCallbackRequestStatus: (requestKey, status) => {
                sessionStorage.setItem(requestKey, status);
            },
            removeOidcCallbackRequestStatus: (requestKey) => {
                sessionStorage.removeItem(requestKey);
            },
        };
    })
);

export const getAuthStore = () => useAuthStore.getState();

export default useAuthStore;
