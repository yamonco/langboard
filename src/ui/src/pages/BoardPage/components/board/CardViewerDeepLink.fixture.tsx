import { StrictMode, lazy, Suspense, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, Navigate, Route, Routes, useLocation, useParams } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/i18n";
import "@/assets/styles/main.css";
import { AuthProvider } from "@/core/providers/AuthProvider";
import { SocketProvider } from "@/core/providers/SocketProvider";
import { PageHeaderProvider } from "@/core/providers/PageHeaderProvider";
import { BoardController } from "@/core/providers/BoardController";
import BoardCardPage from "@/pages/BoardPage/BoardCardPage";
import useAuthStore from "@/core/stores/AuthStore";
import { AuthUser } from "@/core/models";
import { SkeletonBoard } from "@/pages/BoardPage/components/board/Board";

/**
 * Deep-link entry harness for the card viewer.
 *
 * Reproduces the cold /board/:projectUID/:cardUID mount sequence with the real
 * providers, the real BoardCardPage, and the same conditional + keying
 * structure as BoardProxy/BoardProxyDisplay (src/pages/BoardPage/index.tsx):
 *
 *   {currentUser && project ? (... <BoardCardPage key={cardUID} embedded/>) : <Skeleton/>}
 *
 * Every timing phase is configurable through query parameters so a spec can
 * race auth, project, and card data exactly like a real cold load:
 *   ?projectDelay=ms&cardDelay=ms&strictMode=0|1&lateSuspense=0|1&lateSuspenseAt=ms
 *
 * Instrumentation (installed before the first render):
 *   - window.__events: viewer mount/unmount + card-viewer-open animation starts
 *   - window.__viewerMounted: number of [data-card-viewer] elements ever mounted
 *   - window.__openAnimationStarts: times card-viewer-open started
 */

const query = new URLSearchParams(window.location.search);
const delay = (name: string) => Number(query.get(name) ?? 0);
const PROJECT_DELAY = delay("projectDelay");
// Non-production builds of the app mount under React.StrictMode (main.tsx),
// which double-invokes mounts; mirror that for remount-driven replays.
const STRICT_MODE = query.get("strictMode") === "1";
// Mirror the app-root Suspense (Router.tsx): any late lazy chunk suspending
// after the card viewer mounted unmounts the whole children subtree and
// remounts it on resolve, replaying mount-driven animations.
const LATE_SUSPENSE = query.get("lateSuspense") === "1";
const LATE_SUSPENSE_AT = delay("lateSuspenseAt") || 800;

const LateChunk = lazy(
    () =>
        import("./CardViewerDeepLinkLateChunk.fixture").then(
            (module) => new Promise<typeof module>((resolve) => window.setTimeout(() => resolve(module), 500))
        ) as never as Promise<{ default: React.ComponentType }>
);

function LateSuspenseSibling(): React.JSX.Element | null {
    const [show, setShow] = useState(false);

    useEffect(() => {
        const timer = window.setTimeout(() => setShow(true), LATE_SUSPENSE_AT);
        return () => window.clearTimeout(timer);
    }, []);

    return show ? <LateChunk /> : null;
}

const PROJECT_UID = "fixture-project";
const CARD_UID = "fixture-card";

const fixtureUser = AuthUser.Model.fromOne({
    uid: "fixture-user",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    type: "user",
    firstname: "Fixture",
    lastname: "User",
    email: "fixture@example.com",
    username: "fixture",
    api_key_role_actions: ["all"],
    setting_role_actions: ["all"],
    mcp_role_actions: ["all"],
    user_groups: [],
    subemails: [],
    preferred_lang: "en",
    notification_unsubs: {},
    industry: "",
    purpose: "",
} as never);

type TEvent = { type: string; t: number };
const events: TEvent[] = [];
const record = (type: string) => {
    events.push({ type, t: performance.now() });
};

let viewerMounted = 0;
let openAnimationStarts = 0;
const trackedViewers = new WeakSet<Element>();

document.addEventListener(
    "animationstart",
    (event) => {
        const target = event.target as Element;
        if (target instanceof Element && target.hasAttribute("data-card-viewer") && event.animationName === "card-viewer-open") {
            openAnimationStarts += 1;
            record("animationstart:card-viewer-open");
        }
    },
    true
);

function trackViewer(node: Element): void {
    if (!node.hasAttribute("data-card-viewer") || trackedViewers.has(node)) {
        return;
    }
    trackedViewers.add(node);
    viewerMounted += 1;
    record("viewer-mounted");
}

