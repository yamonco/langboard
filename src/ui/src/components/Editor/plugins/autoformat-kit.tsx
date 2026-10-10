"use client";

import type { AutoformatRule } from "@platejs/autoformat";
import {
    autoformatArrow,
    autoformatLegal,
    autoformatLegalHtml,
    autoformatMath,
    AutoformatPlugin,
    autoformatPunctuation,
    autoformatSmartQuotes,
} from "@platejs/autoformat";
import { insertEmptyCodeBlock } from "@platejs/code-block";
import { CODE_DRAWING_TYPE_ARRAY, CodeDrawingType, VIEW_MODE } from "@platejs/code-drawing";
import { toggleList } from "@platejs/list";
import { KEYS } from "platejs";
import { formatOrderedList } from "./markdown/list-number";

const autoformatMarks: AutoformatRule[] = [
    {
        match: "***",
        mode: "mark",
        type: [KEYS.bold, KEYS.italic],
    },
    {
        match: "__*",
        mode: "mark",
        type: [KEYS.underline, KEYS.italic],
    },
    {
        match: "__**",
        mode: "mark",
        type: [KEYS.underline, KEYS.bold],
    },
    {
        match: "___***",
        mode: "mark",
        type: [KEYS.underline, KEYS.bold, KEYS.italic],
    },
    {
        match: "**",
        mode: "mark",
        type: KEYS.bold,
    },
    {
        match: "__",
        mode: "mark",
        type: KEYS.underline,
    },
    {
        match: "*",
        mode: "mark",
        type: KEYS.italic,
    },
    {
        match: "_",
        mode: "mark",
        type: KEYS.italic,
    },
    {
        match: "~~",
        mode: "mark",
        type: KEYS.strikethrough,
    },
    {
        match: "^",
        mode: "mark",
        type: KEYS.sup,
    },
    {
        match: "~",
        mode: "mark",
        type: KEYS.sub,
    },
    {
        match: "==",
        mode: "mark",
        type: KEYS.highlight,
    },
    {
        match: "≡",
        mode: "mark",
        type: KEYS.highlight,
    },
    {
        match: "`",
        mode: "mark",
        type: KEYS.code,
    },
];

const autoformatBlocks: AutoformatRule[] = [
    {
        match: "# ",
        mode: "block",
        type: KEYS.h1,
    },
    {
        match: "## ",
        mode: "block",
        type: KEYS.h2,
    },
    {
        match: "### ",
        mode: "block",
        type: KEYS.h3,
    },
    {
        match: "#### ",
        mode: "block",
        type: KEYS.h4,
    },
    {
        match: "##### ",
        mode: "block",
        type: KEYS.h5,
    },
    {
        match: "###### ",
        mode: "block",
        type: KEYS.h6,
    },
    {
        match: "> ",
        mode: "block",
        type: KEYS.blockquote,
    },
    {
        match: "```",
        mode: "block",
        type: KEYS.codeBlock,
        format: (editor) => {
            insertEmptyCodeBlock(editor, {
                defaultType: KEYS.p,
                insertNodesOptions: { select: true },
            });
        },
    },
    {
        match: ["---", "—-", "___ "],
        mode: "block",
        type: KEYS.hr,
        format: (editor) => {
            editor.tf.setNodes({ type: KEYS.hr });
            editor.tf.insertNodes({
                children: [{ text: "" }],
                type: KEYS.p,
            });
        },
    },
    {
        match: "$$eq",
        mode: "block",
        type: KEYS.equation,
        format: (editor) => {
            editor.tf.setNodes({ type: KEYS.equation });
            editor.tf.insertNodes({
                children: [{ text: "" }],
                type: KEYS.p,
            });
        },
    },
    ...CODE_DRAWING_TYPE_ARRAY.map(
        (codeDrawingType) =>
            ({
                match: `$$${codeDrawingType}`,
                mode: "block",
                type: KEYS.codeDrawing,
                format: (editor) => {
                    editor.tf.setNodes({
                        type: KEYS.codeDrawing,
                        children: [{ text: "" }],
                        data: {
                            drawingType: codeDrawingType as unknown as CodeDrawingType,
                            drawingMode: VIEW_MODE.Both,
                            code: "",
                        },
                    });
                },
            }) as AutoformatRule
    ),
];

const autoformatLists: AutoformatRule[] = [
    {
        match: ["* ", "- "],
        mode: "block",
        type: "list",
        format: (editor) => {
            toggleList(editor, {
                listStyleType: KEYS.ul,
            });
        },
    },
    {
        match: [String.raw`^\d+\.$ `, String.raw`^\d+\)$ `],
        matchByRegex: true,
        mode: "block",
        type: "list",
        format: formatOrderedList,
    },
    {
        match: ["[] "],
        mode: "block",
        type: "list",
        format: (editor) => {
            toggleList(editor, {
                listStyleType: KEYS.listTodo,
            });
            editor.tf.setNodes({
                checked: false,
                listStyleType: KEYS.listTodo,
            });
        },
    },
    {
        match: ["[x] "],
        mode: "block",
        type: "list",
        format: (editor) => {
            toggleList(editor, {
                listStyleType: KEYS.listTodo,
            });
            editor.tf.setNodes({
                checked: true,
                listStyleType: KEYS.listTodo,
            });
        },
    },
    {
        match: ["[["],
        mode: "text",
        format: (editor) => {
            editor.tf.insertText("{{");
        },
    },
];

export const AutoformatKit = [
    AutoformatPlugin.configure({
        options: {
            enableUndoOnDelete: true,
            rules: [
                ...autoformatBlocks,
                ...autoformatMarks,
                ...autoformatSmartQuotes,
                ...autoformatPunctuation,
                ...autoformatLegal,
                ...autoformatLegalHtml,
                ...autoformatArrow,
                ...autoformatMath,
                ...autoformatLists,
            ].map(
                (rule): AutoformatRule => ({
                    ...rule,
                    query: (editor) =>
                        !editor.api.some({
                            match: { type: editor.getType(KEYS.codeBlock) },
                        }),
                })
            ),
        },
    }),
];
