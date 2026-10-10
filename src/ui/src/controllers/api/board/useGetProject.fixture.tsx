import { useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { api } from "@/core/helpers/Api";
import { Project } from "@/core/models";
import useGetProject from "./useGetProject";
import useGetCards from "./useGetCards";
import "@/i18n";

const uid = "project-load-fixture";
const deny = new URLSearchParams(location.search).has("deny");
let release: () => void = () => {};
let reject: () => void = () => {};
let reportRequest: (url: string) => void = () => {};
const base = { created_at: new Date(), updated_at: new Date() };
api.defaults.adapter = async (config) => {
    reportRequest(config.url!);
    const response = { status: 200, statusText: "OK", headers: {}, config };
    if (config.url!.endsWith("/dock")) {
        await new Promise<void>((resolve, fail) => {
            release = resolve;
            reject = () => fail(new AxiosError("Dock unavailable", "ERR_NETWORK", config));
        });
        return { ...response, data: { revision: 1, column_uids: [] } };
    }
    if (config.url!.includes("/metadata/")) return { ...response, data: { metadata: {} } };
    if (config.url!.endsWith("/cards"))
        return {
            ...response,
            data: { cards: [], columns: [], checklists: [], global_relationships: [], column_bot_scopes: [], column_bot_schedules: [] },
        };
    if (deny) throw new AxiosError("Forbidden", "ERR_BAD_REQUEST", config, undefined, { ...response, status: 403, data: {} });
    return {
        ...response,
        data: { project: { ...base, uid, title: "Authorized project", dock_revision: 0 }, project_bot_scopes: [], project_bot_schedules: [] },
    };
};
function Cards() {
    const result = useGetCards({ project_uid: uid });
    return <p>{result.isSuccess ? "Cards ready" : "Cards loading"}</p>;
}
function DockRevision({ project }: { project: Project.TModel }) {
    const revision = project.useField("dock_revision");
    return <p>Dock revision: {revision}</p>;
}
function Fixture() {
    const [requests, setRequests] = useState<string[]>([]);
    reportRequest = (url) => setRequests((all) => [...all, url]);
    const result = useGetProject({ uid });
    return (
        <>
            <h1>{result.isError ? "Project denied" : result.data ? "Project ready" : "Project loading"}</h1>
            {result.data && <Cards />}
            {result.data && <DockRevision project={result.data.project} />}
            <button onClick={() => release()}>Release dock</button>
            <button onClick={() => reject()}>Reject dock</button>
            <button onClick={() => void result.refetch()}>Refresh project</button>
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
