import { AxiosError } from "axios";
import { api } from "./Api";
import { getAuthStore } from "@/core/stores/AuthStore";
const output = document.querySelector<HTMLPreElement>("#result")!;
document.querySelector<HTMLButtonElement>("#run")!.onclick = async () => {
    let reads = 0;
    let refreshes = 0;
    const before = getAuthStore().getSessionVersion();
    api.defaults.adapter = async (config) => {
        if (config.url?.endsWith("/auth/refresh")) refreshes += 1;
        else reads += 1;
        const status = refreshes > 5 ? 401 : 422;
        throw new AxiosError("Synthetic expired session", "ERR_BAD_REQUEST", config, undefined, {
            status,
            statusText: "Expired",
            data: {},
            headers: {},
            config,
        });
    };
    let rejected = false;
    let status = 0;
    try {
        await api.get("/__expired-read", { env: { interceptToast: false } } as never);
    } catch (error) {
        rejected = true;
        if (error instanceof AxiosError) status = error.response?.status ?? 0;
    }
    output.textContent = JSON.stringify(
        {
            reads,
            refreshes,
            rejected,
            status,
            signedOut: getAuthStore().getToken() === null,
            sessionChanges: getAuthStore().getSessionVersion() - before,
        },
        null,
        2
    );
};
