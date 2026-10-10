"use client";

import { CodeBlockPlugin, CodeLinePlugin, CodeSyntaxPlugin } from "@platejs/code-block/react";
import { CodeBlockRules } from "@platejs/code-block";
import { all, createLowlight } from "lowlight";
import { CodeBlockElement, CodeLineElement, CodeSyntaxLeaf } from "@/components/plate-ui/code-block-node";

const lowlight = createLowlight(all);

export const CodeBlockKit = [
    CodeBlockPlugin.configure({
        inputRules: [CodeBlockRules.markdown({ on: "match" })],
        node: { component: CodeBlockElement },
        options: { lowlight },
        shortcuts: { toggle: { keys: "mod+alt+8" } },
    }),
    CodeLinePlugin.withComponent(CodeLineElement),
    CodeSyntaxPlugin.withComponent(CodeSyntaxLeaf),
];
