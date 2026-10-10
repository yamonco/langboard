import axios, { AxiosRequestConfig } from "axios";
import pako from "pako";
import { API_URL } from "@/constants";
import { Routing } from "@langboard/core/constants";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { getAuthStore } from "@/core/stores/AuthStore";
import { Utils } from "@langboard/core/utils";
import { EHttpStatus } from "@langboard/core/enums";

export const api = axios.create({
    baseURL: API_URL,
    withCredentials: true,
    transformRequest: (axios.defaults.transformRequest
        ? Array.isArray(axios.defaults.transformRequest)
            ? axios.defaults.transformRequest
            : [axios.defaults.transformRequest]
        : []
    ).concat((data, headers) => {
        if (Utils.Type.isString(data) && data.length > 1024) {
            headers["Content-Encoding"] = "gzip";
            return pako.gzip(data);
        } else {
            headers["Content-Encoding"] = undefined;
            return data;
        }
    }),
});

const requestSessions = new WeakMap<AxiosRequestConfig, number>();
const isPreviousSession = (config?: AxiosRequestConfig) => {
    const version = config ? requestSessions.get(config) : undefined;
    return version !== undefined && version !== getAuthStore().getSessionVersion();
};

export const refresh = async (): Promise<bool> => {
    const authStore = getAuthStore();

    try {
        const response = await api.post(Routing.API.AUTH.REFRESH);

        if (response.status !== EHttpStatus.HTTP_200_OK) {
            authStore.removeToken();
            throw new Error("Failed to refresh token");
        }

        await authStore.updateToken(response.data.access_token, api);
        return true;
    } catch (e) {
        if (!axios.isCancel(e)) authStore.removeToken();
        return false;
    }
};

api.interceptors.request.use(
    async (config) => {
        const authStore = getAuthStore();
        const accessToken = authStore.getToken();

        if (accessToken) {
            config.headers.Authorization = `Bearer ${accessToken}`;
        }

        return config;
    },
    (error) => Promise.reject(error),
    {
        runWhen: (config) => {
            return !config.url?.endsWith(Routing.API.AUTH.REFRESH);
        },
    }
);

// Axios request interceptors run in reverse registration order. Capture before
// asynchronous token attachment, including cookie-based refresh requests.
api.interceptors.request.use((config) => {
    requestSessions.set(config, getAuthStore().getSessionVersion());
    return config;
});

api.interceptors.response.use(
    (value) => {
        if (isPreviousSession(value.config)) throw new axios.CanceledError("Session changed");
        return value;
    },
    async (error) => {
        if (axios.isCancel(error)) throw error;
        if (isPreviousSession(error.config)) throw new axios.CanceledError("Session changed");
        const interceptToast = error.config?.env?.interceptToast;
        const { handleAsync } = setupApiErrorHandler({
            code: {
                message: (e) => {
                    throw e;
                },
                toast: !interceptToast,
            },
            network: {
                message: (e) => {
                    throw e;
                },
                toast: !interceptToast,
            },
            nonApi: {
                message: (e) => {
                    throw e;
                },
                toast: !interceptToast,
            },
            wildcard: {
                message: (e) => {
                    throw e;
                },
                toast: !interceptToast,
            },
            [EHttpStatus.HTTP_401_UNAUTHORIZED]: {
                message: (e) => {
                    const authStore = getAuthStore();
                    authStore.removeToken();
                    throw e;
                },
                toast: !interceptToast,
            },
            [EHttpStatus.HTTP_422_UNPROCESSABLE_CONTENT]: {
                message: async (e) => {
                    const authStore = getAuthStore();
                    const originalConfig: AxiosRequestConfig = e.config!;
                    const isRefreshed = await refresh();
                    if (!isRefreshed) {
                        return;
                    }
                    originalConfig.headers!.Authorization = `Bearer ${authStore.getToken()}`;
                    return await api(originalConfig);
                },
            },
        });

        const result = await handleAsync(error);
        return result;
    }
);
