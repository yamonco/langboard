import * as Popover from "@radix-ui/react-popover";
import * as Dialog from "@radix-ui/react-dialog";
import { createRoot } from "react-dom/client";
import { useCallback, useState } from "react";
import { isNotificationInteraction, useNotificationNavigation } from "./useNotificationNavigation";

function Fixture() {
    const [open, setOpen] = useState(false);
    const [route, setRoute] = useState<string | null>(null);
    const close = useCallback(() => setOpen(false), []);
    const { closeThenNavigate, onCloseAutoFocus } = useNotificationNavigation(close, setRoute);
    return (
        <>
            <Popover.Root modal open={open} onOpenChange={setOpen}>
                <Popover.Trigger data-notification-surface="trigger">Notifications</Popover.Trigger>
                <Popover.Portal>
                    <Popover.Content data-notification-surface="content" onCloseAutoFocus={onCloseAutoFocus}>
                        {["card", "wiki", "project"].map((target) => (
                            <button key={target} onClick={() => closeThenNavigate(target)}>
                                Open {target}
                            </button>
                        ))}
                        <Popover.Close>Cancel</Popover.Close>
                    </Popover.Content>
                </Popover.Portal>
            </Popover.Root>
            <Dialog.Root
                modal={false}
                open={route !== null}
                onOpenChange={(next) => {
                    if (!next) setRoute(null);
                }}
            >
                <Dialog.Portal>
                    <Dialog.Content
                        aria-describedby={undefined}
                        onInteractOutside={(event) => {
                            if (isNotificationInteraction(event.detail.originalEvent.target)) event.preventDefault();
                        }}
                    >
                        <Dialog.Title>Destination {route}</Dialog.Title>
                        <button>Destination action</button>
                        <Dialog.Close>Close destination</Dialog.Close>
                    </Dialog.Content>
                </Dialog.Portal>
            </Dialog.Root>
        </>
    );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
