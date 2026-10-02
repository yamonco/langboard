import "@/core/injection";
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router";
import { getUserSettingsStore } from "@/core/stores/UserSettingsStore";
import { focusCard, useOpenCards } from "./OpenCardsStore";
import { recentOpenCards } from "./OpenCardsData";
import RecentCardsSection from "./RecentCardsSection";
import "@/i18n";
import "@/assets/styles/main.css";
const count = Number(new URLSearchParams(location.search).get("count") || 14);
getUserSettingsStore().updateSettingsByKey("open_cards", {
    fixture: Array.from({ length: count }, (_, index) => ({
        projectUID: "fixture",
        cardUID: String(index),
        title: `Card ${index}`,
        pinned: index === 0,
        lastFocusedAt: `2026-10-02T00:00:${String(index).padStart(2, "0")}Z`,
    })),
});
function Fixture() {
    const cards = recentOpenCards(useOpenCards("fixture"));
    const [expanded, setExpanded] = useState(false);
    const [collapsed, setCollapsed] = useState(false);
    const location = useLocation();
    return (
        <div className="h-screen w-full max-w-lg p-2">
            <p data-testid="route">{location.pathname}</p>
            <button onClick={() => focusCard("fixture", { projectUID: "fixture", cardUID: "0", title: "Card 0" })}>Read oldest again</button>
            <nav className="flex h-[65vh] min-h-0 flex-col overflow-hidden" aria-label="Explorer">
                <div className="shrink-0 p-2">Explorer</div>
                <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-2 pb-3">
                    <section className="mb-3 shrink-0">
                        Current project
                        <br />
                        Board
                        <br />
                        Wiki
                    </section>
                    <RecentCardsSection
                        userUID="fixture"
                        cards={cards}
                        collapsed={collapsed}
                        expanded={expanded}
                        onExpand={() => setExpanded((shown) => !shown)}
                        onToggle={() => setCollapsed((shown) => !shown)}
                    />
                    <div className="min-h-24 flex-1 overflow-y-auto" data-explorer-project-list="">
                        <h2>Favorites</h2>
                        {Array.from({ length: 20 }, (_, index) => (
                            <p key={index}>Project {index}</p>
                        ))}
                    </div>
                </div>
            </nav>
        </div>
    );
}
const router = createMemoryRouter([{ path: "*", element: <Fixture /> }], { initialEntries: ["/board/fixture"] });
createRoot(document.getElementById("root")!).render(<RouterProvider router={router} />);