new MutationObserver((mutations) => {
    for (const mutation of mutations) {
        if (mutation.type === "attributes" && mutation.target instanceof Element) {
            trackViewer(mutation.target);
            continue;
        }
        for (const node of mutation.addedNodes) {
            if (node instanceof Element) {
                trackViewer(node);
                node.querySelectorAll?.("[data-card-viewer]").forEach(trackViewer);
            }
        }
        for (const node of mutation.removedNodes) {
            if (node instanceof Element && (trackedViewers.has(node) || !!node.querySelector?.("[data-card-viewer]"))) {
                trackedViewers.delete(node);
                record("viewer-unmounted");
            }
        }
    }
}).observe(document.documentElement, { childList: true, subtree: true, attributeFilter: ["data-card-viewer"] });

// Signed-in session restored before the board route renders.
useAuthStore.setState({ currentUser: fixtureUser, state: "loaded" });

const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: Infinity } },
});

function useHasCurrentUser(): boolean {
    const [hasUser, setHasUser] = useState(!!useAuthStore.getState().currentUser);

    useEffect(() => {
        const unsubscribe = useAuthStore.subscribe(() => {
            setHasUser(!!useAuthStore.getState().currentUser);
        });
        return unsubscribe;
    }, []);

    return hasUser;
}

/**
 * Mirrors BoardProxy: skeleton while the project summary is unavailable, then
 * BoardProxyDisplay with the same currentUser/project conditional and the same
 * key={pageRoute} the real board uses for the embedded card viewer.
 */
function BoardRouteFixture(): React.JSX.Element {
    const [projectReady, setProjectReady] = useState(false);
    const hasUser = useHasCurrentUser();
    const location = useLocation();
    const { projectUID } = useParams();
    const [, pageRoute] = location.pathname.split("/").slice(2);
    const isCardPage = !!pageRoute && !["graph", "wiki", "settings"].includes(pageRoute);

    useEffect(() => {
        const timer = window.setTimeout(() => setProjectReady(true), PROJECT_DELAY);
        return () => window.clearTimeout(timer);
    }, [PROJECT_DELAY]);

    if (!projectReady) {
        return <SkeletonBoard />;
    }

    return (
        <div className="flex h-[100dvh] w-full flex-col">
            {hasUser ? (
                <div className="relative min-w-0 flex-1">
                    <div className="relative size-full" />
                    {isCardPage && <BoardCardPage key={pageRoute} projectUID={projectUID ?? PROJECT_UID} cardUID={pageRoute} embedded />}
                </div>
            ) : (
                <SkeletonBoard />
            )}
        </div>
    );
}

function Harness(): React.JSX.Element {
    const tree = (
        <MemoryRouter initialEntries={[`/board/${PROJECT_UID}/${CARD_UID}`]}>
            <QueryClientProvider client={queryClient}>
                <PageHeaderProvider>
                    <AuthProvider>
                        <SocketProvider>
                            <BoardController>
                                <Routes>
                                    <Route path="/board/:projectUID" element={<BoardRouteFixture />} />
                                    <Route path="/board/:projectUID/:cardUID" element={<BoardRouteFixture />} />
                                    <Route path="*" element={<div data-fixture-not-found="" />} />
                                </Routes>
                                {LATE_SUSPENSE && <LateSuspenseSibling />}
                            </BoardController>
                        </SocketProvider>
                    </AuthProvider>
                </PageHeaderProvider>
            </QueryClientProvider>
        </MemoryRouter>
    );

    if (!LATE_SUSPENSE) {
        return tree;
    }

    return <Suspense fallback={<div data-fixture-suspense-fallback="" />}>{tree}</Suspense>;
}

const root = createRoot(document.getElementById("root")!);
root.render(
    STRICT_MODE ? (
        <StrictMode>
            <Harness />
        </StrictMode>
    ) : (
        <Harness />
    )
);

// Spec-side readout (values keep updating; the spec polls them).
window.setInterval(() => {
    const globals = window as unknown as Record<string, unknown>;
    globals.__viewerMounted = viewerMounted;
    globals.__openAnimationStarts = openAnimationStarts;
    globals.__events = [...events];
    const authState = useAuthStore.getState();
    globals.__authState = { state: authState.state, hasUser: !!authState.currentUser };
}, 50);
