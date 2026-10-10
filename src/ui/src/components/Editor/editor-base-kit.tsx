import { BaseSecretReferenceKit } from "./plugins/secret-reference-kit";
import { BaseBasicBlocksKit } from "@/components/Editor/plugins/basic-blocks-base-kit";
import { BaseBasicMarksKit } from "@/components/Editor/plugins/basic-marks-base-kit";
import { BaseCalloutKit } from "@/components/Editor/plugins/callout-base-kit";
import { BaseCodeBlockKit } from "@/components/Editor/plugins/code-block-base-kit";
import { BaseCodeDrawingKit } from "@/components/Editor/plugins/code-drawing-base-kit";
import { BaseDateKit } from "@/components/Editor/plugins/date-base-kit";
import { BaseLinkKit } from "@/components/Editor/plugins/link-base-kit";
import { BaseListKit } from "@/components/Editor/plugins/list-base-kit";
import { MarkdownKit } from "@/components/Editor/plugins/markdown-kit";
import { BaseMathKit } from "@/components/Editor/plugins/math-base-kit";
import { BaseMediaKit } from "@/components/Editor/plugins/media-base-kit";
import { BaseMentionKit } from "@/components/Editor/plugins/mention-base-kit";
import { BaseTableKit } from "@/components/Editor/plugins/table-base-kit";
import { BaseTocKit } from "@/components/Editor/plugins/toc-base-kit";

export const BaseEditorKit = [
    ...BaseBasicBlocksKit,
    ...BaseCodeBlockKit,
    ...BaseCodeDrawingKit,
    ...BaseTableKit,
    ...BaseTocKit,
    ...BaseMediaKit,
    ...BaseCalloutKit,
    ...BaseMathKit,
    ...BaseDateKit,
    ...BaseLinkKit,
    ...BaseSecretReferenceKit,
    ...BaseMentionKit,
    ...BaseBasicMarksKit,
    ...BaseListKit,
    ...MarkdownKit,
];
