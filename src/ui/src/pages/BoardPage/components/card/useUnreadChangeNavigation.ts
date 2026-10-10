import { useEffect, useRef } from "react";
import useMarkCardSeen from "@/controllers/api/board/useMarkCardSeen";
import { useBoardCard, useBoardCardPanel } from "@/core/providers/BoardCardProvider";
import { ProjectCard } from "@/core/models";

const HIGHLIGHT_CLASS = "unread-target-highlight";
const HIGHLIGHT_DURATION_MS = 1800;
const TARGET_WAIT_TIMEOUT_MS = 4000;
const TARGET_WAIT_INTERVAL_MS = 120;

function styleHighlight(): void {
    if (document.getElementById("unread-target-highlight-style")) {
        return;
    }
    const style = document.createElement("style");
    style.id = "unread-target-highlight-style";
    style.textContent = `.${HIGHLIGHT_CLASS}{outline:2px solid var(--primary);outline-offset:2px;transition:outline-color .4s;}`;
    document.head.appendChild(style);
}

function highlightElement(element: Element): void {
    styleHighlight();
    element.classList.add(HIGHLIGHT_CLASS);
    window.setTimeout(() => element.classList.remove(HIGHLIGHT_CLASS), HIGHLIGHT_DURATION_MS);
}

function waitForElement(selector: string): Promise<Element | null> {
    return new Promise((resolve) => {
        const startedAt = Date.now();
        const timer = window.setInterval(() => {
            const element = document.querySelector(selector);
            if (element) {
                window.clearInterval(timer);
                resolve(element);
                return;
            }
            if (Date.now() - startedAt > TARGET_WAIT_TIMEOUT_MS) {
                window.clearInterval(timer);
                resolve(null);
            }
        }, TARGET_WAIT_INTERVAL_MS);
    });
}

function nextFrames(): Promise<void> {
    return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
}

async function scrollIntoViewStable(element: Element): Promise<void> {
    for (let attempt = 0; attempt < 3; attempt++) {
        await nextFrames();
        element.scrollIntoView({ behavior: attempt === 0 ? "smooth" : "auto", block: "center" });
        await new Promise((resolve) => window.setTimeout(resolve, 350));
        const rect = element.getBoundingClientRect();
        if (rect.top >= 0 && rect.bottom <= window.innerHeight) {
            return;
        }
    }
}

/**
 * Jump once to the newest unread change of a card and highlight it.
 * Navigation is best-effort; the read cursor advances as soon as the
 * card detail has mounted.
 */
export function useUnreadChangeNavigation(): void {
    const { card, projectUID } = useBoardCard();
    const { setIsCommentPanelOpen } = useBoardCardPanel();
    const { mutate: markSeen } = useMarkCardSeen();
    const handledRef = useRef<bool>(false);

    useEffect(() => {
        if (handledRef.current) {
            return;
        }
        handledRef.current = true;

        const model = card as ProjectCard.TModel;
        if (!model.has_unread_change) {
            return;
        }

        const targetType = model.last_change_target_type;
        const targetUID = model.last_change_target_uid;

        const focus = async () => {
            if (targetType === "comment" && targetUID) {
                setIsCommentPanelOpen(true);
                const element = await waitForElement(`[data-card-comment-uid="${targetUID}"]`);
                if (element) {
                    await scrollIntoViewStable(element);
                    highlightElement(element);
                }
                return;
            }
            if (targetType === "description" || targetType === "card") {
                const element = await waitForElement("[data-card-description]");
                if (element) {
                    await scrollIntoViewStable(element);
                    highlightElement(element);
                }
            }
        };

        void focus();
        markSeen({ project_uid: projectUID, card_uid: card.uid });
        model.has_unread_change = false;
    }, [card, markSeen, projectUID, setIsCommentPanelOpen]);
}

export default useUnreadChangeNavigation;
