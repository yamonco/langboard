import { createRoot } from "react-dom/client";
import { LabelBadge } from "./index";
import "@/i18n";
import "@/assets/styles/main.css";
createRoot(document.getElementById("root")!).render(
    <div className="p-8">
        <div data-testid="row" className="flex items-center gap-1">
            <LabelBadge compact name="🧩 Contract" emoji="🧩" color="#8B5CF6" />
            <LabelBadge compact name="Local" color="#10B981" />
            <LabelBadge compact name="Question" color="#EAB308" />
            <span>Child title</span>
        </div>
        <button className="mt-10">Outside</button>
        <LabelBadge name="Ordinary" color="#3B82F6" noTooltip />
    </div>
);
