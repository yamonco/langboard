import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { isAxiosError } from "axios";
import { dropTargetForElements } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import { Routing } from "@langboard/core/constants";
import { EHttpStatus } from "@langboard/core/enums";
import Button from "@/components/base/Button";
import Dialog from "@/components/base/Dialog";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Toast from "@/components/base/Toast";
import useChangeCardCheckitemStatus from "@/controllers/api/card/checkitem/useChangeCardCheckitemStatus";
import { api } from "@/core/helpers/Api";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { Project, ProjectCard, ProjectCheckitem } from "@/core/models";
import { cn } from "@/core/utils/ComponentUtils";
import { Utils } from "@langboard/core/utils";
import { BOARD_DND_SYMBOL_SET } from "@/pages/BoardPage/components/board/BoardConstants";
import { draggedBoardCard } from "@/pages/BoardPage/components/board/BoardGestureData";

interface IWorkItem {
    uid: string;
    card_uid: string;
    title: string;
    status: ProjectCheckitem.ECheckitemStatus;
    timer_started_at?: string;
}

interface IActiveWork {
    checkitem: IWorkItem;
    card: {
        uid: string;
        title: string;
        project_uid: string;
    };
    project: {
        uid: string;
        title: string;
    };
}

interface ICardCheckitem {
    uid: string;
    title: string;
    is_checked: bool;
    cardified_card?: unknown;
}

interface ICardDetailsResponse {
    checklists: Array<{
        checkitems?: ICardCheckitem[];
    }>;
}

