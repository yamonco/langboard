import { useState } from "react";
import { useTranslation } from "react-i18next";
import Popover from "@/components/base/Popover";
import IconComponent from "@/components/base/IconComponent";
import useCardReadState from "@/controllers/api/board/useCardReadState";
import { ProjectCardComment } from "@/core/models";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";

export default function BoardCommentSeen({ comment }: { comment: ProjectCardComment.TModel }) {
    const [t] = useTranslation();
    const { projectUID, card, currentUser } = useBoardCard();
    const version = card.useField("read_state_version");
    const { readers, unread } = useCardReadState(projectUID, card.uid, version);
    const members = card.useForeignFieldArray("project_members");
    const updatedAt = comment.useField("updated_at");
    const seen = (readers.data ?? []).filter((reader) => new Date(reader.seen_at).getTime() >= new Date(updatedAt).getTime());
    const ownSeen = seen.some((reader) => reader.user_uid === currentUser.uid);
    const [open, setOpen] = useState(false);
    if (!readers.data) return null;
    return (
        <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground/70">
            <Popover.Root open={open} onOpenChange={setOpen}>
                <Popover.Trigger asChild>
                    <button
                        type="button"
                        className="underline-offset-2 hover:underline focus-visible:underline"
                        onPointerEnter={(event) => {
                            if (event.pointerType === "mouse") setOpen(true);
                        }}
                        onPointerLeave={(event) => {
                            if (event.pointerType === "mouse") setOpen(false);
                        }}
                        onFocus={(event) => {
                            if (event.currentTarget.matches(":focus-visible")) setOpen(true);
                        }}
                        onBlur={() => setOpen(false)}
                        onClick={(event) => {
                            event.preventDefault();
                            setOpen(true);
                        }}
                    >
                        {t("card.Seen by count", { count: seen.length })}
                    </button>
                </Popover.Trigger>
                <Popover.Content
                    side="top"
                    align="start"
                    className="max-w-[calc(100vw-2rem)] text-xs"
                    onOpenAutoFocus={(event) => event.preventDefault()}
                    onCloseAutoFocus={(event) => event.preventDefault()}
                >
                    <p className="mb-2 text-muted-foreground">{t("card.Card view receipt")}</p>
                    <ul className="max-h-48 space-y-1 overflow-y-auto">
                        {seen.map((reader) => {
                            const member = members.find((user) => user.uid === reader.user_uid);
                            return (
                                <li key={reader.user_uid}>
                                    {member ? `${member.firstname} ${member.lastname}`.trim() || member.username : t("common.Unknown User")}
                                </li>
                            );
                        })}
                    </ul>
                </Popover.Content>
            </Popover.Root>
            {ownSeen && (
                <button
                    type="button"
                    className="rounded p-0.5 hover:bg-accent focus-visible:ring-1"
                    aria-label={t("card.Mark card unread")}
                    title={t("card.Mark card unread")}
                    disabled={unread.isPending}
                    onClick={() =>
                        unread.mutate(undefined, {
                            onSuccess: () => {
                                card.has_unread_change = true;
                            },
                            onError: (error) => setupApiErrorHandler({}).handle(error),
                        })
                    }
                >
                    <IconComponent icon="mail" size="3" />
                </button>
            )}
        </span>
    );
}
