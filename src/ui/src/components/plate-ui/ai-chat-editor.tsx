"use client";

import * as React from "react";
import { useAIChatEditor } from "@platejs/ai/react";
import { createSlateEditor } from "platejs";
import { BaseEditorKit } from "@/components/Editor/editor-base-kit";
import { EditorStatic } from "@/components/plate-ui/editor-static";

export const AIChatEditor = React.memo(function AIChatEditor({ content }: { content: string }) {
    const aiEditor = React.useMemo(() => createSlateEditor({ plugins: BaseEditorKit }), []);

    const value = useAIChatEditor(aiEditor, content);

    return <EditorStatic variant="aiChat" editor={aiEditor} value={value} />;
});
