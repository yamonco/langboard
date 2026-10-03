"use client";

import { CODE_DRAWING_TYPE_ARRAY, CodeDrawingType, VIEW_MODE } from "@platejs/code-drawing";
import { createBlockStartInputRule, createSlatePlugin, createTextSubstitutionInputRule, KEYS, type SlateEditor } from "platejs";

const enabled = ({ editor }: { editor: SlateEditor }) => !editor.api.some({ match: { type: editor.getType(KEYS.codeBlock) } });

// Preserve the existing symbol substitutions using Plate's native input-rule runtime.
const patterns = [
    {
        match: String.fromCharCode(34),
        format: ["“", "”"],
    },
    {
        match: "'",
        format: ["‘", "’"],
    },
    {
        match: "--",
        format: "—",
    },
    {
        match: "...",
        format: "…",
    },
    {
        match: ">>",
        format: "»",
    },
    {
        match: "<<",
        format: "«",
    },
    {
        match: ["(tm)", "(TM)"],
        format: "™",
    },
    {
        match: ["(r)", "(R)"],
        format: "®",
    },
    {
        match: ["(c)", "(C)"],
        format: "©",
    },
    {
        match: "&trade;",
        format: "™",
    },
    {
        match: "&reg;",
        format: "®",
    },
    {
        match: "&copy;",
        format: "©",
    },
    {
        match: "&sect;",
        format: "§",
    },
    {
        match: "->",
        format: "→",
    },
    {
        match: "<-",
        format: "←",
    },
    {
        match: "=>",
        format: "⇒",
    },
    {
        match: ["<=", "≤="],
        format: "⇐",
    },
    {
        match: "!>",
        format: "≯",
    },
    {
        match: "!<",
        format: "≮",
    },
    {
        match: ">=",
        format: "≥",
    },
    {
        match: "<=",
        format: "≤",
    },
    {
        match: "!>=",
        format: "≱",
    },
    {
        match: "!<=",
        format: "≰",
    },
    {
        match: "!=",
        format: "≠",
    },
    {
        match: "==",
        format: "≡",
    },
    {
        match: ["!==", "≠="],
        format: "≢",
    },
    {
        match: "~=",
        format: "≈",
    },
    {
        match: "!~=",
        format: "≉",
    },
    {
        match: "+-",
        format: "±",
    },
    {
        match: "%%",
        format: "‰",
    },
    {
        match: ["%%%", "‰%"],
        format: "‱",
    },
    {
        match: "//",
        format: "÷",
    },
    {
        match: "1/2",
        format: "½",
    },
    {
        match: "1/3",
        format: "⅓",
    },
    {
        match: "1/4",
        format: "¼",
    },
    {
        match: "1/5",
        format: "⅕",
    },
    {
        match: "1/6",
        format: "⅙",
    },
    {
        match: "1/7",
        format: "⅐",
    },
    {
        match: "1/8",
        format: "⅛",
    },
    {
        match: "1/9",
        format: "⅑",
    },
    {
        match: "1/10",
        format: "⅒",
    },
    {
        match: "2/3",
        format: "⅔",
    },
    {
        match: "2/5",
        format: "⅖",
    },
    {
        match: "3/4",
        format: "¾",
    },
    {
        match: "3/5",
        format: "⅗",
    },
    {
        match: "3/8",
        format: "⅜",
    },
    {
        match: "4/5",
        format: "⅘",
    },
    {
        match: "5/6",
        format: "⅚",
    },
    {
        match: "5/8",
        format: "⅝",
    },
    {
        match: "7/8",
        format: "⅞",
    },
    {
        match: "^o",
        format: "°",
    },
    {
        match: "^+",
        format: "⁺",
    },
    {
        match: "^-",
        format: "⁻",
    },
    {
        match: "~+",
        format: "₊",
    },
    {
        match: "~-",
        format: "₋",
    },
    {
        match: "^0",
        format: "⁰",
    },
    {
        match: "^1",
        format: "¹",
    },
    {
        match: "^2",
        format: "²",
    },
    {
        match: "^3",
        format: "³",
    },
    {
        match: "^4",
        format: "⁴",
    },
    {
        match: "^5",
        format: "⁵",
    },
    {
        match: "^6",
        format: "⁶",
    },
    {
        match: "^7",
        format: "⁷",
    },
    {
        match: "^8",
        format: "⁸",
    },
    {
        match: "^9",
        format: "⁹",
    },
    {
        match: "~0",
        format: "₀",
    },
    {
        match: "~1",
        format: "₁",
    },
    {
        match: "~2",
        format: "₂",
    },
    {
        match: "~3",
        format: "₃",
    },
    {
        match: "~4",
        format: "₄",
    },
    {
        match: "~5",
        format: "₅",
    },
    {
        match: "~6",
        format: "₆",
    },
    {
        match: "~7",
        format: "₇",
    },
    {
        match: "~8",
        format: "₈",
    },
    {
        match: "~9",
        format: "₉",
    },
];

export const AutoformatKit = [
    createSlatePlugin({
        key: "editorShortcuts",
        inputRules: [
            createTextSubstitutionInputRule({ enabled, patterns }),
            createTextSubstitutionInputRule({ enabled, patterns: [{ match: "[[", format: "{{" }] }),
            createBlockStartInputRule({
                enabled,
                match: "$$eq",
                trigger: "q",
                node: KEYS.equation,
                apply: ({ editor }, match) => {
                    editor.tf.delete({ at: match.range });
                    editor.tf.setNodes({ type: KEYS.equation });
                    editor.tf.insertNodes({ type: KEYS.p, children: [{ text: "" }] });
                    return true;
                },
            }),
            ...CODE_DRAWING_TYPE_ARRAY.map((drawingType) =>
                createBlockStartInputRule({
                    enabled,
                    match: `$$${drawingType}`,
                    trigger: drawingType.slice(-1),
                    node: KEYS.codeDrawing,
                    apply: ({ editor }, match) => {
                        editor.tf.delete({ at: match.range });
                        editor.tf.setNodes({
                            type: KEYS.codeDrawing,
                            data: { drawingType: drawingType as unknown as CodeDrawingType, drawingMode: VIEW_MODE.Both, code: "" },
                        });
                        return true;
                    },
                })
            ),
        ],
    }),
];
