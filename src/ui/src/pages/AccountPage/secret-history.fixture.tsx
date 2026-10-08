import { createRoot } from "react-dom/client";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import { api } from "@/core/helpers/Api";
import SecretHistoryPage from "./SecretHistoryPage";
import "@/i18n";
import "@/assets/styles/main.css";
api.defaults.baseURL = location.origin;
function ReferenceNavigation() {
    const navigate = useNavigate();
    return (
        <nav aria-label="Fixture references">
            <button className="btn btn-sm" onClick={() => navigate("/secret-references/fixture/history")}>
                Fixture reference
            </button>
            <button className="btn btn-sm" onClick={() => navigate("/secret-references/other/history")}>
                Other reference
            </button>
        </nav>
    );
}
createRoot(document.getElementById("root")!).render(
    <MemoryRouter initialEntries={["/secret-references/fixture/history"]}>
        <ReferenceNavigation />
        <Routes>
            <Route path="/secret-references/:referenceUID/history" element={<SecretHistoryPage />} />
        </Routes>
    </MemoryRouter>
);
