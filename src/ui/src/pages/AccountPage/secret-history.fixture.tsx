import { createRoot } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router";
import { api } from "@/core/helpers/Api";
import SecretHistoryPage from "./SecretHistoryPage";
import "@/i18n";
import "@/assets/styles/main.css";
api.defaults.baseURL = location.origin;
createRoot(document.getElementById("root")!).render(
    <MemoryRouter initialEntries={["/secret-references/fixture/history"]}>
        <Routes>
            <Route path="/secret-references/:referenceUID/history" element={<SecretHistoryPage />} />
        </Routes>
    </MemoryRouter>
);
