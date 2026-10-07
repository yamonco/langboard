import { API_URL } from "@/constants";
import { api } from "@/core/helpers/Api";
import useAuthStore, { getAuthStore } from "@/core/stores/AuthStore";
import { useEffect, useState } from "react";

/** Only native attachment URLs may receive our authenticated API transport. */
export function protectedImagePath(src: string | undefined): string | null {
    if (!src) return null;
    try {
        const root = new URL(API_URL, window.location.origin);
        const url = new URL(src, root);
        const prefix = root.pathname.replace(/\/$/, "");
        if (url.origin !== root.origin || url.username || url.password || url.search || url.hash) return null;
        const path = url.pathname;
        if (!path.startsWith(`${prefix}/file/`)) return null;
        const segments = path.slice(prefix.length).split("/").map(decodeURIComponent);
        if (segments.length !== 5 || segments[3] !== "card_attachment") return null;
        return path.slice(prefix.length);
    } catch {
        return null;
    }
}

export default function useProtectedImage(src: string | undefined) {
    const path = protectedImagePath(src);
    const session = useAuthStore((store) => store.getSessionVersion());
    const [loaded, setLoaded] = useState<{ src: string; session: number; url: string } | null>(null);
    useEffect(() => {
        if (!path || !src) return;
        const controller = new AbortController();
        let objectUrl: string | undefined;
        let disposed = false;
        api.get<Blob>(path, { responseType: "blob", signal: controller.signal, env: { interceptToast: false } as never })
            .then(({ data }) => {
                if (disposed || session !== getAuthStore().getSessionVersion()) return;
                objectUrl = URL.createObjectURL(data);
                setLoaded({ src, session, url: objectUrl });
            })
            .catch(() => {
                if (!disposed) setLoaded(null);
            });
        return () => {
            disposed = true;
            controller.abort();
            if (objectUrl) URL.revokeObjectURL(objectUrl);
        };
    }, [src, path, session]);
    return { protected: path !== null, src: path ? (loaded && loaded.src === src && loaded.session === session ? loaded.url : undefined) : src };
}
