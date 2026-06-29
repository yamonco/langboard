import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import Popover from "@/components/base/Popover";
import SubmitButton from "@/components/base/SubmitButton";
import Toast from "@/components/base/Toast";
import useApplyOrchestrationWorkflowTemplate from "@/controllers/api/board/orchestration/useApplyOrchestrationWorkflowTemplate";
import useDeleteProject from "@/controllers/api/board/settings/useDeleteProject";
import { deleteProjectModel } from "@/core/helpers/ModelHelper";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { useBoardSettings } from "@/core/providers/BoardSettingsProvider";
import { ROUTES } from "@/core/routing/constants";
import { ESocketTopic } from "@langboard/core/enums";
import { memo, useState } from "react";
import { useTranslation } from "react-i18next";

const BoardSettingsOther = memo(() => {
    const navigate = usePageNavigateRef();
    const { project } = useBoardSettings();
    const [isValidating, setIsValidating] = useState(false);
    const [isApplyingWorkflow, setIsApplyingWorkflow] = useState(false);
    const [isOpened, setIsOpened] = useState(false);
    const [t] = useTranslation();
    const { mutateAsync } = useDeleteProject({ interceptToast: true });
    const { mutateAsync: applyWorkflowTemplateMutateAsync } = useApplyOrchestrationWorkflowTemplate({ interceptToast: true });

    const applyWorkflowTemplate = () => {
        if (isApplyingWorkflow) {
            return;
        }

        setIsApplyingWorkflow(true);

        const promise = applyWorkflowTemplateMutateAsync({
            project_uid: project.uid,
        });

        Toast.Add.promise(promise, {
            loading: t("common.Updating..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler({}, messageRef);

                handle(error);
                return messageRef.message;
            },
            success: () => t("successes.Orchestration workflow applied successfully."),
            finally: () => {
                setIsApplyingWorkflow(false);
            },
        });
    };

    const deleteProject = () => {
        if (isValidating) {
            return;
        }

        setIsValidating(true);

        const promise = mutateAsync({
            project_uid: project.uid,
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
                deleteProjectModel(ESocketTopic.Board, project.uid);
                setTimeout(() => {
                    navigate(ROUTES.DASHBOARD.PROJECTS.ALL, { replace: true });
                }, 0);
                return t("successes.Project deleted successfully.");
            },
            finally: () => {
                setIsValidating(false);
                setIsOpened(false);
            },
        });
    };

    const changeOpenState = (opened: bool) => {
        if (isValidating) {
            return;
        }

        setIsOpened(opened);
    };

    return (
        <Flex direction="col" py="4" gap="4" items="end">
            <SubmitButton
                type="button"
                variant="secondary"
                size="sm"
                onClick={applyWorkflowTemplate}
                isValidating={isApplyingWorkflow}
                disabled={isValidating}
            >
                {t("project.settings.Apply orchestration workflow")}
            </SubmitButton>
            <Popover.Root open={isOpened} onOpenChange={changeOpenState}>
                <Popover.Trigger asChild>
                    <Button variant="destructive" size="sm">
                        {t("project.settings.Delete project")}
                    </Button>
                </Popover.Trigger>
                <Popover.Content>
                    <Box mb="1" textSize={{ initial: "sm", sm: "base" }} weight="semibold" className="text-center">
                        {t("ask.Are you sure you want to delete this project?")}
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
                        <SubmitButton type="button" variant="destructive" size="sm" onClick={deleteProject} isValidating={isValidating}>
                            {t("common.Delete")}
                        </SubmitButton>
                    </Flex>
                </Popover.Content>
            </Popover.Root>
        </Flex>
    );
});

export default BoardSettingsOther;
