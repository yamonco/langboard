import { useCallback, useRef } from "react";

export const isNotificationInteraction = (target: EventTarget | null): boolean =>
    target instanceof Element && !!target.closest("[data-notification-surface]");

export function useNotificationNavigation(close: () => void, navigate: (route: string) => void) {
    const pendingRoute = useRef<string | null>(null);
    const closeThenNavigate = useCallback(
        (route: string) => {
            pendingRoute.current = route;
            close();
        },
        [close]
    );
    const onCloseAutoFocus = useCallback(
        (event: Event) => {
            const route = pendingRoute.current;
            if (route === null) {
                return;
            }
            // The destination owns focus after navigation; do not restore the old overlay trigger.
            event.preventDefault();
            pendingRoute.current = null;
            navigate(route);
        },
        [navigate]
    );
    return { closeThenNavigate, onCloseAutoFocus };
}
