/**
 * 마크다운 직렬화 결과를 구조화 블록으로 분해 — 에디터 저장(Phase 2) 파서.
 *
 * Plate 직렬화 규약을 그대로 재사용한다:
 * - fenced code block → code 블록 (language + source)
 * - $$<Engine> ... $$ math 블록(meta에 drawingType) → diagram 블록
 * - 나머지 연속 텍스트 → rich_text 블록 (원래 순서 보존)
 */

export interface ISerializedBlock {
    block_type: "rich_text" | "code" | "diagram";
    payload: Record<string, unknown>;
}

const ENGINE_VALUES = new Set(["mermaid", "plantuml", "graphviz", "flowchart"]);
const ENGINE_ALIASES: Record<string, string> = {
    Mermaid: "mermaid",
    PlantUml: "plantuml",
    Graphviz: "graphviz",
    Flowchart: "flowchart",
};

const FENCED_CODE = /```([\w+#.-]*)[ \t]*\n([\s\S]*?)```/g;
const CODE_DRAWING = /\$\$(Mermaid|PlantUml|Graphviz|Flowchart)\b([^\n]*)\n([\s\S]*?)\$\$/g;

function normalizeEngine(token: string | undefined): string | null {
    if (!token) return null;
    const direct = token.trim();
    if (ENGINE_VALUES.has(direct.toLowerCase())) return direct.toLowerCase();
    return ENGINE_ALIASES[direct] ?? null;
}

/**
 * 직렬화된 마크다운에서 code/diagram 세그먼트를 순서대로 추출해
 * 블록 리스트로 만든다. code/diagram가 하나도 없으면 빈 배열을
 * 돌려줘 호출자가 블록 동기화를 건너뛰게 한다.
 */
export function extractContentBlocks(markdown: string): ISerializedBlock[] {
    const segments: Array<{ kind: "text" | "code" | "diagram"; start: number; end: number; block: ISerializedBlock }> = [];

    for (const match of markdown.matchAll(FENCED_CODE)) {
        const language = (match[1] || "text").trim() || "text";
        const source = match[2] ?? "";
        segments.push({
            kind: "code",
            start: match.index ?? 0,
            end: (match.index ?? 0) + match[0].length,
            block: { block_type: "code", payload: { language, source } },
        });
    }

    for (const match of markdown.matchAll(CODE_DRAWING)) {
        const engine = normalizeEngine(match[1]);
        if (!engine) continue;
        const metaTail = (match[2] || "").trim();
        const source = match[3] ?? "";
        const viewMode = metaEngineViewMode(metaTail) ?? "both";
        segments.push({
            kind: "diagram",
            start: match.index ?? 0,
            end: (match.index ?? 0) + match[0].length,
            block: { block_type: "diagram", payload: { engine, source, view_mode: viewMode } },
        });
    }

    if (!segments.length) return [];

    segments.sort((a, b) => a.start - b.start);

    const blocks: ISerializedBlock[] = [];
    let cursor = 0;
    for (const segment of segments) {
        if (segment.start < cursor) continue; // 겹침(코드펜스 내부의 $$ 등)은 먼저 잡힌 것 우선
        const text = markdown
            .slice(cursor, segment.start)
            .replace(/\n{3,}/g, "\n\n")
            .trim();
        if (text) {
            blocks.push({ block_type: "rich_text", payload: { text } });
        }
        blocks.push(segment.block);
        cursor = segment.end;
    }
    const tail = markdown.slice(cursor).trim();
    if (tail) {
        blocks.push({ block_type: "rich_text", payload: { text: tail } });
    }
    return blocks;
}

function metaEngineViewMode(meta: string): string | null {
    if (!meta) return null;
    if (/mode=["']?code/i.test(meta)) return "code";
    if (/mode=["']?image/i.test(meta) || /mode=["']?rendered/i.test(meta)) return "image";
    if (/mode=["']?both/i.test(meta)) return "both";
    return null;
}
