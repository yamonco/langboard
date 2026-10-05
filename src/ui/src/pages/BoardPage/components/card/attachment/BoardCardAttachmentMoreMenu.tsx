import { BoardCardAttachmentDocumentAction } from "./BoardCardAttachmentDocument";
import MoreMenu from "@/components/MoreMenu";
import { ProjectCardAttachment } from "@/core/models";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import BoardCardAttachmentMoreMenuDelete from "@/pages/BoardPage/components/card/attachment/BoardCardAttachmentMoreMenuDelete";
import BoardCardAttachmentMoreMenuDownload from "@/pages/BoardPage/components/card/attachment/BoardCardAttachmentMoreMenuDownload";
import BoardCardAttachmentMoreMenuRename from "@/pages/BoardPage/components/card/attachment/BoardCardAttachmentMoreMenuRename";

export interface IBoardCardAttachmentMoreMenuProps {
    attachment: ProjectCardAttachment.TModel;
    isValidating: bool;
    setIsValidating: (value: bool) => void;
}

function BoardCardAttachmentMoreMenu({ attachment, isValidating, setIsValidating }: IBoardCardAttachmentMoreMenuProps): React.JSX.Element {
    return (
        <ModelRegistry.ProjectCardAttachment.Provider model={attachment} params={{ isValidating, setIsValidating }}>
            <MoreMenu.Root triggerProps={{ className: "h-8 w-5 sm:size-8" }}>
                <BoardCardAttachmentMoreMenuDownload />
                <BoardCardAttachmentDocumentAction />
                <BoardCardAttachmentMoreMenuRename />
                <BoardCardAttachmentMoreMenuDelete />
            </MoreMenu.Root>
        </ModelRegistry.ProjectCardAttachment.Provider>
    );
}

export default BoardCardAttachmentMoreMenu;
