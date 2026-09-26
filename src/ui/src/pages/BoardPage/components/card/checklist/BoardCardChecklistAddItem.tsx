import Button from "@/components/base/Button";
import IconComponent from "@/components/base/IconComponent";
import Toast from "@/components/base/Toast";
import useCreateCardCheckitem from "@/controllers/api/card/checkitem/useCreateCardCheckitem";
import useCardCheckitemCreatedHandlers from "@/controllers/socket/card/checkitem/useCardCheckitemCreatedHandlers";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import useSwitchSocketHandlers from "@/core/hooks/useSwitchSocketHandlers";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { IBoardCardCheckRelatedContextParams } from "@/pages/BoardPage/components/card/checklist/types";
import { useRef } from "react";
import { useTranslation } from "react-i18next";

function BoardCardChecklistAddItem(): React.JSX.Element {
    const { socket, projectUID, card } = useBoardCard();
    const { model: checklist, params } = ModelRegistry.ProjectChecklist.useContext<IBoardCardCheckRelatedContextParams>();
    const { isValidating, setIsValidating } = params;
    const [t] = useTranslation();
    const { mutateAsync: createCheckitemMutateAsync } = useCreateCardCheckitem({ interceptToast: true });
    const isAddedRef = useRef(false);
    const handlers = useCardCheckitemCreatedHandlers({
        cardUID: card.uid,
        checklistUID: checklist.uid,
        callback: () => {
            if (!isAddedRef.current) {
                return;
            }

            isAddedRef.current = false;
            checklist.isOpenedInBoardCard = true;
        },
    });
    useSwitchSocketHandlers({ socket, handlers });

    const createCheckitem = () => {
        if (isValidating) {
            return;
        }

        setIsValidating(true);

        isAddedRef.current = true;

        const promise = createCheckitemMutateAsync({
            project_uid: projectUID,
            card_uid: card.uid,
            checklist_uid: checklist.uid,
            title: "New checkitem",
        });

        Toast.Add.promise(promise, {
            loading: t("common.Creating..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler({}, messageRef);

                handle(error);
                return messageRef.message;
            },
            success: () => {
                return t("successes.Checkitem added successfully.");
            },
            finally: () => {
                setIsValidating(false);
            },
        });
    };

    return (
        <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="inline-flex size-8 shrink-0"
            title={t("card.Add checkitem")}
            aria-label={t("card.Add checkitem")}
            onClick={() => createCheckitem()}
        >
            <IconComponent icon="plus" size="4" />
        </Button>
    );
}

export default BoardCardChecklistAddItem;
