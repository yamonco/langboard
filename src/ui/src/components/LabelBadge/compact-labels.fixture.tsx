import { useState } from "react";
import Dialog from "@/components/base/Dialog";
import { createRoot } from "react-dom/client";
import { LabelBadge } from "./index";
import "@/i18n";
import "@/assets/styles/main.css";
function Fixture() {
    const [open, setOpen] = useState(true);
    const [mounted, setMounted] = useState(false);
    const nested = new URLSearchParams(location.search).has("nested");
    return (
        <>
            <div className="p-8" onFocus={() => window.setTimeout(() => setMounted(true), 100)}>
                <div data-testid="row" className="flex items-center gap-1">
                    <LabelBadge compact name="🧩 Contract" emoji="🧩" color="#8B5CF6" />
                    <LabelBadge compact name="Local" color="#10B981" />
                    <LabelBadge compact name="Question" color="#EAB308" />
                    <span>Child title</span>
                </div>
                <button className="mt-10">Outside</button>
                <LabelBadge name="Ordinary" color="#3B82F6" noTooltip />
            </div>
            {nested && mounted && (
                <Dialog.Root modal={false} open={open} onOpenChange={setOpen}>
                    <Dialog.Content
                        onOpenAutoFocus={(event) => event.preventDefault()}
                        nonModalOverlay
                        overlayClassName="pointer-events-none"
                        className="pointer-events-auto"
                        onInteractOutside={(event) => event.preventDefault()}
                        onOverlayInteract={(event) => event.preventDefault()}
                        aria-describedby=""
                    >
                        <Dialog.Title>Parent card</Dialog.Title>
                        <button>Parent action</button>
                    </Dialog.Content>
                </Dialog.Root>
            )}
        </>
    );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
