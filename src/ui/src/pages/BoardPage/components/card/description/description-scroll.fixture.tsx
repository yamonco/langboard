import { useRef, useState } from "react";
import { MemoryRouter } from "react-router";
import { createRoot } from "react-dom/client";
import { AuthUser } from "@/core/models";
import VirtualizedDescriptionContent from "./VirtualizedDescriptionContent";
import type { IDescriptionChunk } from "./descriptionChunks";
import "@/i18n";
import "@/assets/styles/main.css";
const user = AuthUser.Model.fromOne({ uid: "scroll-fixture-user", created_at: new Date(), updated_at: new Date() });
const chunks: IDescriptionChunk[] = Array.from({ length: 60 }, (_, i) => ({
    id: `chunk-${i}`,
    content: `## Section ${i + 1}\n\n${"Description text. ".repeat(90)}`,
    metadata: { type: "paragraph", heading: `Section ${i + 1}`, previewText: `Preview ${i + 1}`, textLength: 1500, isHeavy: false },
}));
function Fixture() {
    const scrollParentRef = useRef<HTMLDivElement>(null);
    const [height, setHeight] = useState(360);
    const [before, setBefore] = useState(120);
    const [short, setShort] = useState(false);
    return (
        <>
            <button onClick={() => setShort((value) => !value)}>Short description</button>
            <button onClick={() => setHeight((h) => (h === 360 ? 520 : 360))}>Resize card</button>
            <button onClick={() => setBefore((h) => (h === 120 ? 240 : 120))}>Expand header</button>
            <div data-card-content-frame style={{ position: "relative", height, width: "100%", maxWidth: 900 }}>
                <div
                    ref={scrollParentRef}
                    data-card-content-viewport
                    tabIndex={0}
                    style={{ height, width: "100%", maxWidth: 900, overflowY: "auto", scrollbarWidth: "none", border: "1px solid" }}
                >
                    <div style={{ height: before }}>Card metadata</div>
                    <VirtualizedDescriptionContent
                        chunks={short ? chunks.slice(0, 2) : chunks}
                        currentUser={user}
                        mentionables={[]}
                        cards={[]}
                        projectUID="fixture"
                        cardUID="fixture"
                        scrollParentRef={scrollParentRef}
                    />
                    <div style={{ height: 400 }}>Card attachments</div>
                </div>
            </div>
        </>
    );
}
createRoot(document.getElementById("root")!).render(
    <MemoryRouter>
        <Fixture />
    </MemoryRouter>
);
