"use client";

import {
    BoldPlugin,
    CodePlugin,
    HighlightPlugin,
    ItalicPlugin,
    KbdPlugin,
    StrikethroughPlugin,
    SubscriptPlugin,
    SuperscriptPlugin,
    UnderlinePlugin,
} from "@platejs/basic-nodes/react";
import {
    BoldRules,
    ItalicRules,
    UnderlineRules,
    CodeRules,
    StrikethroughRules,
    SubscriptRules,
    SuperscriptRules,
    HighlightRules,
    MarkComboRules,
} from "@platejs/basic-nodes";
import { CodeLeaf } from "@/components/plate-ui/code-node";
import { HighlightLeaf } from "@/components/plate-ui/highlight-node";
import { KbdLeaf } from "@/components/plate-ui/kbd-node";

export const BasicMarksKit = [
    BoldPlugin.configure({
        inputRules: [
            BoldRules.markdown({ variant: "*" }),
            ...["boldItalic", "italicUnderline", "boldUnderline", "boldItalicUnderline"].map((variant) =>
                MarkComboRules.markdown({ variant: variant as "boldItalic" | "italicUnderline" | "boldUnderline" | "boldItalicUnderline" })
            ),
        ],
    }),
    ItalicPlugin.configure({ inputRules: [ItalicRules.markdown({ variant: "*" }), ItalicRules.markdown({ variant: "_" })] }),
    UnderlinePlugin.configure({ inputRules: [UnderlineRules.markdown()] }),
    CodePlugin.configure({
        inputRules: [CodeRules.markdown()],
        node: { component: CodeLeaf },
        shortcuts: { toggle: { keys: "mod+e" } },
    }),
    StrikethroughPlugin.configure({
        inputRules: [StrikethroughRules.markdown()],
        shortcuts: { toggle: { keys: "mod+shift+x" } },
    }),
    SubscriptPlugin.configure({
        inputRules: [SubscriptRules.markdown()],
        shortcuts: { toggle: { keys: "mod+comma" } },
    }),
    SuperscriptPlugin.configure({
        inputRules: [SuperscriptRules.markdown()],
        shortcuts: { toggle: { keys: "mod+period" } },
    }),
    HighlightPlugin.configure({
        inputRules: [HighlightRules.markdown({ variant: "==" }), HighlightRules.markdown({ variant: "≡" })],
        node: { component: HighlightLeaf },
        shortcuts: { toggle: { keys: "mod+shift+h" } },
    }),
    KbdPlugin.withComponent(KbdLeaf),
];
