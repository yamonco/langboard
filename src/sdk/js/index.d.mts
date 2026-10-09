export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type PanelState = { [key: string]: JsonValue };
export interface PanelContext { project_uid: string; app_key: string; app_version: string; language: string; }
export interface PanelSession {
    context: PanelContext;
    state: PanelState | null;
    signal: AbortSignal;
    saveState(state: PanelState): void;
    close(): void;
    dispose(): void;
}
export function createPanelHost(options: {
    frame: HTMLIFrameElement;
    context: PanelContext;
    state?: PanelState | null;
    onState?: (state: PanelState) => void;
    onReady?: () => void;
    onClose?: () => void;
    onError?: (error: unknown) => void;
}): () => void;
export function connectPanel(options: {
    expectedHostOrigin: string;
    onShow?: (session: PanelSession) => void;
    onDispose?: () => void;
}): Promise<PanelSession>;
export class PanelStateCache {
    get(key: string): PanelState | null;
    set(key: string, state: PanelState): void;
    delete(key: string): boolean;
    clear(): void;
}
