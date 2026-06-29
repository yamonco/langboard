import Badge from "@/components/base/Badge";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import Toast from "@/components/base/Toast";
import {
    formatTaskMetadataValue,
    hasTaskMetadata,
    ITaskFailureMetadata,
    ITaskMetadata,
    ITaskRunMetadata,
    ITaskSuggestionMetadata,
    parseTaskMetadata,
} from "@/core/constants/TaskMetadata";
import { MetadataModel } from "@/core/models";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import useCreateOrchestrationSuggestionTask from "@/controllers/api/board/orchestration/useCreateOrchestrationSuggestionTask";
import { PlusIcon } from "lucide-react";
import { memo } from "react";
import { useTranslation } from "react-i18next";

interface IBoardTaskMetadataSectionProps {
    cardUID: string;
}

const BoardTaskMetadataSection = memo(({ cardUID }: IBoardTaskMetadataSectionProps) => {
    const metadataRecord = MetadataModel.Model.useModel(cardUID, [cardUID]);

    if (!metadataRecord || metadataRecord.type !== "card") {
        return null;
    }

    return <BoardTaskMetadataSectionInner cardUID={cardUID} metadataRecord={metadataRecord} />;
});

function BoardTaskMetadataSectionInner({
    cardUID,
    metadataRecord,
}: {
    cardUID: string;
    metadataRecord: MetadataModel.TModel;
}): React.JSX.Element | null {
    const { projectUID, canEditCard } = useBoardCard();
    const metadata = metadataRecord.useField("metadata");
    const task = parseTaskMetadata(metadata);
    const [t] = useTranslation();

    if (!hasTaskMetadata(task)) {
        return null;
    }

    return (
        <Box>
            <Box mb="1">{t("card.Task orchestration")}</Box>
            <Flex direction="col" gap="3" className="rounded-md border bg-secondary/20 p-3">
                <TaskSummary task={task} />
                <TaskList title={t("card.Acceptance criteria")} items={task.acceptanceCriteria} />
                <TaskList title={t("card.Related files")} items={task.relatedFiles} monospace />
                <TaskRun run={task.run} />
                <TaskVerification task={task} />
                <TaskFailure failure={task.failure} />
                <TaskSuggestions task={task} projectUID={projectUID} cardUID={cardUID} canCreate={canEditCard} />
            </Flex>
        </Box>
    );
}

function TaskSummary({ task }: { task: ITaskMetadata }): React.JSX.Element {
    const [t] = useTranslation();
    const bypassLabel = getBypassLabel(task, t);
    const summaryRows = [
        [t("card.Source"), task.source],
        [t("card.Type"), task.type],
        [t("card.Assigned agent"), task.assignedAgent],
        [t("card.Risk"), task.riskLevel],
        [t("card.Bypass"), bypassLabel],
    ].filter(([, value]) => !!value);

    return (
        <Flex direction="col" gap="2">
            <Flex items="center" gap="1" wrap>
                {summaryRows.map(([label, value]) => (
                    <Badge key={`task-summary-${label}`} variant="outline" className="max-w-full truncate">
                        {label}: {formatTaskMetadataValue(String(value))}
                    </Badge>
                ))}
                {task.verification?.status && (
                    <Badge
                        variant={
                            task.verification.status === "failed" ? "destructive" : task.verification.status === "passed" ? "success" : "secondary"
                        }
                    >
                        {t("card.Verification")}: {formatTaskMetadataValue(task.verification.status)}
                    </Badge>
                )}
            </Flex>
            {task.sourceUrl && <TaskLink label={t("card.Source link")} href={task.sourceUrl} />}
            {task.prUrl && <TaskLink label="PR" href={task.prUrl} />}
            {task.externalId && <TaskLine label={t("card.External ID")}>{task.externalId}</TaskLine>}
            {task.bypass?.action_type && <TaskLine label={t("card.Action type")}>{formatTaskMetadataValue(task.bypass.action_type)}</TaskLine>}
            {task.bypass?.reason && <TaskLine label={t("card.Bypass reason")}>{task.bypass.reason}</TaskLine>}
        </Flex>
    );
}

function getBypassLabel(task: ITaskMetadata, t: (key: string) => string): string | undefined {
    if (!task.bypass) {
        return undefined;
    }
    if (task.bypass.requires_approval && task.bypass.allowed) {
        return t("card.Approved");
    }
    if (task.bypass.requires_approval) {
        return t("card.Approval required");
    }
    return task.bypass.allowed ? t("common.Enabled") : t("common.Disabled");
}

function TaskRun({ run }: { run?: ITaskRunMetadata }): React.JSX.Element | null {
    const [t] = useTranslation();

    if (!run) {
        return null;
    }

    return (
        <Flex direction="col" gap="1">
            <Box className="font-medium">{t("card.Agent run")}</Box>
            {run.status && <TaskLine label={t("card.Status")}>{formatTaskMetadataValue(run.status)}</TaskLine>}
            {run.assigned_agent && <TaskLine label={t("card.Assigned agent")}>{formatTaskMetadataValue(run.assigned_agent)}</TaskLine>}
            {run.summary && <TaskLine label={t("card.Summary")}>{run.summary}</TaskLine>}
            {run.run_id && <TaskLine label={t("card.Run ID")}>{run.run_id}</TaskLine>}
            {run.bot_log_uid && <TaskLine label={t("card.Bot log")}>{run.bot_log_uid}</TaskLine>}
            {run.started_at && <TaskLine label={t("card.Started at")}>{run.started_at}</TaskLine>}
            {run.finished_at && <TaskLine label={t("card.Finished at")}>{run.finished_at}</TaskLine>}
            {run.recorded_at && <TaskLine label={t("card.Recorded at")}>{run.recorded_at}</TaskLine>}
        </Flex>
    );
}

