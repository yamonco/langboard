import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Dialog from "@/components/base/Dialog";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Popover from "@/components/base/Popover";
import SubmitButton from "@/components/base/SubmitButton";
import Toast from "@/components/base/Toast";
import { PlateEditor } from "@/components/Editor/plate-editor";
import useArchiveCard from "@/controllers/api/card/useArchiveCard";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { ROUTES } from "@/core/routing/constants";
import { cn } from "@/core/utils/ComponentUtils";
import { useState } from "react";
import { useTranslation } from "react-i18next";

interface IBoardLinkedWikiCardProps {
    isExpanded: boolean;
    setIsExpanded?: React.Dispatch<React.SetStateAction<boolean>>;
    onClose?: () => void;
}

export default function BoardLinkedWikiCard({ isExpanded, setIsExpanded, onClose }: IBoardLinkedWikiCardProps) {
    const { card, projectUID, currentUser, canEditCard } = useBoardCard();
    const resource = card.useField("linked_resource");
    const columnName = card.useField("project_column_name");
    const navigate = usePageNavigateRef();
    const [t] = useTranslation();
    const [confirmOpen, setConfirmOpen] = useState(false);
    const { mutateAsync: removeCard, isPending: isRemoving } = useArchiveCard({ interceptToast: true });

    if (!resource) {
        return <></>;
    }

    const available = resource.status === "available";
    const title = available ? resource.title : resource.status === "forbidden" ? t("wiki.Restricted wiki") : t("wiki.Source unavailable");

    const handleRemove = async () => {
        const promise = removeCard({ project_uid: projectUID, card_uid: card.uid });
        Toast.Add.promise(promise, {
            loading: t("common.Updating..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler({}, messageRef);
                handle(error);
                return messageRef.message;
            },
            success: () => t("wiki.Linked card removed"),
            finally: () => setConfirmOpen(false),
        });
        try {
            await promise;
            navigate(ROUTES.BOARD.MAIN(projectUID), { replace: true });
        } catch {
            // The toast above owns the error presentation.
        }
    };

    return (
        <Flex direction="col" className="h-full min-h-0 gap-2">
            <Box
                className={cn(
                    "relative min-h-0 min-w-0 flex-1 overflow-hidden border bg-background px-4 py-4 sm:px-6 sm:py-6",
                    isExpanded ? "border-0 shadow-none" : "rounded-2xl shadow-2xl"
                )}
            >
                <Flex direction="col" className="h-full min-h-0">
                    <Dialog.Header className="relative mb-3 shrink-0 border-b pb-3 text-left">
                        <Flex items="center" gap="2" className="mb-2 text-amber-700 dark:text-amber-300">
                            <IconComponent icon={available ? "book-text" : "lock"} size="4" />
                            <span className="text-xs font-semibold uppercase tracking-[0.12em]">{t("wiki.Linked wiki")}</span>
                        </Flex>
                        <Dialog.Title className="break-words pr-24 text-xl font-semibold">{title}</Dialog.Title>
                        <Dialog.Description>{columnName}</Dialog.Description>
                        <Flex items="center" gap="1" className="absolute right-0 top-0">
                            {!!setIsExpanded && (
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    className="size-8"
                                    title={t(isExpanded ? "common.Collapse" : "common.Expand")}
                                    onClick={() => setIsExpanded((value) => !value)}
                                >
                                    <IconComponent icon={isExpanded ? "minimize-2" : "maximize-2"} size="4" />
                                </Button>
                            )}
                            {isExpanded ? (
                                <Button type="button" variant="ghost" size="icon" className="size-8" title={t("common.Close")} onClick={onClose}>
                                    <IconComponent icon="x" size="4" />
                                </Button>
                            ) : (
                                <Dialog.CloseButton className="inline-flex size-8 items-center justify-center" />
                            )}
                        </Flex>
                    </Dialog.Header>

                    <Box className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-amber-400/20 bg-amber-50/25 px-2 dark:bg-amber-950/10">
                        {available && resource.content ? (
                            <PlateEditor
                                value={resource.content}
                                readOnly
                                editorType="view"
                                form={{ project_uid: projectUID }}
                                currentUser={currentUser}
                                mentionables={[]}
                                className="min-h-full px-4 py-5 sm:px-6"
                            />
                        ) : (
                            <Flex direction="col" items="center" justify="center" gap="3" className="min-h-64 text-center text-muted-foreground">
                                <IconComponent icon={resource.status === "forbidden" ? "lock" : "file-question"} size="8" />
                                <p>{title}</p>
                            </Flex>
                        )}
                    </Box>

                    <Flex items="center" justify="between" gap="2" pt="3" wrap>
                        <Button variant="secondary" disabled={!available} onClick={() => navigate(ROUTES.BOARD.WIKI_PAGE(projectUID, resource.uid))}>
                            <IconComponent icon="external-link" size="4" />
                            {t("wiki.Open original")}
                        </Button>
                        {canEditCard && card.can_delete && (
                            <Popover.Root open={confirmOpen} onOpenChange={setConfirmOpen}>
                                <Popover.Trigger asChild>
                                    <Button variant="destructive">
                                        <IconComponent icon="unlink" size="4" />
                                        {t("wiki.Remove from board")}
                                    </Button>
                                </Popover.Trigger>
                                <Popover.Content align="end">
                                    <Box mb="2" textSize="sm" weight="semibold" className="max-w-72 text-center">
                                        {t("wiki.Remove linked card question")}
                                    </Box>
                                    <Flex items="center" justify="end" gap="1">
                                        <Button variant="secondary" size="sm" disabled={isRemoving} onClick={() => setConfirmOpen(false)}>
                                            {t("common.Cancel")}
                                        </Button>
                                        <SubmitButton variant="destructive" size="sm" isValidating={isRemoving} onClick={handleRemove}>
                                            {t("wiki.Remove from board")}
                                        </SubmitButton>
                                    </Flex>
                                </Popover.Content>
                            </Popover.Root>
                        )}
                    </Flex>
                </Flex>
            </Box>
        </Flex>
    );
}
