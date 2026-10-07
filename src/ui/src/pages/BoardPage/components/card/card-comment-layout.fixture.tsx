import { useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { AuthUser, ProjectCard } from "@/core/models";
import { BoardCardProvider, useBoardCardPanel } from "@/core/providers/BoardCardProvider";
import "@/i18n";
import "@/assets/styles/main.css";
const user = AuthUser.Model.fromOne({ uid: "comment-fixture-user", created_at: new Date(), updated_at: new Date() });
const card = ProjectCard.Model.fromOne({
    uid: "comment-fixture-card",
    count_comment: 1,
    current_auth_role_actions: [],
    created_at: new Date(),
    updated_at: new Date(),
});
function Content() {
    const { commentSurfaceRef, commentLayoutMode, toggleActionPanel } = useBoardCardPanel();
    const [width, setWidth] = useState(600);
    return (
        <>
            <button onClick={() => setWidth(900)}>Wide card</button>
            <button onClick={() => setWidth(600)}>Narrow card</button>
            <button onClick={toggleActionPanel}>Toggle actions</button>
            <div ref={commentSurfaceRef} style={{ width, border: "1px solid" }}>
                <output data-testid="comment-layout">{commentLayoutMode}</output>
            </div>
        </>
    );
}
function Fixture() {
    const ref = useRef<HTMLDivElement>(null);
    return (
        <BoardCardProvider projectUID="fixture" card={card} currentUser={user} viewportRef={ref}>
            <Content />
        </BoardCardProvider>
    );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
