import "@/core/injection";
import { useState } from "react";
import { createRoot } from "react-dom/client";
import Conversation from "./Conversation";
import { rejectStale } from "./history-recovery.boundary";
import { selectSession } from "./history-recovery.state";
import "@/i18n";
import "@/assets/styles/main.css";
export function Fixture() {
    const [, redraw] = useState(0);
    return (
        <div className="h-screen flex flex-col">
            <button
                onClick={() => {
                    selectSession("b");
                    redraw((v) => v + 1);
                }}
            >
                Switch session
            </button>
            <button onClick={() => rejectStale()}>Reject stale request</button>
            <Conversation />
        </div>
    );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
