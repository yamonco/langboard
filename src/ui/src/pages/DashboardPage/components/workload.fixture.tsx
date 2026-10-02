import { createRoot } from "react-dom/client";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ProjectCompactList from "./ProjectCompactList";
import { Project, ProjectColumn } from "@/core/models";
import ProjectWorkloadBadges from "./ProjectWorkloadBadges";
import i18n from "@/i18n";
import "@/core/injection/StringExtensions";
await i18n.changeLanguage(new URLSearchParams(location.search).get("lang") ?? "en-US");
import "@/assets/styles/main.css";
const fixtureColumns: Omit<ProjectColumn.IStore, "created_at" | "updated_at">[] = [
    {
        uid: "ready",
        project_uid: "fixture",
        name: "Ready",
        order: 0,
        is_archive: false,
        workflow_stage: "ready",
        count: 9,
        open_count: 9,
        incomplete_count: 1,
    },
    {
        uid: "active",
        project_uid: "fixture",
        name: "Active",
        order: 1,
        is_archive: false,
        workflow_stage: "active",
        count: 7,
        open_count: 7,
        incomplete_count: 4,
    },
    {
        uid: "review",
        project_uid: "fixture",
        name: "Review",
        order: 2,
        is_archive: false,
        workflow_stage: "review",
        count: 8,
        open_count: 8,
        incomplete_count: 2,
    },
    {
        uid: "request",
        project_uid: "fixture",
        name: "Request",
        order: 3,
        is_archive: false,
        workflow_stage: "backlog",
        count: 6,
        open_count: 6,
        incomplete_count: 3,
    },
    {
        uid: "done",
        project_uid: "fixture",
        name: "Done",
        order: 2,
        is_archive: false,
        workflow_stage: null,
        count: 99,
        open_count: 0,
        incomplete_count: 0,
    },
    { uid: "archive", project_uid: "fixture", name: "Archive", order: 3, is_archive: true, count: 99, open_count: 0, incomplete_count: 0 },
];
const columns = ProjectColumn.Model.fromArray(fixtureColumns.map((column) => ({ ...column, created_at: new Date(), updated_at: new Date() })));
function Fixture() {
    const location = useLocation();
    return (
        <div className="w-full max-w-lg space-y-3 p-3">
            <ProjectCompactList projects={projects} title="Project count" initialVisibleCount={1} updateStarredProjects={() => {}} />
            <p data-testid="route" className="break-all">
                {location.pathname}
                {location.search}
            </p>
            <section aria-label="Project list">
                <ProjectWorkloadBadges projectUID="fixture" />
            </section>
            <section aria-label="Favorites">
                <div className="flex min-w-0 items-center gap-1" style={{ containerType: "inline-size", containerName: "project-workload" }}>
                    <button className="min-w-0 flex-1 truncate" data-testid="favorite-title">
                        A visible project name
                    </button>
                    <ProjectWorkloadBadges projectUID="fixture" compact />
                </div>
            </section>
            <section aria-label="Explorer">
                <div className="flex min-w-0 items-center gap-1" style={{ containerType: "inline-size", containerName: "project-workload" }}>
                    <button className="min-w-0 flex-1 truncate" data-testid="explorer-title">
                        Project title
                    </button>
                    <ProjectWorkloadBadges projectUID="fixture" compact />
                </div>
            </section>
            <button
                onClick={() => {
                    ProjectColumn.Model.fromOne({
                        ...fixtureColumns[0],
                        open_count: 1234,
                        incomplete_count: 1234,
                        created_at: new Date(),
                        updated_at: new Date(),
                    });
                }}
            >
                Apply large counts
            </button>
            <button
                onClick={() => {
                    columns[0].incomplete_count = 0;
                    columns[1].incomplete_count = 1;
                    columns[2].incomplete_count = 0;
                    columns[3].incomplete_count = 0;
                }}
            >
                Apply live counts
            </button>
        </div>
    );
}
const projects = Project.Model.fromArray(
    Array.from({ length: 1002 }, (_, index) => ({
        uid: `project-${index}`,
        title: `Project ${index}`,
        project_type: "Other",
        created_at: new Date(),
        updated_at: new Date(),
        starred: false,
    }))
);
const router = createMemoryRouter([{ path: "*", element: <Fixture /> }], { initialEntries: ["/dashboard/projects/all"] });
createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={new QueryClient()}>
        <RouterProvider router={router} />
    </QueryClientProvider>
);
