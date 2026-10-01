import { useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { api } from "@/core/helpers/Api";
import { ProjectCard, MetadataModel } from "@/core/models";
import useGetCards from "./useGetCards";
import "@/i18n";

const projectUID = "enrichment-fixture";
const deny = new URLSearchParams(location.search).has("deny");
let resolveMetadata: () => void = () => {};
let rejectMetadata: () => void = () => {};
let readyMetadata = false;
let metadataReads = 0;
let reportRequest: (url: string) => void = () => {};
let reportAbort: () => void = () => {};
api.defaults.adapter = async (config) => {
    reportRequest(config.url!);
    const response = { status: 200, statusText: "OK", headers: {}, config };
    if (config.url!.startsWith("/metadata/")) {
        const version = ++metadataReads;
        config.signal?.addEventListener?.("abort", () => reportAbort());
        if (!readyMetadata)
            await new Promise<void>((resolve, reject) => {
                resolveMetadata = () => {
                    readyMetadata = true;
                    resolve();
                };
                rejectMetadata = () => reject(new AxiosError("Metadata unavailable", "ERR_NETWORK", config));
            });
        return { ...response, data: { metadata: { card: { note: `loaded-${version}` }, removed: { note: "must not return" } } } };
    }
    if (deny) throw new AxiosError("Forbidden", "ERR_BAD_REQUEST", config, undefined, { ...response, status: 403, data: {} });
    const base = { created_at: new Date(), updated_at: new Date() };
    return {
        ...response,
        data: {
            cards: [
                { ...base, uid: "card", project_uid: projectUID, project_column_uid: "column", title: "Authorized card", description: "", order: 0 },
            ],
            columns: [{ ...base, uid: "column", project_uid: projectUID, name: "Board column", order: 0 }],
            checklists: [],
            global_relationships: [],
            column_bot_scopes: [],
            column_bot_schedules: [],
        },
    };
};
function SecondObserver({ enabled }: { enabled: boolean }) {
    useGetCards({ project_uid: projectUID }, { enabled });
    return null;
}
function Fixture() {
    const [requests, setRequests] = useState<string[]>([]);
    const [secondEnabled, setSecondEnabled] = useState(false);
    const [aborted, setAborted] = useState(0);
    reportAbort = () => setAborted((value) => value + 1);
    reportRequest = (url) => setRequests((value) => [...value, url]);
    const result = useGetCards({ project_uid: projectUID });
    const cards = ProjectCard.Model.useModels((card) => card.project_uid === projectUID);
    const metadata = MetadataModel.Model.useModels(() => true);
    return (
        <>
            <SecondObserver enabled={secondEnabled} />
            <h1>{result.isError ? "Board denied" : result.data ? "Board ready" : "Board loading"}</h1>
            {cards.map((card) => (
                <p key={card.uid}>{card.title}</p>
            ))}
            <p>Metadata entries: {metadata.length}</p>
            <p>Aborted metadata: {aborted}</p>
            <p>Metadata value: {metadata[0]?.metadata.note ?? "none"}</p>
            <button onClick={() => setSecondEnabled(true)}>Enable second observer</button>
            <button onClick={() => rejectMetadata()}>Reject metadata</button>
            <button onClick={() => resolveMetadata()}>Release metadata</button>
            <button
                onClick={() => {
                    readyMetadata = true;
                    void result.refetch();
                }}
            >
                Refresh board
            </button>
            <ul>
                {requests.map((url, index) => (
                    <li key={index}>{url}</li>
                ))}
            </ul>
        </>
    );
}
createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={new QueryClient()}>
        <Fixture />
    </QueryClientProvider>
);
