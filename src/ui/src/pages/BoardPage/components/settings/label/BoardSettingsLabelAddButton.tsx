import SubmitButton from "@/components/base/SubmitButton";
import Toast from "@/components/base/Toast";
import useCreateProjectLabel from "@/controllers/api/board/settings/useCreateProjectLabel";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { useBoardSettings } from "@/core/providers/BoardSettingsProvider";
import { Utils } from "@langboard/core/utils";
import { useState } from "react";
import { useTranslation } from "react-i18next";

function BoardSettingsLabelAddButton() {
    const { project } = useBoardSettings();
    const [t] = useTranslation();
    const [isValidating, setIsValidating] = useState(false);
    const { mutateAsync: createProjectLabelMutateAsync } = useCreateProjectLabel({ interceptToast: true });

    const createLabel = () => {
        if (isValidating) {
            return;
        }

        setIsValidating(true);

        const promise = createProjectLabelMutateAsync({
            project_uid: project.uid,
            name: t("project.settings.New Label"),
            color: new Utils.Color.Generator(Utils.String.Token.shortUUID()).generateRandomColor(),
            description: t("project.settings.Sample label description"),
        });

        Toast.Add.promise(promise, {
            loading: t("common.Adding..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler({}, messageRef);

                handle(error);
                return messageRef.message;
            },
            success: () => {
                return t("successes.Label added successfully.");
            },
            finally: () => {
                setIsValidating(false);
            },
        });
    };

    return (
        <SubmitButton
            type="button"
            isValidating={isValidating}
            variant="outline"
            className="mb-4 w-full border-2 border-dashed"
            onClick={createLabel}
        >
            {t("project.settings.Add a label")}
        </SubmitButton>
    );
}

export default BoardSettingsLabelAddButton;
