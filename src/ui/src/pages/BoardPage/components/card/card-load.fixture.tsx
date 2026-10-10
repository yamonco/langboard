import { Suspense, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { api } from "@/core/helpers/Api";
import { AuthUser } from "@/core/models";
import Dialog from "@/components/base/Dialog";
import BoardCard from "./BoardCard";
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
    throw new AxiosError("Synthetic unavailable card", "ERR_BAD_RESPONSE", config, undefined, {
        status: 503,
        statusText: "Unavailable",
        data: {},
        headers: {},
        config,
    });
};
const currentUser = AuthUser.Model.fromOne({ uid: "fixture-user", created_at: new Date(), updated_at: new Date() });
function Fixture() {
    const viewportRef = useRef<HTMLDivElement>(null);
    const [open, setOpen] = useState(true);
    return (
        <>
            <output>0</output>
            {open ? (
                <Dialog.Root open modal={false}>
                    <Dialog.Content withCloseButton={false} nonModalOverlay className="flex flex-col gap-3">
                        <button onClick={() => release?.()}>Release retry</button>
                        <BoardCard
                            projectUID="fixture-project"
                            cardUID="fixture-card"
                            currentUser={currentUser}
                            viewportRef={viewportRef}
                            onClose={() => setOpen(false)}
                        />
                    </Dialog.Content>
                </Dialog.Root>
            ) : (
                <p>Card closed</p>
            )}
        </>
    );
}
createRoot(document.getElementById("root")!).render(
    <Suspense>
        <MemoryRouter>
            <QueryClientProvider client={new QueryClient()}>
                <Fixture />
            </QueryClientProvider>
        </MemoryRouter>
    </Suspense>
);
