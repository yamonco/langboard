import { createRoot } from "react-dom/client";
import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import CreateProjectFormDialog from "./CreateProjectFormDialog";
import i18n from "@/i18n";
import "@/assets/styles/main.css";
await i18n.changeLanguage(new URLSearchParams(location.search).get("lang") ?? "en-US");
function Fixture() {
    const [opened, setOpened] = useState(true);
    return <CreateProjectFormDialog opened={opened} setOpened={setOpened} />;
}
createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
            <Fixture />
        </MemoryRouter>
    </QueryClientProvider>
);
