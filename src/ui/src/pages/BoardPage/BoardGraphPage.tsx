import "@xyflow/react/dist/style.css";

import dagre from "@dagrejs/dagre";
import { Background, Controls, Edge, MarkerType, MiniMap, Node, Position, ReactFlow } from "@xyflow/react";
import useGetCards from "@/controllers/api/board/useGetCards";
import { GlobalRelationshipType, ProjectCard, ProjectColumn } from "@/core/models";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";
import { IBoardRelatedPageProps } from "@/pages/BoardPage/types";
import { ScreenMap } from "@/core/utils/VariantUtils";
import useResizeEvent from "@/core/hooks/useResizeEvent";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

const NODE_WIDTH = 260;
const NODE_HEIGHT = 84;

type TLayoutDirection = "LR" | "TB";

const layoutGraph = (nodes: Node[], edges: Edge[], direction: TLayoutDirection): Node[] => {
    const graph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
    graph.setGraph({ rankdir: direction, nodesep: 36, ranksep: 72, marginx: 24, marginy: 24 });

    nodes.forEach((node) => graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT }));
    edges.forEach((edge) => graph.setEdge(edge.source, edge.target));
    dagre.layout(graph);

    return nodes.map((node) => {
        const position = graph.node(node.id);
        return {
            ...node,
            sourcePosition: direction === "LR" ? Position.Right : Position.Bottom,
            targetPosition: direction === "LR" ? Position.Left : Position.Top,
            position: {
                x: position.x - NODE_WIDTH / 2,
                y: position.y - NODE_HEIGHT / 2,
            },
        };
    });
};

const BoardGraphPage = ({ project }: IBoardRelatedPageProps): React.JSX.Element => {
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const { data } = useGetCards({ project_uid: project.uid });
    const [direction, setDirection] = useState<TLayoutDirection>(window.innerWidth < ScreenMap.size.md ? "TB" : "LR");
    const cards = ProjectCard.Model.useModels((card) => card.project_uid === project.uid, [project, data]);

    useResizeEvent(
        {
            doneCallback: () => setDirection(window.innerWidth < ScreenMap.size.md ? "TB" : "LR"),
        },
        [setDirection]
    );

    const { edges, nodes, relationshipCount } = useMemo(() => {
        const cardUIDs = new Set(cards.map((card) => card.uid));
        const seenRelationships = new Set<string>();
        const graphEdges: Edge[] = [];

        cards.forEach((card) => {
            card.relationships.forEach((relationship) => {
                if (!cardUIDs.has(relationship.parent_card_uid) || !cardUIDs.has(relationship.child_card_uid)) {
                    return;
                }

                const key = `${relationship.relationship_type_uid}:${relationship.parent_card_uid}:${relationship.child_card_uid}`;
                if (seenRelationships.has(key)) {
                    return;
                }
                seenRelationships.add(key);

                const relationshipType = GlobalRelationshipType.Model.getModel(relationship.relationship_type_uid);
                graphEdges.push({
                    id: key,
                    source: relationship.parent_card_uid,
                    target: relationship.child_card_uid,
                    label: relationshipType?.child_name,
                    markerEnd: { type: MarkerType.ArrowClosed },
                    type: "smoothstep",
                });
            });
        });

        const graphNodes: Node[] = cards.map((card) => {
            const column = ProjectColumn.Model.getModel(card.project_column_uid);
            return {
                id: card.uid,
                data: {
                    label: (
                        <div className="min-w-0 text-left">
                            <div className="truncate text-xs text-muted-foreground">{column?.name ?? card.project_column_name}</div>
                            <div className="mt-1 line-clamp-2 font-semibold text-foreground">{card.title}</div>
                        </div>
                    ),
                },
                position: { x: 0, y: 0 },
                style: {
                    width: NODE_WIDTH,
                    minHeight: NODE_HEIGHT,
                    borderRadius: 12,
                    border: "1px solid hsl(var(--border))",
                    background: "hsl(var(--card))",
                    padding: 14,
                },
            };
        });

        return {
            edges: graphEdges,
            nodes: layoutGraph(graphNodes, graphEdges, direction),
            relationshipCount: graphEdges.length,
        };
    }, [cards, direction]);

    if (!data) {
        return <div className="size-full animate-pulse bg-muted/30" />;
    }

    return (
        <div className="relative size-full bg-background">
            <div className="pointer-events-none absolute left-4 top-4 z-10 rounded-xl border bg-card/90 px-3 py-2 shadow-sm backdrop-blur">
                <div className="text-sm font-semibold">{t("board.Relationship graph")}</div>
                <div className="text-xs text-muted-foreground">
                    {t("board.{cards} cards, {relationships} relationships", {
                        cards: cards.length,
                        relationships: relationshipCount,
                    })}
                </div>
            </div>
            <ReactFlow
                nodes={nodes}
                edges={edges}
                nodesDraggable={false}
                nodesConnectable={false}
                elementsSelectable
                fitView
                fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }}
                minZoom={0.1}
                onNodeClick={(_event, node) => navigate(ROUTES.BOARD.CARD(project.uid, node.id))}
                proOptions={{ hideAttribution: true }}
            >
                <Background gap={24} size={1} />
                <Controls showInteractive={false} />
                <MiniMap className="hidden md:block" pannable zoomable />
            </ReactFlow>
        </div>
    );
};

export default BoardGraphPage;
