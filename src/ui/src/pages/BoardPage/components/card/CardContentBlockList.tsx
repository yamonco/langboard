import { memo, useEffect, useRef, useState } from "react";
import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import { canRenderDiagram, renderDiagram } from "@/core/helpers/CodeDrawingRenderer";
import type { CodeDrawingType } from "@platejs/code-drawing";
import type { IContentBlock } from "@/core/models/ProjectCard";

type TEngine = "mermaid" | "plantuml" | "graphviz" | "flowchart";

const ENGINE_BY_VALUE: Record<TEngine, CodeDrawingType> = {
    mermaid: "Mermaid",
    plantuml: "PlantUml",
    graphviz: "Graphviz",
    flowchart: "Flowchart",
};

function asString(value: unknown, fallback = ""): string {
    return typeof value === "string" ? value : fallback;
}

const DiagramBlockBody = memo(function DiagramBlockBody({ engine, source }: { engine: TEngine; source: string }) {
    const [image, setImage] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const lastRequestRef = useRef(0);

    useEffect(() => {
        const requestId = ++lastRequestRef.current;
        const drawingType = ENGINE_BY_VALUE[engine] ?? "Mermaid";
        if (!source.trim() || !canRenderDiagram(drawingType, source)) {
            setImage("");
            setError(null);
            setLoading(false);
            return;
        }
        setLoading(true);
        renderDiagram(drawingType, source)
            .then((imageData) => {
                if (lastRequestRef.current !== requestId) return;
                setImage(imageData);
                setError(null);
            })
            .catch((err: unknown) => {
                if (lastRequestRef.current !== requestId) return;
                setError(err instanceof Error ? err.message : "Rendering failed");
                setImage("");
            })
            .finally(() => {
                if (lastRequestRef.current === requestId) setLoading(false);
            });
    }, [engine, source]);

    if (loading) return <Box className="h-32 animate-pulse rounded-lg bg-secondary/60" />;
    if (error) {
        return (
            <Box className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                {engine} 다이어그램을 렌더링하지 못했습니다: {error}
            </Box>
        );
    }
    if (!image) {
        return (
            <Box className="rounded-lg border border-dashed px-3 py-2 text-xs text-muted-foreground">
                {engine} 다이어그램 미리보기를 사용할 수 없습니다
            </Box>
        );
    }
    return (
        <div className="flex justify-center overflow-x-auto">
            <img src={image} alt={`${engine} diagram`} className="max-w-full" />
        </div>
    );
});

function CodeBlock({ block }: { block: IContentBlock }) {
    const language = asString(block.payload.language, "text");
    const source = asString(block.payload.source);
    const title = asString(block.payload.title);
    return (
        <Box className="overflow-hidden rounded-lg border">
            <Flex items="center" justify="between" className="border-b bg-secondary/60 px-3 py-1.5">
                <Flex items="center" gap="1.5" className="min-w-0 text-xs text-muted-foreground">
                    <IconComponent icon="file-text" size="3.5" />
                    <span className="truncate font-mono">{title || language}</span>
                </Flex>
                <span className="shrink-0 rounded bg-background px-1.5 py-0.5 font-mono text-[10px] uppercase">{language}</span>
            </Flex>
            <Box className="overflow-x-auto">
                <pre className="p-3 font-mono text-xs leading-relaxed">
                    <code>{source}</code>
                </pre>
            </Box>
        </Box>
    );
}

function DiagramBlock({ block }: { block: IContentBlock }) {
    const engine = (asString(block.payload.engine, "mermaid") as TEngine) ?? "mermaid";
    const source = asString(block.payload.source);
    const rawMode = asString(block.payload.view_mode, "both");
    const viewMode = rawMode === "code" || rawMode === "source" ? "source" : rawMode === "image" || rawMode === "rendered" ? "rendered" : "both";
    const showCode = viewMode === "source" || viewMode === "both";
    const showDiagram = viewMode === "rendered" || viewMode === "both";
    return (
        <Box className="rounded-lg border p-3">
            {showDiagram ? (
                <Box className="mb-2">
                    <DiagramBlockBody engine={engine} source={source} />
                </Box>
            ) : null}
            {showCode ? (
                <details open={!showDiagram}>
                    <summary className="cursor-pointer select-none text-xs text-muted-foreground">{engine} source</summary>
                    <pre className="mt-2 overflow-x-auto rounded bg-secondary/50 p-2 font-mono text-xs leading-relaxed">
                        <code>{source}</code>
                    </pre>
                </details>
            ) : null}
        </Box>
    );
}

function RichTextBlock({ block }: { block: IContentBlock }) {
    const text = asString(block.payload.text) || asString(block.payload.content);
    if (!text) return null;
    return <Box className="whitespace-pre-wrap break-words text-sm leading-relaxed">{text}</Box>;
}

function BlockDispatch({ block }: { block: IContentBlock }) {
    if (block.type === "code") return <CodeBlock block={block} />;
    if (block.type === "diagram") return <DiagramBlock block={block} />;
    return <RichTextBlock block={block} />;
}

/**
 * 순서 보존 구조화 블록 렌더러 — 블록별 격리된 fallback.
 * code.source는 리터럴 데이터로만 출력하고 diagram.source는 rich-text 렌더러를
 * 거치지 않으며, 렌더 실패는 해당 블록 내부 오류로 국한된다.
 */
function CardContentBlockList({ blocks }: { blocks: IContentBlock[] }): React.JSX.Element | null {
    if (!blocks.length) return null;
    const ordered = [...blocks].sort((a, b) => a.order - b.order);
    return (
        <Flex direction="col" gap="3" data-card-content-blocks>
            {ordered.map((block) => (
                <Box key={block.block_uid} data-card-block-uid={block.block_uid}>
                    <BlockDispatch block={block} />
                </Box>
            ))}
        </Flex>
    );
}

export default memo(CardContentBlockList);
