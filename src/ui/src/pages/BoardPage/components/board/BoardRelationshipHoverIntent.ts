export const RELATIONSHIP_HOVER_OPEN_DELAY_MS = 2_000;
export const RELATIONSHIP_HOVER_CLOSE_DELAY_MS = 3_000;

interface IRelationshipHoverIntentOptions<T> {
    onOpen: (target: T) => void;
    onClose: () => void;
    schedule?: (callback: () => void, delay: number) => unknown;
    cancel?: (timer: unknown) => void;
}

export const createRelationshipHoverIntent = <T>({
    onOpen,
    onClose,
    schedule = (callback, delay) => setTimeout(callback, delay),
    cancel = (timer) => clearTimeout(timer as ReturnType<typeof setTimeout>),
}: IRelationshipHoverIntentOptions<T>) => {
    let pendingOpen: unknown;
    let pendingClose: unknown;
    let activeTarget: T | undefined;

    const cancelOpen = () => {
        if (pendingOpen !== undefined) cancel(pendingOpen);
        pendingOpen = undefined;
    };
    const keepOpen = () => {
        if (pendingClose !== undefined) cancel(pendingClose);
        pendingClose = undefined;
    };
    const close = () => {
        cancelOpen();
        keepOpen();
        activeTarget = undefined;
        onClose();
    };

    return {
        pointerEnter(target: T) {
            keepOpen();
            if (activeTarget === target) return;
            cancelOpen();
            pendingOpen = schedule(() => {
                pendingOpen = undefined;
                activeTarget = target;
                onOpen(target);
            }, RELATIONSHIP_HOVER_OPEN_DELAY_MS);
        },
        pointerLeave() {
            cancelOpen();
            if (activeTarget === undefined) return;
            keepOpen();
            pendingClose = schedule(close, RELATIONSHIP_HOVER_CLOSE_DELAY_MS);
        },
        openImmediately(target: T) {
            cancelOpen();
            keepOpen();
            activeTarget = target;
            onOpen(target);
        },
        keepOpen,
        close,
        dispose() {
            cancelOpen();
            keepOpen();
        },
    };
};
