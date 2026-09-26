import { useCallback, useEffect, useRef, useState } from "react";
import { isAxiosError } from "axios";
import { dropTargetForElements } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import { Routing } from "@langboard/core/constants";
import { EHttpStatus } from "@langboard/core/enums";
import Button from "@/components/base/Button";
import Dialog from "@/components/base/Dialog";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Popover from "@/components/base/Popover";
import Toast from "@/components/base/Toast";
import useChangeCardCheckitemStatus from "@/controllers/api/card/checkitem/useChangeCardCheckitemStatus";
import { api } from "@/core/helpers/Api";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { Project, ProjectCard, ProjectCheckitem } from "@/core/models";
import { cn } from "@/core/utils/ComponentUtils";
import { Utils } from "@langboard/core/utils";
import { ROUTES } from "@/core/routing/constants";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { BOARD_DND_SYMBOL_SET } from "@/pages/BoardPage/components/board/BoardConstants";
import { draggedBoardCard } from "@/pages/BoardPage/components/board/BoardGestureData";

interface IWorkItem {
    uid: string;
    card_uid: string;
    title: string;
    status: ProjectCheckitem.ECheckitemStatus;
    timer_started_at?: string;
    accumulated_seconds?: number;
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

export default function BoardWorkIsland({ project, dragging }: { project: Project.TModel; dragging: bool }) {
    const targetRef = useRef<HTMLButtonElement>(null);
    const navigate = usePageNavigateRef();
    const [over, setOver] = useState(false);
    const [activeWork, setActiveWork] = useState<IActiveWork[]>([]);
    const [candidateCard, setCandidateCard] = useState<ProjectCard.TModel>();
    const [candidates, setCandidates] = useState<ICardCheckitem[]>([]);
    const [conflictTarget, setConflictTarget] = useState<ICardCheckitem>();
    const [busy, setBusy] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false);
    const [loadingWork, setLoadingWork] = useState(false);
    const [workError, setWorkError] = useState(false);
    const [now, setNow] = useState(Date.now());
    const { mutateAsync: changeStatus } = useChangeCardCheckitemStatus({ interceptToast: true });

    const refreshActiveWork = useCallback(async () => {
        setLoadingWork(true);
        try {
            const res = await api.get<{ active_work: IActiveWork[] }>(Routing.API.DASHBOARD.ACTIVE_WORK, {
                env: { interceptToast: true } as never,
            });
            setActiveWork(res.data.active_work ?? []);
            setWorkError(false);
        } catch {
            setWorkError(true);
        } finally {
            setLoadingWork(false);
        }
    }, []);

    useEffect(() => {
        void refreshActiveWork();
        const refreshVisible = () => {
            if (!document.hidden) void refreshActiveWork();
        };
        window.addEventListener("focus", refreshVisible);
        document.addEventListener("visibilitychange", refreshVisible);
        const interval = window.setInterval(refreshVisible, 15_000);
        return () => {
            window.removeEventListener("focus", refreshVisible);
            document.removeEventListener("visibilitychange", refreshVisible);
            window.clearInterval(interval);
        };
    }, [refreshActiveWork]);

    useEffect(() => {
        if (!menuOpen || !activeWork.length) return;
        setNow(Date.now());
        const interval = window.setInterval(() => setNow(Date.now()), 1_000);
        return () => window.clearInterval(interval);
    }, [menuOpen, activeWork.length]);

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
                    setCandidateCard(card);
                    setCandidates(next);
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
                const card = ProjectCard.Model.getModels((model) => model.uid === uid && model.project_uid === project.uid && !model.archived_at)[0];
                if (card) void acceptCard(card);
            },
        });
    }, [acceptCard, project.uid]);

    const dialogOpen = !!candidateCard && (candidates.length > 1 || !!conflictTarget);
    const currentLabel = current ? `${current.card.title} · ${current.checkitem.title}` : "My Work";

    return (
        <>
            <Popover.Root
                open={menuOpen}
                onOpenChange={(open) => {
                    setMenuOpen(open);
                    if (open) void refreshActiveWork();
                }}
            >
                <Popover.Trigger asChild>
                    <Button
                        ref={targetRef}
                        type="button"
                        variant={over ? "default" : current ? "secondary" : "ghost"}
                        disabled={busy}
                        className={cn(
                            "h-11 min-w-0 shrink-0 gap-1 rounded-xl px-2 transition-[width,background-color,transform] duration-200 md:gap-2 md:rounded-full md:px-3",
                            dragging ? "min-w-44 border border-dashed border-primary/60 md:px-4" : "min-w-0",
                            over && "scale-[1.03]"
                        )}
                        aria-label={over ? "Release to start work" : currentLabel}
                    >
                        <IconComponent icon="hammer" size="4" />
                        <span className={cn("max-w-16 truncate text-xs md:max-w-44", !dragging && !current && "md:max-w-20")}>
                            {over ? "Release to start work" : dragging ? "Drop to start work" : currentLabel}
                        </span>
                    </Button>
                </Popover.Trigger>
                <Popover.Content side="top" align="end" className="w-[min(22rem,calc(100vw-1rem))] p-3">
                    <div className="mb-2 text-sm font-semibold">My Work</div>
                    {loadingWork && !activeWork.length ? (
                        <div className="py-2 text-xs text-muted-foreground">작업을 불러오는 중...</div>
                    ) : workError ? (
                        <Button variant="ghost" size="sm" onClick={() => void refreshActiveWork()}>
                            작업을 불러오지 못했습니다. 다시 시도
                        </Button>
                    ) : activeWork.length ? (
                        <div className="max-h-64 space-y-1 overflow-y-auto">
                            {activeWork.map((work) => {
                                const elapsed = Math.max(
                                    0,
                                    (work.checkitem.accumulated_seconds ?? 0) +
                                        (work.checkitem.timer_started_at
                                            ? Math.floor((now - Date.parse(work.checkitem.timer_started_at)) / 1_000)
                                            : 0)
                                );
                                const duration = [Math.floor(elapsed / 3_600), Math.floor((elapsed % 3_600) / 60), elapsed % 60]
                                    .map((part) => String(part).padStart(2, "0"))
                                    .join(":");
                                return (
                                    <button
                                        key={work.checkitem.uid}
                                        type="button"
                                        className="w-full rounded-md p-2 text-left hover:bg-muted"
                                        onClick={() => {
                                            setMenuOpen(false);
                                            navigate(ROUTES.BOARD.CARD(work.card.project_uid, work.card.uid));
                                        }}
                                    >
                                        <div className="truncate text-xs text-muted-foreground">
                                            {work.project.title} · {work.card.title}
                                        </div>
                                        <div className="flex items-center justify-between gap-2 text-sm">
                                            <span className="truncate">{work.checkitem.title}</span>
                                            <span className="shrink-0 font-mono text-xs tabular-nums">{duration}</span>
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                    ) : (
                        <div className="py-2 text-xs text-muted-foreground">실행 중인 작업이 없습니다.</div>
                    )}
                    <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="mt-2 w-full justify-start"
                        onClick={() => {
                            setMenuOpen(false);
                            navigate(ROUTES.DASHBOARD.TRACKING, { smooth: true });
                        }}
                    >
                        모든 작업 보기
                    </Button>
                </Popover.Content>
            </Popover.Root>

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
                            <Button type="button" disabled={busy} onClick={() => void start(candidateCard, conflictTarget, true)}>
                                기존 작업 일시정지 후 전환
                            </Button>
                        </Dialog.Footer>
                    )}
                </Dialog.Content>
            </Dialog.Root>
        </>
    );
}
