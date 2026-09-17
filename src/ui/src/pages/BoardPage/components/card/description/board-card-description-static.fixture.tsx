import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router";

import BoardCardDescriptionStaticChunk from "./BoardCardDescriptionStaticChunk";
import "@/assets/styles/main.css";

const chunk = {
    id: "internal-link-chunk",
    content: "Before [[card:fixture-card]] after https://example.com/fixture",
    metadata: {
        type: "paragraph",
        previewText: "Before [[card:fixture-card]] after",
        textLength: 34,
        isHeavy: false,
    },
} as const;

const root = createRoot(document.getElementById("root")!);

root.render(
    <MemoryRouter initialEntries={["/"]}>
        <main style={{ padding: 24, maxWidth: 700, margin: "auto" }}>
            <BoardCardDescriptionStaticChunk
                chunk={chunk}
                currentUser={undefined as never}
                mentionables={[]}
                cards={[]}
                projectUID="fixture-project"
                cardUID="fixture-card-owner"
            />
        </main>
    </MemoryRouter>
);
