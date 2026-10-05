import "@/core/injection";
import { useState } from "react";
import { createRoot } from "react-dom/client";
import Conversation from "./Conversation";
import { rejectStale } from "./history-recovery.boundary";
import "@/i18n";
import "@/assets/styles/main.css";
export let session = "a";
export const rows = [{ uid: "cached", chat_session_uid: "a", updated_at: new Date() }];
export function Fixture() {
    const [, redraw] = useState(0);
    return (
        <div className="h-screen flex flex-col">
            <button
                onClick={() => {
                    session = "b";
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
