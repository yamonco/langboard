import { createRoot } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router";
import { api } from "@/core/helpers/Api";
import SecretInputPage from "./SecretInputPage";
import "@/i18n";
import "@/assets/styles/main.css";
api.defaults.baseURL = location.origin;
createRoot(document.getElementById("root")!).render(
    <MemoryRouter initialEntries={["/secret-input/fixture-input"]}>
        <Routes>
            <Route path="/secret-input/:inputUID" element={<SecretInputPage />} />
        </Routes>
    </MemoryRouter>
);
