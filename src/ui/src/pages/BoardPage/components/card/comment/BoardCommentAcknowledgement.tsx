import { useState } from "react";
import { useTranslation } from "react-i18next";
import Button from "@/components/base/Button";
import Popover from "@/components/base/Popover";
import useAcknowledgeCardComment from "@/controllers/api/card/comment/useAcknowledgeCardComment";
import { ProjectCardComment } from "@/core/models";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";

export default function BoardCommentAcknowledgement({ comment }: { comment: ProjectCardComment.TModel }) {
    const [t] = useTranslation();
    const { projectUID, card, currentUser } = useBoardCard();
    const uids = [...new Set(comment.useField("acknowledged_user_uids") ?? [])];
    const members = card.useForeignFieldArray("project_members");
    const acknowledged = uids.includes(currentUser.uid);
    const { mutate, isPending } = useAcknowledgeCardComment();
    const [open, setOpen] = useState(false);
    const toggle = () => {
        if (isPending) return;
        mutate(
            { project_uid: projectUID, card_uid: card.uid, comment_uid: comment.uid, acknowledged: !acknowledged },
            {
                onSuccess: (data) => {
                    comment.acknowledged_user_uids = data.acknowledged_user_uids;
                },
                onError: (error) => setupApiErrorHandler({}).handle(error),
            }
        );
    };
    return (
        <>
            <Button
                variant="link"
                size="sm"
                className="h-5 p-0 text-accent-foreground/60"
                aria-pressed={acknowledged}
                aria-label={t(acknowledged ? "card.Withdraw acknowledgement" : "card.Acknowledge comment")}
                onClick={toggle}
                disabled={isPending}
            >
                {t(acknowledged ? "card.Acknowledged" : "card.Acknowledge")}
            </Button>
            {uids.length > 0 && (
                <Popover.Root open={open} onOpenChange={setOpen}>
                    <Popover.Trigger asChild>
                        <button
                            type="button"
                            className="text-xs text-muted-foreground underline-offset-2 hover:underline focus-visible:underline"
                            onPointerEnter={(event) => {
                                if (event.pointerType === "mouse") setOpen(true);
                            }}
                            onPointerLeave={(event) => {
                                if (event.pointerType === "mouse") setOpen(false);
                            }}
                            onFocus={(event) => {
                                if (event.currentTarget.matches(":focus-visible")) setOpen(true);
                            }}
                            onClick={(event) => {
                                event.preventDefault();
                                setOpen(true);
                            }}
                            onBlur={() => setOpen(false)}
                        >
                            {t("card.Acknowledged by count", { count: uids.length })}
                        </button>
                    </Popover.Trigger>
                    <Popover.Content
                        side="top"
                        align="start"
                        className="max-w-[calc(100vw-2rem)] text-xs"
                        onOpenAutoFocus={(event) => event.preventDefault()}
                        onCloseAutoFocus={(event) => event.preventDefault()}
                    >
                        <p className="mb-2 font-medium">{t("card.Explicit acknowledgements")}</p>
                        <ul className="max-h-48 space-y-1 overflow-y-auto">
                            {uids.map((uid) => {
                                const member = members.find((user) => user.uid === uid);
                                return (
                                    <li key={uid}>
                                        {member ? `${member.firstname} ${member.lastname}`.trim() || member.username : t("common.Unknown User")}
                                    </li>
                                );
                            })}
                        </ul>
                    </Popover.Content>
                </Popover.Root>
            )}
        </>
    );
}
