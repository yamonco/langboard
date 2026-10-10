import { MarkdownPlugin } from "@platejs/markdown";
import { usePlateEditor } from "platejs/react";
import { memo, useMemo } from "react";

import { BaseEditorKit } from "@/components/Editor/editor-base-kit";
import { BaseInternalLinkKit } from "@/components/Editor/plugins/internal-link-base-kit";
import Box from "@/components/base/Box";
import { EditorStatic } from "@/components/plate-ui/editor-static";
import { EditorDataProvider } from "@/core/providers/EditorDataProvider";
import { AuthUser, ProjectCard } from "@/core/models";
import type { TUserLikeModel } from "@/core/models/ModelRegistry";

import type { IDescriptionChunk } from "./descriptionChunks";

const DescriptionStaticKit = [...BaseEditorKit, ...BaseInternalLinkKit];

interface IBoardCardDescriptionStaticChunkProps {
    chunk: IDescriptionChunk;
    currentUser: AuthUser.TModel;
    mentionables: TUserLikeModel[];
    cards: ProjectCard.TModel[];
    projectUID: string;
    cardUID: string;
}

interface IStaticChunkBodyProps {
    chunk: IDescriptionChunk;
}

const StaticChunkBody = memo(({ chunk }: IStaticChunkBodyProps): React.JSX.Element => {
    const editor = usePlateEditor({
        plugins: DescriptionStaticKit,
    });

    const value = useMemo(() => editor.getApi(MarkdownPlugin).markdown.deserialize(chunk.content), [chunk.content, editor]);

    return <EditorStatic editor={editor} value={value} variant="ai" className="h-full min-h-0 px-0" />;
});

export const BoardCardDescriptionStaticChunk = memo(
    ({ chunk, currentUser, mentionables, cards, projectUID, cardUID }: IBoardCardDescriptionStaticChunkProps): React.JSX.Element => {
        return (
            <Box
                data-card-description-chunk
                data-description-chunk-id={chunk.id}
                data-description-card-uid={cardUID}
                className="[contain-intrinsic-size:auto_160px]"
            >
                <EditorDataProvider
                    currentUser={currentUser}
                    mentionables={mentionables}
                    linkables={cards}
                    editorType="view"
                    form={{ project_uid: projectUID }}
                >
                    <StaticChunkBody chunk={chunk} />
                </EditorDataProvider>
            </Box>
        );
    }
);

export default BoardCardDescriptionStaticChunk;
