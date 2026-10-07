import MoreMenu from "@/components/MoreMenu";
import Toast from "@/components/base/Toast";
import { api } from "@/core/helpers/Api";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { documentDisplayTags, EDoclingIndexStatus, parseDoclingMetadata } from "@/core/constants/DoclingMetadata";
import { MetadataModel } from "@/core/models";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { useAuth } from "@/core/providers/AuthProvider";
import { ProjectRole } from "@/core/models/roles";
import { Routing } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import { useTranslation } from "react-i18next";

export function BoardCardAttachmentDocumentAction({ mode = "transcription" }: { mode?: "transcription" | "embedding" }): React.JSX.Element | null {
    const [t] = useTranslation();
    const { projectUID, card, hasRoleAction } = useBoardCard();
    const { model: attachment } = ModelRegistry.ProjectCardAttachment.useContext();
    const name = attachment.useField("name");
    const actionLabel = t(mode === "embedding" ? "card.Index document embeddings" : "card.Process document");
    if (!hasRoleAction(ProjectRole.EAction.CardUpdate) || !/\.(pdf|png|jpe?g|tiff?|bmp|webp|docx|pptx|xlsx|html?|md|markdown|csv)$/i.test(name))
        return null;
    const process = (endCallback: (close: bool) => void) => {
        const url = Utils.String.format(Routing.API.BOARD.CARD.ATTACHMENT.PROCESS_DOCUMENT, {
            uid: projectUID,
            card_uid: card.uid,
            attachment_uid: attachment.uid,
        });
        Toast.Add.promise(api.post(url, { reprocess: true, mode }, { env: { interceptToast: true } as never }), {
            loading: t("common.Changing..."),
            success: () => t(mode === "embedding" ? "card.Embedding requested" : "card.Document processing requested"),
            error: (error) => {
                const message = { message: "" };
                setupApiErrorHandler({}, message).handle(error);
                return message.message;
            },
            finally: () => endCallback(true),
        });
    };
    return (
        <MoreMenu.PopoverItem menuName={actionLabel} saveText={actionLabel} onSave={process}>
            <p className="max-w-72 text-sm text-muted-foreground">
                {t(mode === "embedding" ? "card.Embed only this transcription" : "card.Process only this attachment")}
            </p>
        </MoreMenu.PopoverItem>
    );
}

export function BoardCardAttachmentDocumentProgress({
    attachmentUID,
    cardUID,
}: {
    attachmentUID?: string;
    cardUID?: string;
}): React.JSX.Element | null {
    const { currentUser } = useAuth();
    const { card } = useBoardCard();
    const uid = cardUID ?? card.uid;
    const record = MetadataModel.Model.useModel(uid, [uid]);
    return record && currentUser ? <DocumentProgress record={record} attachmentUID={attachmentUID} currentUser={currentUser} /> : null;
}

function DocumentProgress({
    record,
    attachmentUID,
    currentUser,
}: {
    record: MetadataModel.TModel;
    attachmentUID?: string;
    currentUser: NonNullable<ReturnType<typeof useAuth>["currentUser"]>;
}): React.JSX.Element | null {
    const [t] = useTranslation();
    const preferredLanguage = currentUser.useField("preferred_lang");
    const metadata = record.useField("metadata");
    const document = parseDoclingMetadata(metadata).find((entry) =>
        attachmentUID
            ? entry.attachment_uid === attachmentUID
            : entry.status === EDoclingIndexStatus.Pending || entry.status === EDoclingIndexStatus.Processing
    );
    if (!document) return null;
    const tags = attachmentUID ? documentDisplayTags(document.content, preferredLanguage) : [];
    const running = document.status === EDoclingIndexStatus.Processing;
    const label = running
        ? t("card.Processing document")
        : document.status === EDoclingIndexStatus.Pending
          ? t("card.Document queued")
          : document.status === EDoclingIndexStatus.Indexed
            ? t("card.Document indexed")
            : document.status === EDoclingIndexStatus.Failed
              ? t("card.Document processing failed")
              : t("card.Document processing disabled");
    const percent = typeof document.progress_percent === "number" ? Math.max(0, Math.min(100, document.progress_percent)) : undefined;
    const pages =
        typeof document.total_pages === "number" && document.total_pages > 0
            ? t("card.Document page progress", { completed: document.completed_pages ?? 0, total: document.total_pages })
            : "";
    return (
        <div className="mt-1 max-w-64 text-xs text-muted-foreground" role="status" aria-live="polite">
            <span>
                {label}
                {pages ? ` · ${pages}` : ""}
                {running && percent !== undefined ? ` · ${percent}%` : ""}
            </span>
            {attachmentUID && document.embedding && (
                <span className="mt-0.5 block">
                    {t(
                        document.embedding.status === "indexed"
                            ? "card.Embedding indexed"
                            : document.embedding.status === "failed"
                              ? "card.Embedding failed"
                              : "card.Embedding queued"
                    )}
                </span>
            )}
            {running && <progress className="mt-1 block h-1 w-full accent-primary" max={100} value={percent} aria-label={label} />}
            {tags.length > 0 && (
                <div className="mt-1 flex max-w-full flex-wrap gap-x-2 gap-y-0.5 text-primary/70">
                    {tags.map((tag) => (
                        <span key={tag} className="max-w-full break-words">
                            #{tag}
                        </span>
                    ))}
                </div>
            )}
        </div>
    );
}
