import ForceGraph2D, { ForceGraphMethods, LinkObject, NodeObject } from "react-force-graph-2d";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "next-themes";
import { useTranslation } from "react-i18next";
import Button from "@/components/base/Button";
import { cn } from "@/core/utils/ComponentUtils";
import { layoutBoardGraph, networkBoardGraph } from "@/pages/BoardPage/BoardGraphLayout";

type TDot = ReturnType<typeof networkBoardGraph>["nodes"][number];
type TDotNode = NodeObject<TDot>;
type TDotLink = LinkObject<TDot, { id: string }>;

interface IBoardNetworkGraphProps {
    layout: ReturnType<typeof layoutBoardGraph>;
    focusColumn?: { uid: string };
    onOpen: (cardUID: string) => void;
}

const endpointUID = (node: string | number | TDotNode | undefined) => (typeof node === "object" ? node.id : node);

function BoardNetworkGraph({ layout, focusColumn, onOpen }: IBoardNetworkGraphProps) {
    const [t] = useTranslation();
    const { resolvedTheme } = useTheme();
    const containerRef = useRef<HTMLDivElement>(null);
    const graphRef = useRef<ForceGraphMethods<TDot, { id: string }> | undefined>(undefined);
    const didFit = useRef(false);
    const [size, setSize] = useState({ width: 0, height: 0 });
    const [selectedUID, setSelectedUID] = useState<string>();
    const [hoveredUID, setHoveredUID] = useState<string>();
    const [colors, setColors] = useState({ background: "transparent", foreground: "#999", muted: "#666", primary: "#999", hue: 260 });
    const graph = useMemo(() => networkBoardGraph(layout), [layout]);
    const selected = graph.nodes.find((node) => node.id === selectedUID);
    const activeUID = hoveredUID ?? selectedUID;
    const neighbors = useMemo(() => {
        const result = new Set([activeUID]);
        for (const edge of layout.edges) {
            if (edge.source === activeUID) result.add(edge.target);
            if (edge.target === activeUID) result.add(edge.source);
        }
        return result;
    }, [layout.edges, activeUID]);
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;
        const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
        observer.observe(container);
        return () => observer.disconnect();
    }, []);
    useEffect(() => {
        const frame = requestAnimationFrame(() => {
            const style = getComputedStyle(document.documentElement);
            const color = (name: string) => `hsl(${style.getPropertyValue(`--${name}`).trim()})`;
            setColors({
                background: color("background"),
                foreground: color("foreground"),
                muted: color("muted-foreground"),
                primary: color("primary"),
                hue: Number.parseFloat(style.getPropertyValue("--primary")) || 260,
            });
        });
        return () => cancelAnimationFrame(frame);
    }, [resolvedTheme]);
    useEffect(() => {
        didFit.current = false;
        setSelectedUID(undefined);
        setHoveredUID(undefined);
    }, [graph]);
    useEffect(() => {
        if (focusColumn) graphRef.current?.zoomToFit(reducedMotion ? 0 : 200, 64, (node) => node.columnUID === focusColumn.uid);
    }, [focusColumn, reducedMotion]);

    const nodeColor = (node: TDotNode) => `hsl(${(colors.hue + node.columnIndex * 32) % 360} 62% ${resolvedTheme === "dark" ? 68 : 42}%)`;
    const activeLink = (link: TDotLink) => endpointUID(link.source) === activeUID || endpointUID(link.target) === activeUID;

    return (
        <div ref={containerRef} className="relative size-full overflow-hidden">
            {size.width > 0 && size.height > 0 && (
                <ForceGraph2D<TDot, { id: string }>
                    ref={graphRef}
                    graphData={graph}
                    width={size.width}
                    height={size.height}
                    backgroundColor={colors.background}
                    nodeLabel={() => ""}
                    linkLabel={() => ""}
                    nodeColor={(node) => (activeUID && !neighbors.has(node.id) ? colors.muted : nodeColor(node))}
                    nodeVal={(node) => 1 + Math.min(node.degree, 8)}
                    nodeRelSize={4}
                    linkColor={(link) => (activeUID && activeLink(link) ? colors.primary : colors.muted)}
                    linkWidth={(link) => (activeUID && activeLink(link) ? 2 : 0.6)}
                    linkDirectionalArrowLength={(link) => (activeUID && activeLink(link) ? 4 : 0)}
                    minZoom={0.25}
                    maxZoom={2.5}
                    warmupTicks={reducedMotion ? 160 : 60}
                    cooldownTicks={reducedMotion ? 0 : 100}
                    autoPauseRedraw
                    enableNodeDrag={false}
                    onNodeHover={(node) => setHoveredUID(node?.id)}
                    onNodeClick={(node) => setSelectedUID(node.id)}
                    onBackgroundClick={() => setSelectedUID(undefined)}
                    onEngineStop={() => {
                        if (!didFit.current) {
                            graphRef.current?.zoomToFit(0, 70);
                            didFit.current = true;
                        }
                    }}
                    nodeCanvasObjectMode={() => "after"}
                    nodeCanvasObject={(node, context, scale) => {
                        const active = node.id === activeUID;
                        // Keep a selected neighborhood legible instead of stacking its long titles.
                        if (!active && (activeUID || scale < 1.8 || node.degree < 2)) return;
                        const label = node.title.length > 24 ? `${node.title.slice(0, 23)}…` : node.title;
                        const fontSize = (active ? 12 : 10) / scale;
                        context.font = `${active ? 600 : 400} ${fontSize}px sans-serif`;
                        context.textAlign = "center";
                        context.textBaseline = "top";
                        context.lineWidth = 4 / scale;
                        context.strokeStyle = colors.background;
                        context.fillStyle = colors.foreground;
                        context.strokeText(label, node.x ?? 0, (node.y ?? 0) + 10 / scale);
                        context.fillText(label, node.x ?? 0, (node.y ?? 0) + 10 / scale);
                    }}
                    nodePointerAreaPaint={(node, color, context, scale) => {
                        context.fillStyle = color;
                        context.beginPath();
                        context.arc(node.x ?? 0, node.y ?? 0, Math.max(4 * Math.sqrt(1 + Math.min(node.degree, 8)), 22 / scale), 0, 2 * Math.PI);
                        context.fill();
                    }}
                />
            )}
            <div className="absolute left-3 top-3 flex max-w-[calc(100%-1.5rem)] gap-2">
                <select
                    aria-label={t("board.Find a card")}
                    className="h-10 min-w-0 max-w-64 rounded-lg border bg-background px-3 text-sm"
                    value={selectedUID ?? ""}
                    onChange={(event) => {
                        setSelectedUID(event.target.value || undefined);
                        const node = graph.nodes.find((item) => item.id === event.target.value) as TDotNode | undefined;
                        if (node) graphRef.current?.centerAt(node.x, node.y, reducedMotion ? 0 : 200);
                    }}
                >
                    <option value="">{t("board.Find a card")}</option>
                    {graph.nodes.map((node) => (
                        <option key={node.id} value={node.id}>
                            {node.title} · {node.column}
                        </option>
                    ))}
                </select>
                <Button variant="outline" onClick={() => graphRef.current?.zoomToFit(reducedMotion ? 0 : 200, 70)}>
                    {t("board.Overview")}
                </Button>
            </div>
            {selected && (
                <div
                    className={cn(
                        "absolute bottom-3 left-3 right-3 flex items-center gap-3 rounded-xl border bg-card/95 p-3 shadow-lg",
                        "md:right-auto md:max-w-md"
                    )}
                >
                    <div className="min-w-0 flex-1">
                        <p className="text-xs text-muted-foreground">{selected.column}</p>
                        <p className="line-clamp-2 text-sm font-medium">{selected.title}</p>
                    </div>
                    <Button size="sm" onClick={() => onOpen(selected.id)}>
                        {t("board.Open card")}
                    </Button>
                </div>
            )}
        </div>
    );
}

export default BoardNetworkGraph;
