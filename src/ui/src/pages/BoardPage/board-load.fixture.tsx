import { Suspense } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { api } from "@/core/helpers/Api";
import { AuthUser, Project } from "@/core/models";
import BoardPage from "./BoardPage";
import "@/i18n";
import "@/assets/styles/main.css";
let reads = 0;
let release: (() => void) | undefined;
api.defaults.adapter = async (config) => {
    document.querySelector("output")!.textContent = String(++reads);
    if (reads > 1)
        await new Promise<void>((resolve) => {
            release = resolve;
        });
    throw new AxiosError("Synthetic unavailable board", "ERR_BAD_RESPONSE", config, undefined, {
        status: 503,
        statusText: "Unavailable",
        data: {},
        headers: {},
        config,
    });
};
const date = new Date();
const currentUser = AuthUser.Model.fromOne({ uid: "fixture-user", created_at: date, updated_at: date });
const project = Project.Model.fromOne({ uid: "fixture-project", title: "Fixture", created_at: date, updated_at: date });
createRoot(document.getElementById("root")!).render(
    <Suspense>
        <MemoryRouter>
            <QueryClientProvider client={new QueryClient()}>
                <output>0</output>
                <button onClick={() => release?.()}>Release retry</button>
                <BoardPage project={project} currentUser={currentUser} />
            </QueryClientProvider>
        </MemoryRouter>
    </Suspense>
);
