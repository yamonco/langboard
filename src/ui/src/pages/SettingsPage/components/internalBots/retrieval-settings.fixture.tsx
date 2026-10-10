import { createRoot } from "react-dom/client";
import { useState } from "react";
import DocumentRetrievalSettings from "./DocumentRetrievalSettings";
import "@/i18n";
import "@/assets/styles/main.css";
function Fixture() {
    const [saved, setSaved] = useState<Record<string, unknown>>({});
    return (
        <>
            <DocumentRetrievalSettings
                value={{ retrieval: { enabled: false, splitter: { strip_headers: true } } }}
                disabled={false}
                onSave={setSaved}
            />
            <output className="block whitespace-pre-wrap break-all">{JSON.stringify(saved)}</output>
        </>
    );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
