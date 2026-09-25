import Popover from "@/components/base/Popover";
import Dialog from "@/components/base/Dialog";
import Button from "@/components/base/Button";
import "@/assets/styles/main.css";
import { CARD_WINDOW_EMBEDDED_OVERLAY_CLASS, CARD_WINDOW_HEIGHT_CLASS, CARD_WINDOW_OVERLAY_CLASS } from "@/pages/BoardPage/cardWindowLayout";
import { cn } from "@/core/utils/ComponentUtils";
import { createRoot } from "react-dom/client";
import { useCallback, useState } from "react";
import { isNotificationInteraction, useNotificationNavigation } from "./useNotificationNavigation";

function Fixture() {
    const embedded = new URLSearchParams(window.location.search).has("embedded");
    const overlayClass = embedded ? CARD_WINDOW_EMBEDDED_OVERLAY_CLASS : CARD_WINDOW_OVERLAY_CLASS;
    const [open, setOpen] = useState(false);
    const [route, setRoute] = useState<string | null>(null);
    const close = useCallback(() => setOpen(false), []);
    const { closeThenNavigate, onCloseAutoFocus } = useNotificationNavigation(close, setRoute);
    return (
        <>
            <header className="sticky top-0 z-10 flex h-16 items-center gap-4 border-b bg-background px-4">
                <Popover.Root modal open={open} onOpenChange={setOpen}>
                    <Popover.Trigger asChild>
                        <Button data-notification-surface="trigger" title="Notification shortcut">
                            Notifications
                        </Button>
                    </Popover.Trigger>
                    <Popover.Content data-notification-surface="content" onCloseAutoFocus={onCloseAutoFocus}>
                        {["card", "wiki", "project"].map((target) => (
                            <button key={target} onClick={() => closeThenNavigate(target)}>
                                Open {target}
                            </button>
                        ))}
                        <button onClick={close}>Cancel</button>
                    </Popover.Content>
                </Popover.Root>
                <button>Other navigation</button>
            </header>
            <main className="relative h-[calc(100dvh-theme(spacing.16))]">
                <Dialog.Root
                    modal={false}
                    open={route !== null}
                    onOpenChange={(next) => {
                        if (!next) setRoute(null);
                    }}
                >
                    <Dialog.Content
                        nonModalOverlay
                        withCloseButton={false}
                        className={cn(
                            "h-[calc(100dvh-theme(spacing.6))] sm:h-[calc(100dvh-theme(spacing.8))]",
                            "w-[calc(100vw-theme(spacing.4))] max-w-none p-6",
                            CARD_WINDOW_HEIGHT_CLASS
                        )}
                        overlayClassName={overlayClass}
                        disablePortal={embedded}
                        contentWrapperClassName={cn(
                            "pointer-events-none !items-start pb-2 pt-4 sm:pt-6",
                            "[&_[data-dialog-content=true]]:pointer-events-auto"
                        )}
                        viewportClassName="!py-0"
                        onOverlayInteract={(event) => {
                            if (isNotificationInteraction(event.target)) event.preventDefault();
                            else setRoute(null);
                        }}
                        aria-describedby={undefined}
                        onInteractOutside={(event) => {
                            if (isNotificationInteraction(event.detail.originalEvent.target)) event.preventDefault();
                        }}
                    >
                        <Dialog.Title>Destination {route}</Dialog.Title>
                        <button>Destination action</button>
                        <Dialog.Close>Close destination</Dialog.Close>
                    </Dialog.Content>
                </Dialog.Root>
            </main>
        </>
    );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
