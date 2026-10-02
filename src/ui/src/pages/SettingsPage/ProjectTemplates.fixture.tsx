import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ProjectTemplatesPage from "./ProjectTemplatesPage";
import "@/i18n";
import "@/assets/styles/main.css";
createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={new QueryClient()}>
        <ProjectTemplatesPage />
    </QueryClientProvider>
);
