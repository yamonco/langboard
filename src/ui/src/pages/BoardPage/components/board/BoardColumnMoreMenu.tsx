import Box from "@/components/base/Box";
import DropdownMenu from "@/components/base/DropdownMenu";
import Toast from "@/components/base/Toast";
import MoreMenu from "@/components/MoreMenu";
import NotificationSetting from "@/components/NotificationSetting";
import { DISABLE_DRAGGING_ATTR } from "@/constants";
import useDeleteProjectColumn from "@/controllers/api/board/useDeleteProjectColumn";
import useReplaceProjectColumnDock from "@/controllers/api/board/useReplaceProjectColumnDock";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { ProjectColumn } from "@/core/models";
import { pinnedProjectDockColumns } from "@/core/models/projectDock";
import { ProjectRole } from "@/core/models/roles";
import { useBoard } from "@/core/providers/BoardProvider";
import BoardColumnMoreMenuBotList from "@/pages/BoardPage/components/board/BoardColumnMoreMenuBotList";
import BoardColumnMoreMenuBotScope from "@/pages/BoardPage/components/board/BoardColumnMoreMenuBotScope";
import { memo, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";

export interface IBoardColumnMoreMenuProps {
    column: ProjectColumn.TModel;
    onRenameStart?: () => void;
}

const BoardColumnMoreMenu = memo(({ column, onRenameStart }: IBoardColumnMoreMenuProps) => {
    const { project, currentUser, hasRoleAction } = useBoard();
    const canEdit = hasRoleAction(ProjectRole.EAction.Update) && !column.is_archive;
    const isAdmin = currentUser.useField("is_admin");
    const canPin = (isAdmin || hasRoleAction(ProjectRole.EAction.Update)) && !column.is_archive;
    const shouldKeepRenameFocusRef = useRef(false);
    const handleCloseAutoFocus = useCallback((e: Event) => {
        if (!shouldKeepRenameFocusRef.current) {
            return;
        }

        e.preventDefault();
        shouldKeepRenameFocusRef.current = false;
    }, []);
    const handleRenameStart = useCallback(() => {
        shouldKeepRenameFocusRef.current = true;
        onRenameStart?.();
    }, [onRenameStart]);

    return (
        <MoreMenu.Root
            triggerProps={{ className: "size-7", ...{ [DISABLE_DRAGGING_ATTR]: "" } }}
            contentProps={{ className: "w-min p-0", onCloseAutoFocus: handleCloseAutoFocus, ...{ [DISABLE_DRAGGING_ATTR]: "" } }}
        >
            <NotificationSetting.SpecificScopedPopover
                type="column"
                currentUser={currentUser}
                specificUID={column.uid}
                modal
                form={{
                    project_uid: project.uid,
                    project_column_uid: column.uid,
                }}
                triggerProps={{
                    variant: "ghost",
                    className: "w-full justify-start rounded-none px-2 py-1.5 font-normal",
                    role: "menuitem",
                }}
                iconProps={{
                    className: "hidden",
                }}
                showTriggerText
                onlyPopover
            />
            {canEdit && <BoardColumnMoreMenuRename onRenameStart={handleRenameStart} />}
            {canPin && <BoardColumnMoreMenuDock column={column} />}
            {hasRoleAction(ProjectRole.EAction.Update) && <BoardColumnMoreMenuBotScope column={column} />}
            {canEdit && <BoardColumnMoreMenuDelete column={column} />}
            {hasRoleAction(ProjectRole.EAction.Update) && <BoardColumnMoreMenuBotList column={column} />}
        </MoreMenu.Root>
    );
});
BoardColumnMoreMenu.displayName = "Board.ColumnMore";

const BoardColumnMoreMenuDock = memo(({ column }: IBoardColumnMoreMenuProps) => {
    const [t] = useTranslation();
    const { project } = useBoard();
    const dockOrder = column.useField("dock_order");
    const { mutateAsync, isPending } = useReplaceProjectColumnDock({ interceptToast: true });
    const pending = useRef(false);
    const toggle = (event: Event) => {
        event.preventDefault();
        if (pending.current) return;
        pending.current = true;
        const pinned = pinnedProjectDockColumns(ProjectColumn.Model.getModels((item) => item.project_uid === project.uid)).map((item) => item.uid);
        const columnUIDs = dockOrder != null ? pinned.filter((uid) => uid !== column.uid) : [...pinned, column.uid];
        Toast.Add.promise(mutateAsync({ project_uid: project.uid, column_uids: columnUIDs, expected_revision: project.dock_revision }), {
            loading: t("common.Updating..."),
            success: t("board.Dock updated"),
            error: (error) => {
                const message = { message: "" };
                setupApiErrorHandler({}, message).handle(error);
                return message.message;
            },
            finally: () => {
                pending.current = false;
            },
        });
    };
    return (
        <DropdownMenu.Item onSelect={toggle} disabled={isPending} {...{ [DISABLE_DRAGGING_ATTR]: "" }}>
            {t(dockOrder != null ? "board.Unpin from dock" : "board.Pin to dock")}
        </DropdownMenu.Item>
    );
});
BoardColumnMoreMenuDock.displayName = "Board.ColumnMoreDock";

const BoardColumnMoreMenuRename = memo(({ onRenameStart }: Pick<IBoardColumnMoreMenuProps, "onRenameStart">) => {
    const [t] = useTranslation();
    const { setIsOpened } = MoreMenu.useMoreMenu();

    const handleRename = useCallback(
        (e: Event) => {
            e.preventDefault();
            setIsOpened(false);
            requestAnimationFrame(() => {
                onRenameStart?.();
            });
        },
        [onRenameStart, setIsOpened]
    );

    return (
        <DropdownMenu.Item onSelect={handleRename} {...{ [DISABLE_DRAGGING_ATTR]: "" }}>
            {t("project.settings.Rename")}
        </DropdownMenu.Item>
    );
});
BoardColumnMoreMenuRename.displayName = "Board.ColumnMoreRename";

const BoardColumnMoreMenuDelete = memo(({ column }: IBoardColumnMoreMenuProps) => {
    const [t] = useTranslation();
    const { project } = useBoard();
    const { mutateAsync } = useDeleteProjectColumn({ interceptToast: true });

    const deleteColumn = (endCallback: (shouldClose: bool) => void) => {
        const promise = mutateAsync({
            project_uid: project.uid,
            project_column_uid: column.uid,
        });

        Toast.Add.promise(promise, {
            loading: t("common.Deleting..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler({}, messageRef);

                handle(error);
                return messageRef.message;
            },
            success: () => {
                return t("successes.Column deleted successfully.");
            },
            finally: () => {
                endCallback(true);
            },
        });
    };

    return (
        <MoreMenu.PopoverItem
            modal
            contentProps={{ align: "center", ...{ [DISABLE_DRAGGING_ATTR]: "" } }}
            menuName={t("project.Delete column")}
            saveText={t("common.Delete")}
            saveButtonProps={{ variant: "destructive" }}
            onSave={deleteColumn}
        >
            <Box mb="1" textSize={{ initial: "sm", sm: "base" }} weight="semibold" className="text-center">
                {t("ask.Are you sure you want to delete this column?")}
            </Box>
            <Box maxW="full" textSize="sm" weight="bold" className="text-center text-red-500">
                {t("project.All cards in this column will be archived.")}
            </Box>
            <Box maxW="full" textSize="sm" weight="bold" className="text-center text-red-500">
                {t("common.deleteDescriptions.This action cannot be undone.")}
            </Box>
        </MoreMenu.PopoverItem>
    );
});
BoardColumnMoreMenuDelete.displayName = "Board.ColumnMoreDelete";

export default BoardColumnMoreMenu;
