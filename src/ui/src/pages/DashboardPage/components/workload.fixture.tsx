import { createRoot } from "react-dom/client";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router";
import { ProjectColumn } from "@/core/models";
import ProjectWorkloadBadges from "./ProjectWorkloadBadges";
import "@/i18n";
import "@/assets/styles/main.css";
const fixtureColumns: Omit<ProjectColumn.IStore, "created_at" | "updated_at">[] = [
    { uid: "ready", project_uid: "fixture", name: "Ready", order: 0, is_archive: false, workflow_stage: "ready", count: 9, incomplete_count: 3 },
    { uid: "active", project_uid: "fixture", name: "Active", order: 1, is_archive: false, workflow_stage: "active", count: 7, incomplete_count: 2 },
    { uid: "done", project_uid: "fixture", name: "Done", order: 2, is_archive: false, workflow_stage: null, count: 99, incomplete_count: 0 },
    { uid: "archive", project_uid: "fixture", name: "Archive", order: 3, is_archive: true, count: 99, incomplete_count: 0 },
];
const columns = ProjectColumn.Model.fromArray(fixtureColumns.map((column) => ({ ...column, created_at: new Date(), updated_at: new Date() })));
function Fixture() {
    const location = useLocation();
    return (
        <div className="w-full max-w-lg space-y-3 p-3">
            <p data-testid="route">
                {location.pathname}
                {location.search}
            </p>
            <section aria-label="Project list">
                <ProjectWorkloadBadges projectUID="fixture" />
            </section>
            <section aria-label="Favorites">
                <ProjectWorkloadBadges projectUID="fixture" compact />
            </section>
            <section aria-label="Explorer">
                <div className="flex items-center justify-between">
                    <button>Project title</button>
                    <ProjectWorkloadBadges projectUID="fixture" compact />
                </div>
            </section>
            <button
                onClick={() => {
                    columns[0].incomplete_count = 0;
                    columns[1].incomplete_count = 1;
                }}
            >
                Apply live counts
            </button>
        </div>
    );
}
const router = createMemoryRouter([{ path: "*", element: <Fixture /> }], { initialEntries: ["/dashboard/projects/all"] });
createRoot(document.getElementById("root")!).render(<RouterProvider router={router} />);
