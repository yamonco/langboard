import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider, useLocation } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthUser, Project, ProjectCard, ProjectColumn } from "@/core/models";
import { BoardProvider, useBoard } from "@/core/providers/BoardProvider";
import BoardFilter from "./BoardFilter";
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
ProjectColumn.Model.fromArray(
    ["ready", "active"].map((uid, order) => ({
        ...base,
        uid,
        project_uid: "fixture",
        name: uid,
        order,
        is_archive: false,
        workflow_stage: uid,
        count: 2,
    }))
);
ProjectCard.Model.fromArray(
    [
        {
            uid: "a",
            title: "Ready mine",
            project_column_uid: "ready",
            member_uids: ["me"],
            creator: { uid: "me", type: "user", name: "Me User", avatar: null },
        },
        {
            uid: "b",
            title: "Active mine",
            project_column_uid: "active",
            member_uids: ["me"],
            creator: { uid: "me", type: "user", name: "Me User", avatar: null },
        },
        {
            uid: "c",
            title: "Ready unassigned",
            project_column_uid: "ready",
            member_uids: [],
            creator: { uid: "old", type: "user", name: "Former User", avatar: null },
        },
    ].map((card, order) => ({
        ...base,
        ...card,
        project_uid: "fixture",
        description: { content: "", type: "text" },
        labels: [],
        relationships:
            card.uid === "a"
                ? [{ ...base, uid: "ab", relationship_type_uid: "contains", parent_card_uid: "a", child_card_uid: "b" }]
                : card.uid === "b"
                  ? [
                        { ...base, uid: "ab", relationship_type_uid: "contains", parent_card_uid: "a", child_card_uid: "b" },
                        { ...base, uid: "bc", relationship_type_uid: "contains", parent_card_uid: "b", child_card_uid: "c" },
                    ]
                  : [{ ...base, uid: "bc", relationship_type_uid: "contains", parent_card_uid: "b", child_card_uid: "c" }],
        order,
    }))
);
function Result() {
    const { cards, filterCard, filterCardMember, filterCardCreator, filterCardLabels, filterCardRelationships } = useBoard();
    const location = useLocation();
    return (
        <>
            <BoardFilter />
            <p data-testid="url">{location.search}</p>
            <section aria-label="Results">
                {cards
                    .filter(
                        (card) =>
                            filterCard(card) &&
                            filterCardMember(card) &&
                            filterCardCreator(card) &&
                            filterCardLabels(card) &&
                            filterCardRelationships(card)
                    )
                    .map((card) => (
                        <p key={card.uid}>{card.title}</p>
                    ))}
            </section>
        </>
    );
}
const router = createBrowserRouter([
    {
        path: "*",
        element: (
            <BoardProvider project={project} currentUser={user}>
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
