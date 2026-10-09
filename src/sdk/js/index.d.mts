export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type PanelState = { [key: string]: JsonValue };
export interface PanelContext { project_uid: string; app_key: string; app_version: string; language: string; }
export const PANEL_DESIGN_TOKENS: readonly string[];
export interface PanelAppearance { mode: "light" | "dark"; tokens: Record<string, string>; }
export interface PanelDesign extends PanelAppearance { resources?: { module_url: string; css_url: string }; }
export interface PanelHostDispose { (): void; updateDesign(design: PanelAppearance): void; }
export interface PanelSession {
    context: PanelContext;
    state: PanelState | null;
    design: PanelDesign | null;
    widgets: Promise<Record<string, unknown> | null>;
    signal: AbortSignal;
    saveState(state: PanelState): void;
    close(): void;
    dispose(): void;
}
export function createPanelHost(options: {
    frame: HTMLIFrameElement;
    context: PanelContext;
    state?: PanelState | null;
    design?: PanelDesign;
    onState?: (state: PanelState) => void;
    onReady?: () => void;
    onClose?: () => void;
    onError?: (error: unknown) => void;
}): PanelHostDispose;
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
