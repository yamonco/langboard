import "@/i18n";
import { createRoot } from "react-dom/client";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { AxiosError, CanceledError } from "axios";
import setupApiErrorHandler from "./setupApiErrorHandler";

function Fixture() {
    const [t] = useTranslation();
    const [message, setMessage] = useState("");
    const handle = async (kind: string) => {
        const ref = { message: "" };
        const error =
            kind === "cancel"
                ? new CanceledError("Private cancellation detail")
                : kind === "network"
                  ? new AxiosError("Private network detail", AxiosError.ERR_NETWORK)
                  : new Error("Private resource loading detail");
        await setupApiErrorHandler({}, ref).handleAsync(error);
        setMessage(ref.message);
    };
    return (
        <main>
            <button onClick={() => handle("resource")}>Resource failure</button>
            <button onClick={() => handle("network")}>Network failure</button>
            <button onClick={() => handle("cancel")}>Cancel</button>
            <output>{message}</output>
            <p data-testid="fallback">{t("errors.Internal server error")}</p>
            <p data-testid="network">{t("errors.Network error")}</p>
        </main>
    );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
