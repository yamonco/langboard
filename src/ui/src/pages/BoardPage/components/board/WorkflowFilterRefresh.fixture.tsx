import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthUser, Project, ProjectCard, ProjectColumn } from "@/core/models";
import { BoardProvider, useBoard } from "@/core/providers/BoardProvider";
import "@/i18n";
import "@/assets/styles/main.css";
const base = { created_at: new Date(), updated_at: new Date() };
const user = AuthUser.Model.fromOne({
    ...base,
    uid: "me",
    type: "user",
    email: "me@example.test",
    firstname: "Me",
    lastname: "User",
    username: "me",
    is_admin: true,
    user_groups: [],
    subemails: [],
    api_key_role_actions: [],
    setting_role_actions: [],
    mcp_role_actions: [],
});
const project = Project.Model.fromOne({
    ...base,
    uid: "fixture",
    title: "Fixture",
    all_members: [user],
    labels: [],
    invited_member_uids: [],
    current_auth_role_actions: ["*"],
});
const column = ProjectColumn.Model.fromOne({
    ...base,
    uid: "queue",
    project_uid: "fixture",
    name: "Queue",
    order: 0,
    is_archive: false,
    workflow_stage: "ready",
    count: 0,
});
const count = Number(new URLSearchParams(location.search).get("count") ?? 3);
ProjectCard.Model.fromArray(
    Array.from({ length: count }, (_, order) => ({
        ...base,
        uid: `card${order}`,
        title: `Task ${order}`,
        project_uid: "fixture",
        project_column_uid: column.uid,
        description: { content: "", type: "text" },
        labels: [],
        relationships: [],
        member_uids: [],
        order,
    }))
);
function Controls() {
    return (
        <label>
            Stage
            <select
                aria-label="Stage"
                defaultValue="ready"
                onChange={(event) => {
                    column.workflow_stage = event.target.value || null;
                }}
            >
                {["ready", "active", "closed", "reference", ""].map((stage) => (
                    <option key={stage} value={stage}>
                        {stage || "unclassified"}
                    </option>
                ))}
            </select>
        </label>
    );
}
function Result() {
    const { cards, filterCard } = useBoard();
    return (
        <section aria-label="Results">
            {cards.filter(filterCard).map((card) => (
                <p key={card.uid} data-card-uid={card.uid} data-order={card.order}>
                    {card.title}
                </p>
            ))}
        </section>
    );
}
const router = createBrowserRouter([
    {
        path: "*",
        element: (
            <BoardProvider project={project} currentUser={user}>
                <Controls />
                <Result />
            </BoardProvider>
        ),
    },
]);
createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={new QueryClient()}>
        <RouterProvider router={router} />
    </QueryClientProvider>
);
