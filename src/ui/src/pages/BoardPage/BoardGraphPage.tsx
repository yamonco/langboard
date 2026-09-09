import "@xyflow/react/dist/style.css";

import { Background, Controls, Edge, Handle, MarkerType, MiniMap, Node, NodeProps, Position, ReactFlow, ReactFlowInstance } from "@xyflow/react";
import Button from "@/components/base/Button";
import useGetCards from "@/controllers/api/board/useGetCards";
import { GlobalRelationshipType, ProjectCard, ProjectColumn } from "@/core/models";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";
import { IBoardRelatedPageProps } from "@/pages/BoardPage/types";
import { GRAPH_CARD_HEIGHT, GRAPH_CARD_WIDTH, GRAPH_DEFAULT_VIEWPORT, GRAPH_LANE_WIDTH, layoutBoardGraph } from "@/pages/BoardPage/BoardGraphLayout";
import { lazy, Suspense, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/core/utils/ComponentUtils";
import { useAuth } from "@/core/providers/AuthProvider";
import useUserSettingsStore, { getUserSettingsStore, useUserSettings } from "@/core/stores/UserSettingsStore";
import { boardGraphViewForUser, TBoardGraphView } from "@/pages/BoardPage/BoardGraphPreference";

const BoardNetworkGraph = lazy(() => import("@/pages/BoardPage/BoardNetworkGraph"));

type TCardNode = Node<{ title: string; column: string; onOpen: () => void; onFocus: () => void; onBlur: () => void }, "card">;

function GraphCard({ data }: NodeProps<TCardNode>) {
    return (
        <div className="size-full rounded-xl border bg-card text-card-foreground shadow-sm hover:border-primary">
            <button
                type="button"
                className={cn(
                    "nodrag nopan flex size-full items-center rounded-xl px-4 py-3 text-left",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                )}
                aria-label={`${data.title} · ${data.column}`}
                onClick={data.onOpen}
                onFocus={data.onFocus}
                onBlur={data.onBlur}
            >
                <span className="line-clamp-3 break-words text-sm font-medium leading-5" title={data.title}>
                    {data.title}
                </span>
            </button>
            {[Position.Left, Position.Right].map((position) => (
                <span key={position}>
                    <Handle type="source" id={`source-${position}`} position={position} isConnectable={false} />
                    <Handle type="target" id={`target-${position}`} position={position} isConnectable={false} />
                </span>
            ))}
        </div>
    );
}

function GraphLane({ data }: NodeProps<Node<{ name: string; count: number }, "lane">>) {
    return (
        <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
            <span className="truncate text-sm font-semibold text-foreground">{data.name}</span>
            <span className="rounded-md bg-background px-2 py-0.5 text-xs text-muted-foreground">{data.count}</span>
        </div>
    );
}

const nodeTypes = { card: GraphCard, lane: GraphLane };

const BoardGraphPage = ({ project }: IBoardRelatedPageProps): React.JSX.Element => {
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const { currentUser } = useAuth();
    const savedViews = useUserSettings("graph_view_modes");
    const view = boardGraphViewForUser(savedViews, currentUser?.uid ?? "");
    const updateSettingsByKey = useUserSettingsStore((store) => store.updateSettingsByKey);
    const setView = (next: TBoardGraphView) => {
        if (currentUser) updateSettingsByKey("graph_view_modes", { ...getUserSettingsStore().settings.graph_view_modes, [currentUser.uid]: next });
    };
    const [focusColumn, setFocusColumn] = useState<string>();
    const { data, isError, refetch } = useGetCards({ project_uid: project.uid });
    const cards = ProjectCard.Model.useModels((card) => card.project_uid === project.uid, [project, data]);
    const columns = ProjectColumn.Model.useModels((column) => column.project_uid === project.uid, [project, data]);
    const relationshipTypes = GlobalRelationshipType.Model.useModels(() => true, []);
    const [includeArchive, setIncludeArchive] = useState(false);
    const [showUnlinked, setShowUnlinked] = useState(false);
    const [activeCard, setActiveCard] = useState<string>();
    const flowRef = useRef<ReactFlowInstance | null>(null);
    const layout = useMemo(() => layoutBoardGraph(cards, columns, { includeArchive, showUnlinked }), [cards, columns, includeArchive, showUnlinked]);

    const nodes = useMemo<Node[]>(
        () => [
            ...layout.lanes.map(({ column, x, height, cards: laneCards }) => ({
                id: `column:${column.uid}`,
                type: "lane",
                position: { x, y: 0 },
                data: { name: column.name, count: laneCards.length },
                style: {
                    width: GRAPH_LANE_WIDTH,
                    height,
                    borderRadius: 16,
                    background: "hsl(var(--muted) / 0.25)",
                    border: "1px solid hsl(var(--border))",
                },
                selectable: false,
                focusable: false,
                zIndex: -1,
            })),
            ...layout.lanes.flatMap(({ column, cards: laneCards }) =>
                laneCards.map(({ card, y }) => ({
                    id: card.uid,
                    type: "card",
                    parentId: `column:${column.uid}`,
                    extent: "parent" as const,
                    position: { x: (GRAPH_LANE_WIDTH - GRAPH_CARD_WIDTH) / 2, y },
                    data: {
                        title: card.title,
                        column: column.name,
                        onOpen: () => navigate(ROUTES.BOARD.CARD(project.uid, card.uid)),
                        onFocus: () => setActiveCard(card.uid),
                        onBlur: () => setActiveCard(undefined),
                    },
                    style: { width: GRAPH_CARD_WIDTH, height: GRAPH_CARD_HEIGHT },
                    focusable: false,
                    zIndex: 1,
                }))
            ),
        ],
        [layout, navigate, project.uid]
    );
    const edges = useMemo<Edge[]>(() => {
        const names = new Map(relationshipTypes.map((type) => [type.uid, type.child_name]));
        return layout.edges.map(({ typeUID, ...edge }) => {
            const emphasized = edge.source === activeCard || edge.target === activeCard;
            return {
                ...edge,
                label: emphasized ? names.get(typeUID) : undefined,
                type: "default",
                markerEnd: { type: MarkerType.ArrowClosed, color: "hsl(var(--primary))" },
                style: { stroke: "hsl(var(--primary))", strokeWidth: emphasized ? 2.5 : 1.5, opacity: activeCard && !emphasized ? 0.12 : 0.65 },
                labelStyle: { fill: "hsl(var(--foreground))", fontSize: 12 },
                labelBgStyle: { fill: "hsl(var(--background))" },
                zIndex: emphasized ? 2 : 0,
                focusable: false,
                selectable: false,
            };
        });
    }, [layout.edges, relationshipTypes, activeCard]);

    const showColumn = (x: number) => {
        const duration = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 200;
        void flowRef.current?.setViewport({ ...GRAPH_DEFAULT_VIEWPORT, x: GRAPH_DEFAULT_VIEWPORT.x - x }, { duration });
    };

    if (isError) {
        return (
            <div className="flex size-full flex-col items-center justify-center gap-3">
                <p>{t("board.Graph could not be loaded.")}</p>
                <Button onClick={() => void refetch()}>{t("common.Retry")}</Button>
            </div>
        );
    }
    if (!data) return <div className="size-full animate-pulse bg-muted/30" />;

    return (
        <div className="flex size-full flex-col bg-background pb-16">
            <div className="shrink-0 space-y-2 border-b bg-background px-3 py-3 md:px-5">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                    <div className="mr-auto">
                        <h1 className="text-sm font-semibold">{t("board.Relationship graph")}</h1>
                        <p className="text-xs text-muted-foreground">
                            {t("board.{cards} cards, {relationships} relationships", { cards: layout.cardCount, relationships: edges.length })}
                        </p>
                    </div>
                    <div role="group" aria-label={t("board.Graph view")} className="flex rounded-lg border p-0.5">
                        <Button
                            size="sm"
                            variant={view === "columns" ? "secondary" : "ghost"}
                            aria-pressed={view === "columns"}
                            onClick={() => setView("columns")}
                        >
                            {t("board.Columns")}
                        </Button>
                        <Button
                            size="sm"
                            variant={view === "network" ? "secondary" : "ghost"}
                            aria-pressed={view === "network"}
                            onClick={() => setView("network")}
                        >
                            {t("board.Network")}
                        </Button>
                    </div>
                    <Button
                        size="sm"
                        variant={showUnlinked ? "default" : "outline"}
                        aria-pressed={showUnlinked}
                        onClick={() => setShowUnlinked(!showUnlinked)}
                    >
                        {t("board.Show unlinked cards")}
                    </Button>
                    <Button
                        size="sm"
                        variant={includeArchive ? "default" : "outline"}
                        aria-pressed={includeArchive}
                        onClick={() => setIncludeArchive(!includeArchive)}
                    >
                        {t("board.Include archive")}
                    </Button>
                </div>
                <nav aria-label={t("board.Columns")} className="flex gap-1 overflow-x-auto pb-1">
                    {layout.lanes.map(({ column, x, cards: laneCards }) => (
                        <Button
                            key={column.uid}
                            size="sm"
                            variant="ghost"
                            className="shrink-0 gap-2"
                            onClick={() => (view === "columns" ? showColumn(x) : setFocusColumn(column.uid))}
                        >
                            {column.name}
                            <span className="text-xs text-muted-foreground">{laneCards.length}</span>
                        </Button>
                    ))}
                </nav>
            </div>
            <div className="relative min-h-0 flex-1">
                {!layout.cardCount && (
                    <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center px-6">
                        <p className="rounded-xl border bg-card p-4 text-center text-sm text-muted-foreground">
                            {t("board.No related cards in this view.")}
                        </p>
                    </div>
                )}
                {view === "network" ? (
                    <Suspense fallback={<div className="size-full animate-pulse bg-muted/30" />}>
                        <BoardNetworkGraph
                            layout={layout}
                            focusColumn={focusColumn}
                            onOpen={(uid) => navigate(ROUTES.BOARD.CARD(project.uid, uid))}
                        />
                    </Suspense>
                ) : (
                    <ReactFlow
                        nodes={nodes}
                        edges={edges}
                        nodeTypes={nodeTypes}
                        onInit={(instance) => {
                            flowRef.current = instance;
                        }}
                        defaultViewport={GRAPH_DEFAULT_VIEWPORT}
                        minZoom={0.5}
                        maxZoom={1.5}
                        nodesDraggable={false}
                        nodesConnectable={false}
                        edgesFocusable={false}
                        deleteKeyCode={null}
                        onlyRenderVisibleElements
                        onNodeMouseEnter={(_event, node) => setActiveCard(node.type === "card" ? node.id : undefined)}
                        onNodeMouseLeave={() => setActiveCard(undefined)}
                        proOptions={{ hideAttribution: true }}
                    >
                        <Background gap={24} size={1} color="hsl(var(--border))" />
                        <Controls showInteractive={false} showFitView={false} />
                        <MiniMap
                            className="hidden md:block"
                            style={{ background: "hsl(var(--background))", height: 100, width: 160 }}
                            nodeColor="hsl(var(--muted-foreground))"
                            maskColor="hsl(var(--muted) / 0.6)"
                            pannable
                            zoomable
                        />
                    </ReactFlow>
                )}
            </div>
        </div>
    );
};

export default BoardGraphPage;
