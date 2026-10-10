import { SecretReferenceKit } from "./plugins/secret-reference-kit";
("use client");

import { type Value, TrailingBlockPlugin } from "platejs";
import { type TPlateEditor } from "platejs/react";
import { AutoformatKit } from "@/components/Editor/plugins/autoformat-kit";
import { BasicBlocksKit } from "@/components/Editor/plugins/basic-blocks-kit";
import { BasicMarksKit } from "@/components/Editor/plugins/basic-marks-kit";
import { BlockMenuKit } from "@/components/Editor/plugins/block-menu-kit";
import { BlockPlaceholderKit } from "@/components/Editor/plugins/block-placeholder-kit";
import { CalloutKit } from "@/components/Editor/plugins/callout-kit";
import { CodeBlockKit } from "@/components/Editor/plugins/code-block-kit";
import { CursorOverlayKit } from "@/components/Editor/plugins/cursor-overlay-kit";
import { DateKit } from "@/components/Editor/plugins/date-kit";
import { EmojiKit } from "@/components/Editor/plugins/emoji-kit";
import { ExitBreakKit } from "@/components/Editor/plugins/exit-break-kit";
import { FixedToolbarKit } from "@/components/Editor/plugins/fixed-toolbar-kit";
import { FloatingToolbarKit } from "@/components/Editor/plugins/floating-toolbar-kit";
import { LinkKit } from "@/components/Editor/plugins/link-kit";
import { ListKit } from "@/components/Editor/plugins/list-kit";
import { MarkdownKit } from "@/components/Editor/plugins/markdown-kit";
import { MathKit } from "@/components/Editor/plugins/math-kit";
import { MediaKit } from "@/components/Editor/plugins/media-kit";
import { MentionKit } from "@/components/Editor/plugins/mention-kit";
import { SlashKit } from "@/components/Editor/plugins/slash-kit";
import { TableKit } from "@/components/Editor/plugins/table-kit";
import { TocKit } from "@/components/Editor/plugins/toc-kit";
import { CodeDrawingKit } from "@/components/Editor/plugins/code-drawing-kit";
import { InternalLinkKit } from "@/components/Editor/plugins/internal-link-kit";

export const EditorKit = [
    ...BlockMenuKit,

    // Elements
    ...BasicBlocksKit,
    ...CodeBlockKit,
    ...CodeDrawingKit,
    ...TableKit,
    ...TocKit,
    ...MediaKit,
    ...CalloutKit,
    ...MathKit,
    ...DateKit,
    ...LinkKit,
    ...SecretReferenceKit,
    ...MentionKit,

    // Marks
    ...BasicMarksKit,

    // Block Style
    ...ListKit,

    // Editing
    ...SlashKit,
    ...AutoformatKit,
    ...CursorOverlayKit,
    ...EmojiKit,
    ...ExitBreakKit,
    TrailingBlockPlugin,

    // Parsers
    ...MarkdownKit,

    // UI
    ...BlockPlaceholderKit,
    ...FixedToolbarKit,
    ...FloatingToolbarKit,

    // Custom
    ...InternalLinkKit,
];

export type TEditor = TPlateEditor<Value, (typeof EditorKit)[number]>;