export default function BoardWorkIsland({
    project,
    dragging,
}: {
    project: Project.TModel;
    dragging: bool;
}) {
    const targetRef = useRef<HTMLButtonElement>(null);
    const [over, setOver] = useState(false);
    const [activeWork, setActiveWork] = useState<IActiveWork[]>([]);
    const [candidateCard, setCandidateCard] = useState<ProjectCard.TModel>();
    const [candidates, setCandidates] = useState<ICardCheckitem[]>([]);
    const [conflictTarget, setConflictTarget] = useState<ICardCheckitem>();
    const [busy, setBusy] = useState(false);
    const { mutateAsync: changeStatus } = useChangeCardCheckitemStatus({ interceptToast: true });

    const refreshActiveWork = useCallback(async () => {
        const res = await api.get<{ active_work: IActiveWork[] }>(Routing.API.DASHBOARD.ACTIVE_WORK, {
            env: { interceptToast: true } as never,
        });
        setActiveWork(res.data.active_work ?? []);
    }, []);

    useEffect(() => {
        void refreshActiveWork().catch(() => undefined);
    }, [refreshActiveWork]);

    const current = activeWork[0];

    const start = useCallback(
        async (card: ProjectCard.TModel, checkitem: ICardCheckitem, replaceActive = false) => {
            if (busy) return;
            setBusy(true);
            try {
                await changeStatus({
                    project_uid: project.uid,
                    card_uid: card.uid,
                    checkitem_uid: checkitem.uid,
                    status: ProjectCheckitem.ECheckitemStatus.Started,
                    replace_active: replaceActive,
                });
                setConflictTarget(undefined);
                setCandidateCard(undefined);
                setCandidates([]);
                await refreshActiveWork();
            } catch (error) {
                if (isAxiosError(error) && error.response?.status === EHttpStatus.HTTP_409_CONFLICT) {
                    await refreshActiveWork();
                    setConflictTarget(checkitem);
                    return;
                }
                const messageRef = { message: "" };
                setupApiErrorHandler({}, messageRef).handle(error);
                Toast.Add.error(messageRef.message);
            } finally {
                setBusy(false);
            }
        },
        [busy, changeStatus, project.uid, refreshActiveWork]
    );

    const acceptCard = useCallback(
        async (card: ProjectCard.TModel) => {
            if (busy) return;
            setBusy(true);
            try {
                const url = Utils.String.format(Routing.API.BOARD.CARD.GET_DETAILS, {
                    uid: project.uid,
                    card_uid: card.uid,
                });
                const res = await api.get<ICardDetailsResponse>(url, {
                    env: { interceptToast: true } as never,
                });
                const next = res.data.checklists
                    .flatMap((checklist) => checklist.checkitems ?? [])
                    .filter((checkitem) => !checkitem.is_checked && !checkitem.cardified_card);

                if (!next.length) {
                    Toast.Add.info("이 카드에는 시작할 수 있는 체크리스트 작업이 없습니다.");
                    return;
                }
                if (next.length === 1) {
                    setBusy(false);
                    await start(card, next[0]);
                    return;
                }
                setCandidateCard(card);
                setCandidates(next);
            } catch (error) {
                const messageRef = { message: "" };
                setupApiErrorHandler({}, messageRef).handle(error);
                Toast.Add.error(messageRef.message);
            } finally {
                setBusy(false);
            }
        },
        [busy, project.uid, start]
    );

    useEffect(() => {
        if (!targetRef.current) return;
        return dropTargetForElements({
            element: targetRef.current,
            canDrop: ({ source }) =>
                window.matchMedia("(min-width: 768px) and (pointer: fine)").matches &&
                !!draggedBoardCard(source.data, BOARD_DND_SYMBOL_SET.row, project.uid),
            getData: () => ({ type: "board-card-work-island" }),
            onDragEnter: () => setOver(true),
            onDragLeave: () => setOver(false),
            onDrop: ({ source }) => {
                setOver(false);
                const uid = draggedBoardCard(source.data, BOARD_DND_SYMBOL_SET.row, project.uid);
                if (!uid) return;
                const card = ProjectCard.Model.getModels(
                    (model) => model.uid === uid && model.project_uid === project.uid && !model.archived_at
                )[0];
                if (card) void acceptCard(card);
            },
        });
    }, [acceptCard, project.uid]);

    const dialogOpen = !!candidateCard && (candidates.length > 1 || !!conflictTarget);
    const currentLabel = current ? `${current.card.title} · ${current.checkitem.title}` : "My Work";

    return (
        <>
            <Button
                ref={targetRef}
                type="button"
                variant={over ? "default" : current ? "secondary" : "ghost"}
                disabled={busy}
                className={cn(
                    "h-11 shrink-0 gap-2 rounded-full px-3 transition-[width,background-color,transform] duration-200",
                    dragging ? "min-w-44 border border-dashed border-primary/60 md:px-4" : "min-w-0",
                    over && "scale-[1.03]"
                )}
                aria-label={over ? "Release to start work" : currentLabel}
                onClick={() => {
                    if (current) {
                        window.dispatchEvent(new CustomEvent("langboard:open-my-work"));
                    }
                }}
            >
                <IconComponent icon="hammer" size="4" />
                <span className={cn("max-w-44 truncate text-xs", !dragging && !current && "md:max-w-20")}>
                    {over ? "Release to start work" : dragging ? "Drop to start work" : currentLabel}
                </span>
            </Button>

            <Dialog.Root
                open={dialogOpen}
                onOpenChange={(open) => {
                    if (!open) {
                        setCandidateCard(undefined);
                        setCandidates([]);
                        setConflictTarget(undefined);
                    }
                }}
            >
                <Dialog.Content className="sm:max-w-md">
                    <Dialog.Header>
                        <Dialog.Title>{conflictTarget ? "작업 전환" : "작업 항목 선택"}</Dialog.Title>
                        <Dialog.Description>
                            {conflictTarget
                                ? "이미 진행 중인 작업이 있습니다. 기존 작업을 일시정지하고 새 작업으로 전환합니다."
                                : candidateCard?.title}
                        </Dialog.Description>
                    </Dialog.Header>

                    {conflictTarget && current ? (
                        <Flex direction="col" gap="3" mt="4">
                            <div className="rounded-lg border bg-muted/40 p-3 text-sm">
                                <div className="text-xs text-muted-foreground">현재 작업</div>
                                <div className="mt-1 font-medium">{current.card.title}</div>
                                <div className="mt-1 text-xs text-muted-foreground">{current.checkitem.title}</div>
                            </div>
                            <div className="rounded-lg border p-3 text-sm">
                                <div className="text-xs text-muted-foreground">새 작업</div>
                                <div className="mt-1 font-medium">{candidateCard?.title}</div>
                                <div className="mt-1 text-xs text-muted-foreground">{conflictTarget.title}</div>
                            </div>
                        </Flex>
                    ) : (
                        <Flex direction="col" gap="1" mt="4">
                            {candidates.map((checkitem) => (
                                <Button
                                    key={checkitem.uid}
                                    type="button"
                                    variant="ghost"
                                    className="justify-start rounded-lg"
                                    disabled={busy}
                                    onClick={() => candidateCard && void start(candidateCard, checkitem)}
                                >
                                    <IconComponent icon="play" size="4" />
                                    <span className="truncate">{checkitem.title}</span>
                                </Button>
                            ))}
                        </Flex>
                    )}

                    {conflictTarget && candidateCard && (
                        <Dialog.Footer className="mt-5">
                            <Button
                                type="button"
                                variant="outline"
                                disabled={busy}
                                onClick={() => {
                                    setCandidateCard(undefined);
                                    setCandidates([]);
                                    setConflictTarget(undefined);
                                }}
                            >
                                취소
                            </Button>
                            <Button
                                type="button"
                                disabled={busy}
                                onClick={() => void start(candidateCard, conflictTarget, true)}
                            >
                                기존 작업 일시정지 후 전환
                            </Button>
                        </Dialog.Footer>
                    )}
                </Dialog.Content>
            </Dialog.Root>
        </>
    );
}
