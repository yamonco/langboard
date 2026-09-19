import assert from "node:assert/strict";
import { extractContentBlocks } from "./contentBlockSerializer.ts";

// fenced code → code 블록
const code = extractContentBlocks("설명입니다\n\n```python\nprint('hi')\n```\n\n끝");
assert.deepEqual(
    code.map((b) => b.block_type),
    ["rich_text", "code", "rich_text"]
);
assert.equal(code[1].payload.language, "python");
assert.equal(code[1].payload.source, "print('hi')\n");
assert.ok(String(code[0].payload.text).includes("설명입니다"));

// $$Mermaid → diagram 블록 (엔진 정규화)
const diagram = extractContentBlocks("$$Mermaid\ngraph TD; A-->B\n$$");
assert.equal(diagram.length, 1);
assert.equal(diagram[0].block_type, "diagram");
assert.equal(diagram[0].payload.engine, "mermaid");
assert.equal(diagram[0].payload.view_mode, "both");

// 코드펜스 내부의 $$는 코드로 유지 (겹침 방지)
const inner = extractContentBlocks("```\n$$Mermaid\nfake\n$$\n```");
assert.equal(inner.length, 1);
assert.equal(inner[0].block_type, "code");

// 코드/다이어그램 없으면 빈 배열 (동기화 스킵 신호)
assert.equal(extractContentBlocks("그냥 텍스트만").length, 0);

console.log("contentBlockSerializer tests pass");
