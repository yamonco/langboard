import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Button from "@/components/base/Button";
import { api } from "@/core/helpers/Api";
import type { CatalogApp } from "@/controllers/api/board/useBoardAppCatalog";
import { loadPanelResources, readPanelDesign } from "@/core/apps/PanelDesign";
import { activePanelDisposals, panelStateCache } from "@/core/apps/PanelSession";
import { createPanelHost, type JsonValue } from "@langboard/app-panel";

interface Props {
    app: CatalogApp;
    projectUID: string;
    userUID: string;
    onClose: () => void;
}
interface PanelPermission {
    key: string;
    version: string;
    panel: { url: string; name: string };
    app_revision: string;
    binding_revision: string;
}

// A live frame belongs to one permission read and one visible document session.
export function useAppPanel({ app, projectUID, userUID, onClose }: Props) {
    const [, i18n] = useTranslation();
    const language = i18n.resolvedLanguage ?? i18n.language;
    const container = useRef<HTMLDivElement>(null);
    const closeRef = useRef(onClose);
    closeRef.current = onClose;
    const [intersecting, setIntersecting] = useState(false);
    const [visible, setVisible] = useState(!document.hidden);
    const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
    useEffect(() => {
        const update = () => setVisible(!document.hidden);
        document.addEventListener("visibilitychange", update);
        return () => document.removeEventListener("visibilitychange", update);
    }, []);
    useEffect(() => {
        const observer = new IntersectionObserver(([entry]) =>
            setIntersecting(entry.isIntersecting && entry.intersectionRect.width > 0 && entry.intersectionRect.height > 0)
        );
        if (container.current) observer.observe(container.current);
        return () => observer.disconnect();
    }, []);
    useEffect(() => {
        if (!visible || !intersecting || !container.current) return;
        const controller = new AbortController();
        let frame: HTMLIFrameElement | undefined;
        let loadTimer: ReturnType<typeof setTimeout> | undefined;
        let disposeHost: ReturnType<typeof createPanelHost> | undefined;
        let themeObserver: MutationObserver | undefined;
        let stateKey = JSON.stringify([userUID, projectUID, app.key, app.version]);
        const teardown = () => {
            controller.abort();
            clearTimeout(loadTimer);
            themeObserver?.disconnect();
            disposeHost?.();
            frame?.remove();
        };
        activePanelDisposals.set(stateKey, teardown);
        const fail = () => {
            panelStateCache.delete(stateKey);
            teardown();
            setStatus("error");
        };
        const onHidden = () => {
            if (document.hidden) teardown();
        };
        document.addEventListener("visibilitychange", onHidden);
        setStatus("loading");
        void api
            .get<PanelPermission>(`/board/${projectUID}/apps/${encodeURIComponent(app.key)}/panel`, {
                signal: controller.signal,
                env: { interceptToast: true } as never,
            })
            .then(async ({ data }) => {
                const resources = await loadPanelResources(controller.signal);
                if (controller.signal.aborted || document.hidden || !container.current) return;
                activePanelDisposals.delete(stateKey);
                stateKey = JSON.stringify([userUID, projectUID, app.key, data.version]);
                activePanelDisposals.set(stateKey, teardown);
                frame = document.createElement("iframe");
                frame.setAttribute("sandbox", "allow-scripts allow-forms");
                frame.referrerPolicy = "no-referrer";
                frame.title = data.panel.name;
                frame.className = "size-full border-0";
                frame.addEventListener(
                    "load",
                    () => {
                        if (controller.signal.aborted || document.hidden || !frame) return;
                        try {
                            disposeHost = createPanelHost({
                                frame,
                                context: { project_uid: projectUID, app_key: app.key, app_version: data.version, language },
                                state: panelStateCache.get(stateKey),
                                design: { ...readPanelDesign(), resources },
                                onRequest: async (operation: string, params: JsonValue, signal: AbortSignal) => {
                                    if (operation !== "signals.list") throw new Error("Unsupported panel operation");
                                    if (
                                        !params ||
                                        typeof params !== "object" ||
                                        Array.isArray(params) ||
                                        Object.keys(params).some((key) => key !== "provider" && key !== "after") ||
                                        typeof params.provider !== "string" ||
                                        !/^[a-z][a-z0-9_-]{0,31}$/.test(params.provider) ||
                                        (params.after !== undefined && typeof params.after !== "string")
                                    )
                                        throw new Error("Invalid signal request parameters");
                                    const response = await api.post<JsonValue>(
                                        `/board/${projectUID}/apps/${encodeURIComponent(app.key)}/panel/signals`,
                                        { ...params, app_revision: data.app_revision, binding_revision: data.binding_revision },
                                        { signal: AbortSignal.any([signal, controller.signal]), env: { interceptToast: true } as never }
                                    );
                                    return response.data;
                                },
                                onState: (state) => panelStateCache.set(stateKey, state),
                                onReady: () => {
                                    clearTimeout(loadTimer);
                                    setStatus("ready");
                                },
                                onClose: () => {
                                    teardown();
                                    closeRef.current();
                                },
                                onError: fail,
                            });
                            themeObserver = new MutationObserver(() => {
                                if (!controller.signal.aborted) disposeHost?.updateDesign(readPanelDesign());
                            });
                            themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "style"] });
                        } catch {
                            fail();
                        }
                    },
                    { once: true }
                );
                loadTimer = setTimeout(fail, 10_000);
                frame.src = data.panel.url;
                container.current.append(frame);
            })
            .catch(() => {
                if (!controller.signal.aborted) fail();
            });
        return () => {
            activePanelDisposals.delete(stateKey);
            document.removeEventListener("visibilitychange", onHidden);
            teardown();
        };
    }, [visible, intersecting, language, projectUID, userUID, app.key, app.version, app.panel?.url, app.app_revision, app.binding?.revision]);
    return { container, status };
}

export default function AppPanel(props: Props) {
    const [t] = useTranslation();
    const { container, status } = useAppPanel(props);
    return (
        <div className="flex h-full min-h-0 flex-col" role="region" aria-label={props.app.panel?.name ?? props.app.name}>
            <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
                <span className="truncate text-sm font-medium">{props.app.panel?.name ?? props.app.name}</span>
                <Button size="icon" variant="ghost" onClick={props.onClose} aria-label={t("project.Close App panel")}>
                    ×
                </Button>
            </div>
            {status === "loading" && (
                <p className="p-3 text-sm" role="status">
                    {t("common.Loading...")}
                </p>
            )}
            {status === "error" && (
                <p className="p-3 text-sm" role="alert">
                    {t("project.App panel unavailable")}
                </p>
            )}
            <div ref={container} className="min-h-0 flex-1" />
        </div>
    );
}
