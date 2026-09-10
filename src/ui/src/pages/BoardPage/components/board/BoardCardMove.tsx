import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import Button from "@/components/base/Button";
import Sheet from "@/components/base/Sheet";
import IconComponent from "@/components/base/IconComponent";
import Toast from "@/components/base/Toast";
import { DISABLE_DRAGGING_ATTR } from "@/constants";
import useChangeCardOrder from "@/controllers/api/board/useChangeCardOrder";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { ProjectCard } from "@/core/models";
import { useBoard } from "@/core/providers/BoardProvider";
import { BOARD_CARD_TOUCH_HANDLE_ATTR } from "@/pages/BoardPage/components/board/BoardConstants";
import { nextCardOrder } from "@/pages/BoardPage/components/board/BoardGestureData";

export default function BoardCardMove({ card, compact }: { card: ProjectCard.TModel; compact: boolean }) {
    const { project, columns, cards, canDragCards } = useBoard();
    const columnUID = card.useField("project_column_uid");
    const title = card.useField("title");
    const [opened, setOpened] = useState(false);
    const busy = useRef(false);
    const [pending, setPending] = useState(false);
    const [t] = useTranslation();
    const queryClient = useQueryClient();
    const { mutateAsync } = useChangeCardOrder({ interceptToast: true });
    if (!canDragCards) return null;

    const move = (destinationUID: string) => {
        if (busy.current || destinationUID === columnUID || !columns.some((column) => column.uid === destinationUID && !column.is_archive)) return;
        busy.current = true;
        setPending(true);
        const order = nextCardOrder(cards, destinationUID);
        const promise = mutateAsync({ project_uid: project.uid, card_uid: card.uid, parent_uid: destinationUID, order }).then(async () => {
            await queryClient.invalidateQueries({ queryKey: [`get-cards-${project.uid}`] });
            setOpened(false);
        });
        Toast.Add.promise(promise, {
            loading: t("common.Updating..."),
            success: t("board.Card moved"),
            error: (error) => {
                const message = { message: "" };
                setupApiErrorHandler({}, message).handle(error);
                return message.message;
            },
            finally: () => {
                busy.current = false;
                setPending(false);
            },
        });
    };

    return (
        <Sheet.Root open={opened} onOpenChange={(value) => !busy.current && setOpened(value)}>
            <Sheet.Trigger asChild>
                <Button
                    variant="ghost"
                    className={compact ? "absolute right-0 top-0 size-11 p-0 md:hidden" : "absolute right-9 top-0 size-11 p-0 md:hidden"}
                    aria-label={t("board.Move card")}
                    title={t("board.Tap to move, hold to drag")}
                    {...{ [DISABLE_DRAGGING_ATTR]: "", [BOARD_CARD_TOUCH_HANDLE_ATTR]: "" }}
                    onClick={(event) => event.stopPropagation()}
                >
                    <IconComponent icon="grip-vertical" size="4" />
                </Button>
            </Sheet.Trigger>
            <Sheet.Content
                side="bottom"
                className="max-h-[80dvh] overflow-y-auto rounded-t-2xl pb-[max(1.5rem,env(safe-area-inset-bottom))]"
                onClick={(event) => event.stopPropagation()}
            >
                <Sheet.Header>
                    <Sheet.Title>{t("board.Move card")}</Sheet.Title>
                    <Sheet.Description className="break-words">{title}</Sheet.Description>
                </Sheet.Header>
                <div className="mt-4 flex flex-col gap-2">
                    {columns
                        .filter((column) => !column.is_archive)
                        .sort((a, b) => a.order - b.order)
                        .map((column) => (
                            <Button
                                key={column.uid}
                                variant="secondary"
                                className="min-h-11 justify-between"
                                disabled={pending || column.uid === columnUID}
                                onClick={() => move(column.uid)}
                            >
                                <span className="truncate">{column.name}</span>
                                {column.uid === columnUID && <IconComponent icon="check" size="4" />}
                            </Button>
                        ))}
                </div>
            </Sheet.Content>
        </Sheet.Root>
    );
}
