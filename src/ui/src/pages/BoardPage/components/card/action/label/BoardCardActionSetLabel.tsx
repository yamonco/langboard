import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import { ICollaborativeTextMeta, useCollaborativeText } from "@/components/Collaborative/useCollaborativeText";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Popover from "@/components/base/Popover";
import SubmitButton from "@/components/base/SubmitButton";
import Toast from "@/components/base/Toast";
import useUpdateCardLabels from "@/controllers/api/card/useUpdateCardLabels";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { ProjectRole } from "@/core/models/roles";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { parseCollaborativeStringList } from "@/core/utils/CollaborativeSelectionUtils";
import BoardCardActionLabelList from "@/pages/BoardPage/components/card/action/label/BoardCardActionLabelList";
import { ISharedBoardCardActionProps } from "@/pages/BoardPage/components/card/action/types";
import { EEditorCollaborationType } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import { memo, useState } from "react";
import { useTranslation } from "react-i18next";

export interface IBoardCardActionSetLabelProps extends ISharedBoardCardActionProps {}

interface ILabelToggleMeta {
    checked: bool;
    labelUID: string;
    updatedAt: number;
}

const BoardCardActionSetLabel = memo(({ buttonClassName }: IBoardCardActionSetLabelProps) => {
    const { projectUID, card, hasRoleAction } = useBoardCard();
    const labels = card.useForeignFieldArray("labels");
    const [t] = useTranslation();
    const [isOpened, setIsOpened] = useState(false);
    const [isValidating, setIsValidating] = useState(false);
    const { mutateAsync: updateCardLabelsMutateAsync } = useUpdateCardLabels({ interceptToast: true });
    const currentCardLabelUIDs = labels.map((label) => label.uid);
    const defaultSelectedLabelUIDs = JSON.stringify(currentCardLabelUIDs);
    const { isSynced, remoteMeta, updateMeta, updateValue, value } = useCollaborativeText({
        defaultValue: defaultSelectedLabelUIDs,
        disabled: !isOpened,
        collaborationType: EEditorCollaborationType.Card,
        uid: card.uid,
        section: "labels",
        field: "selected-label-uids",
    });
    const isWaitingForSync = isOpened && !isSynced;
    const selectedLabelUIDs = parseCollaborativeStringList(value, currentCardLabelUIDs);
    const remoteLabelStates = remoteMeta.reduce<Record<string, ICollaborativeTextMeta<ILabelToggleMeta>>>((acc, meta) => {
        const value = meta.value;
        if (
            !value ||
            !Utils.Type.isObject(value) ||
            !Utils.Type.isString((value as Record<string, unknown>).labelUID) ||
            !Utils.Type.isBool((value as Record<string, unknown>).checked) ||
            !Utils.Type.isNumber((value as Record<string, unknown>).updatedAt)
        ) {
            return acc;
        }

        const parsedMeta = meta as ICollaborativeTextMeta<ILabelToggleMeta>;
        const previousMeta = acc[parsedMeta.value.labelUID];
        if (!previousMeta || previousMeta.value.updatedAt < parsedMeta.value.updatedAt) {
            acc[parsedMeta.value.labelUID] = parsedMeta;
        }

        return acc;
    }, {});

    const changeOpenedState = (opened: bool) => {
        if (isValidating) {
            return;
        }

        if (!opened) {
            updateMeta(null);
        }
        setIsOpened(opened);
    };

    const handleSelectedLabelUIDsChange: React.Dispatch<React.SetStateAction<string[]>> = (value) => {
        if (isWaitingForSync) {
            return;
        }

        const nextValue = Utils.Type.isFunction(value) ? value(selectedLabelUIDs) : value;
        const changedLabelUID =
            selectedLabelUIDs.find((uid) => !nextValue.includes(uid)) || nextValue.find((uid) => !selectedLabelUIDs.includes(uid));
        if (changedLabelUID) {
            updateMeta({
                checked: nextValue.includes(changedLabelUID),
                labelUID: changedLabelUID,
                updatedAt: Date.now(),
            } satisfies ILabelToggleMeta);
        }
        updateValue(JSON.stringify(nextValue));
    };

    const updateLabels = () => {
        if (isValidating || isWaitingForSync) {
            return;
        }

        setIsValidating(true);

        const promise = updateCardLabelsMutateAsync({
            project_uid: projectUID,
            card_uid: card.uid,
            labels: selectedLabelUIDs,
        });

        Toast.Add.promise(promise, {
            loading: t("common.Updating..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler({}, messageRef);

                handle(error);
                return messageRef.message;
            },
            success: () => {
                return t("successes.Labels updated successfully.");
            },
            finally: () => {
                setIsValidating(false);
                setIsOpened(false);
            },
        });
    };

    if (!hasRoleAction(ProjectRole.EAction.CardUpdate)) {
        return null;
    }

    return (
        <Popover.Root modal open={isOpened} onOpenChange={changeOpenedState}>
            <Popover.Trigger asChild>
                <Button variant="outline" className={buttonClassName} aria-label={t("card.Add labels")}>
                    <IconComponent icon="plus" size="3" />
                    {t("card.Add labels")}
                </Button>
            </Popover.Trigger>
            <Popover.Content align="start" sideOffset={8} className="w-[min(340px,calc(100vw-24px))] rounded-xl p-3 shadow-xl">
                <Flex items="center" justify="between" mb="2">
                    <Flex items="center" gap="2">
                        <IconComponent icon="tags" size="4" />
                        <Box textSize="sm" weight="semibold">
                            {t("card.Labels")}
                        </Box>
                    </Flex>
                    <Box textSize="xs" className="rounded-full bg-secondary px-2 py-0.5 text-muted-foreground">
                        {selectedLabelUIDs.length}
                    </Box>
                </Flex>
                <Box mb="3" textSize="xs" className="text-muted-foreground">
                    {t("card.Select labels to attach or remove, then save.")}
                </Box>
                <BoardCardActionLabelList
                    disabled={isWaitingForSync || isValidating}
                    remoteLabelStates={remoteLabelStates}
                    selectedLabelUIDs={selectedLabelUIDs}
                    setSelectedLabelUIDs={handleSelectedLabelUIDsChange}
                />
                {isWaitingForSync && (
                    <Box mt="2" textSize="xs" className="text-muted-foreground">
                        {t("common.Syncing draft...")}
                    </Box>
                )}
                <Flex items="center" justify="end" gap="1" mt="2">
                    <Button type="button" variant="secondary" size="sm" disabled={isValidating} onClick={() => changeOpenedState(false)}>
                        {t("common.Cancel")}
                    </Button>
                    <SubmitButton type="button" size="sm" onClick={updateLabels} isValidating={isValidating} disabled={isWaitingForSync}>
                        {t("common.Save")}
                    </SubmitButton>
                </Flex>
            </Popover.Content>
        </Popover.Root>
    );
});

export default BoardCardActionSetLabel;
