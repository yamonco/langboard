import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Popover from "@/components/base/Popover";
import SubmitButton from "@/components/base/SubmitButton";
import Toast from "@/components/base/Toast";
import useDeleteCard from "@/controllers/api/card/useDeleteCard";
import { deleteCardModel } from "@/core/helpers/ModelHelper";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { ROUTES } from "@/core/routing/constants";
import { ISharedBoardCardActionProps } from "@/pages/BoardPage/components/card/action/types";
import { memo, useState } from "react";
import { useTranslation } from "react-i18next";

export interface IBoardCardActionDeleteProps extends ISharedBoardCardActionProps {}

const BoardCardActionDelete = memo(({ buttonClassName }: IBoardCardActionDeleteProps) => {
    const { projectUID, card } = useBoardCard();
    const [t] = useTranslation();
    const [isValidating, setIsValidating] = useState(false);
    const [isOpened, setIsOpened] = useState(false);
    const navigate = usePageNavigateRef();
    const { mutateAsync } = useDeleteCard({ interceptToast: true });

    const deleteCard = () => {
        if (isValidating) {
            return;
        }

        setIsValidating(true);

        const promise = mutateAsync({
            project_uid: projectUID,
            card_uid: card.uid,
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
                deleteCardModel(card.uid, true);
                setTimeout(() => {
                    navigate(ROUTES.BOARD.MAIN(projectUID), { replace: true });
                }, 0);
                return t("successes.Card deleted successfully.");
            },
            finally: () => {
                setIsValidating(false);
                setIsOpened(false);
            },
        });
    };

    const changeOpenState = (state: bool) => {
        if (isValidating) {
            return;
        }

        setIsOpened(state);
    };

    return (
        <Popover.Root open={isOpened} onOpenChange={changeOpenState}>
            <Popover.Trigger asChild>
                <Button variant="destructive" className={buttonClassName}>
                    <IconComponent icon="x" size="4" />
                    {t("card.Delete card")}
                </Button>
            </Popover.Trigger>
            <Popover.Content align="end">
                <Box mb="1" textSize={{ initial: "sm", sm: "base" }} weight="semibold" className="text-center">
                    {t("ask.Are you sure you want to delete this card?")}
                </Box>
                <Box maxW="full" textSize="sm" weight="bold" className="text-center text-red-500">
                    {t("common.deleteDescriptions.All data will be lost.")}
                </Box>
                <Box maxW="full" textSize="sm" weight="bold" className="text-center text-red-500">
                    {t("common.deleteDescriptions.This action cannot be undone.")}
                </Box>
                <Flex items="center" justify="end" gap="1" mt="2">
                    <Button type="button" variant="secondary" size="sm" disabled={isValidating} onClick={() => setIsOpened(false)}>
                        {t("common.Cancel")}
                    </Button>
                    <SubmitButton type="button" variant="destructive" size="sm" onClick={deleteCard} isValidating={isValidating}>
                        {t("common.Delete")}
                    </SubmitButton>
                </Flex>
            </Popover.Content>
        </Popover.Root>
    );
});

export default BoardCardActionDelete;
