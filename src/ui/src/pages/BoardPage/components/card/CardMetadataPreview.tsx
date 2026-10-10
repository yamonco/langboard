import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ProjectCard, ProjectColumn, User } from "@/core/models";
import { useBoard } from "@/core/providers/BoardProvider";
import { cn } from "@/core/utils/ComponentUtils";
import Popover from "@/components/base/Popover";

function MemberName({ member }: { member: User.TModel }) {
    const firstname = member.useField("firstname");
    const lastname = member.useField("lastname");
    return <span>{`${firstname} ${lastname}`.trim()}</span>;
}

function ColumnName({ column }: { column: ProjectColumn.TModel }) {
    return <span>{column.useField("name")}</span>;
}

export default function CardMetadataPreview({ card, children }: { card: ProjectCard.TModel; children: ReactNode }) {
    const [t] = useTranslation();
    const [open, setOpen] = useState(false);
    const { project, columns } = useBoard();
    const members = project.useForeignFieldArray("all_members");
    const memberUIDs = card.useField("member_uids") ?? [];
    const creator = card.useField("creator");
    const createdAt = card.useField("created_at");
    const updatedAt = card.useField("updated_at");
    const deadlineAt = card.useField("deadline_at");
    const commentCount = card.useField("count_comment");
    const columnUID = card.useField("project_column_uid");
    const column = columns.find((item) => item.uid === columnUID);
    const assignees = members.filter((member) => memberUIDs.includes(member.uid));
    const exact = (date: Date) => date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
    const rows: [string, ReactNode][] = [
        [t("card.Created"), exact(createdAt)],
        [t("card.Updated"), exact(updatedAt)],
    ];
    if (creator?.name) rows.push([t("card.Creator"), creator.name]);
    if (assignees.length)
        rows.push([
            t("card.Members"),
            assignees.map((member, i) => (
                <span key={member.uid}>
                    {i > 0 && ", "}
                    <MemberName member={member} />
                </span>
            )),
        ]);
    if (commentCount !== undefined) rows.push([t("card.Comments"), commentCount]);
    if (deadlineAt) rows.push([t("card.Deadline"), exact(deadlineAt)]);
    if (column) rows.push([t("card.Column"), <ColumnName column={column} />]);

    return (
        <Popover.Root open={open} onOpenChange={setOpen}>
            <Popover.Trigger asChild>
                <button
                    type="button"
                    aria-label={t("card.Preview card details")}
                    className={cn(
                        "inline-flex items-center gap-1 rounded-sm text-left",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    )}
                    onPointerDown={(event) => event.stopPropagation()}
                    onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        setOpen(true);
                    }}
                    onPointerEnter={(event) => {
                        if (event.pointerType === "mouse") setOpen(true);
                    }}
                    onPointerLeave={(event) => {
                        if (event.pointerType === "mouse") setOpen(false);
                    }}
                    onFocus={(event) => {
                        if (event.currentTarget.matches(":focus-visible")) setOpen(true);
                    }}
                >
                    {children}
                </button>
            </Popover.Trigger>
            <Popover.Content
                className="w-72 max-w-[calc(100vw-2rem)] text-xs"
                side="top"
                align="start"
                onOpenAutoFocus={(event) => event.preventDefault()}
                onCloseAutoFocus={(event) => event.preventDefault()}
                onClick={(event) => event.stopPropagation()}
                onPointerDown={(event) => event.stopPropagation()}
            >
                <h3 className="mb-2 font-semibold">{t("card.Card details")}</h3>
                <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5">
                    {rows.map(([label, value]) => (
                        <div key={label} className="contents">
                            <dt className="text-muted-foreground">{label}</dt>
                            <dd className="break-words">{value}</dd>
                        </div>
                    ))}
                </dl>
            </Popover.Content>
        </Popover.Root>
    );
}