function TaskVerification({ task }: { task: ITaskMetadata }): React.JSX.Element | null {
    const [t] = useTranslation();

    if (!task.verification?.summary && !task.verification?.checked_at) {
        return null;
    }

    return (
        <Flex direction="col" gap="1">
            <Box className="font-medium">{t("card.Verification result")}</Box>
            {task.verification.summary && <Box className="break-words text-muted">{task.verification.summary}</Box>}
            {task.verification.checked_at && <Box className="text-xs text-muted">{task.verification.checked_at}</Box>}
        </Flex>
    );
}

function TaskFailure({ failure }: { failure?: ITaskFailureMetadata }): React.JSX.Element | null {
    const [t] = useTranslation();

    if (!failure) {
        return null;
    }

    return (
        <Flex direction="col" gap="2">
            <Box className="font-medium">{t("card.Failure feedback")}</Box>
            {failure.summary && <TaskLine label={t("card.Summary")}>{failure.summary}</TaskLine>}
            {failure.cause && <TaskLine label={t("card.Cause")}>{failure.cause}</TaskLine>}
            <TaskList title={t("card.Reproduction")} items={failure.reproduction ?? []} />
            <TaskList title={t("card.Recommendation")} items={failure.recommendation ?? []} />
        </Flex>
    );
}

function TaskSuggestions({
    task,
    projectUID,
    cardUID,
    canCreate,
}: {
    task: ITaskMetadata;
    projectUID: string;
    cardUID: string;
    canCreate: bool;
}): React.JSX.Element | null {
    const [t] = useTranslation();
    const createSuggestionTask = useCreateOrchestrationSuggestionTask({ interceptToast: true });

    if (!task.suggestions.length) {
        return null;
    }

    const handleCreateTask = (suggestion: ITaskSuggestionMetadata) => {
        if (!suggestion.title || suggestion.created_card_uid) {
            return;
        }

        const promise = createSuggestionTask.mutateAsync({
            project_uid: projectUID,
            card_uid: cardUID,
            suggestion: {
                title: suggestion.title,
                type: suggestion.type,
                assigned_agent: suggestion.assigned_agent,
                assigned_bot_uid: suggestion.assigned_bot_uid,
                risk_level: suggestion.risk_level,
                acceptance_criteria: suggestion.acceptance_criteria,
                related_files: suggestion.related_files,
            },
        });
        Toast.Add.promise(promise, {
            loading: t("card.Creating child task"),
            success: t("successes.Child task created successfully."),
        });
    };

    return (
        <Flex direction="col" gap="2">
            <Box className="font-medium">{t("card.Suggestions")}</Box>
            <ul className="space-y-2 text-sm text-muted">
                {task.suggestions.map((suggestion, index) => (
                    <li key={`task-suggestion-${index}`} className="flex min-w-0 items-start justify-between gap-2">
                        <Box className="min-w-0 break-words">
                            {suggestion.title || t("card.Untitled suggestion")}
                            {suggestion.type ? ` - ${formatTaskMetadataValue(suggestion.type)}` : ""}
                            {suggestion.created_card_uid && (
                                <Badge variant="outline" className="ml-2 align-middle">
                                    {t("card.Task created")}
                                </Badge>
                            )}
                        </Box>
                        {canCreate && !suggestion.created_card_uid && suggestion.title && (
                            <Button
                                type="button"
                                size="icon-sm"
                                variant="ghost"
                                title={t("card.Create child task")}
                                aria-label={t("card.Create child task")}
                                disabled={createSuggestionTask.isPending}
                                onClick={() => handleCreateTask(suggestion)}
                            >
                                <PlusIcon className="size-4" />
                            </Button>
                        )}
                    </li>
                ))}
            </ul>
        </Flex>
    );
}

function TaskList({ title, items, monospace = false }: { title: string; items: string[]; monospace?: bool }): React.JSX.Element | null {
    if (!items.length) {
        return null;
    }

    return (
        <Flex direction="col" gap="1">
            <Box className="font-medium">{title}</Box>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
                {items.map((item, index) => (
                    <li key={`${title}-${index}`} className={monospace ? "break-all font-mono text-xs" : "break-words"}>
                        {item}
                    </li>
                ))}
            </ul>
        </Flex>
    );
}

function TaskLine({ label, children }: React.PropsWithChildren<{ label: string }>): React.JSX.Element {
    return (
        <Box className="break-words text-sm text-muted">
            <span className="font-medium text-foreground">{label}: </span>
            {children}
        </Box>
    );
}

function TaskLink({ label, href }: { label: string; href: string }): React.JSX.Element {
    return (
        <TaskLine label={label}>
            <a href={href} target="_blank" rel="noreferrer" className="break-all text-primary hover:underline">
                {href}
            </a>
        </TaskLine>
    );
}

BoardTaskMetadataSection.displayName = "Board.TaskMetadataSection";

export default BoardTaskMetadataSection;
