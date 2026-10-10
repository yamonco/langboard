import AutoComplete from "@/components/base/AutoComplete";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Collaborative from "@/components/Collaborative";
import Flex from "@/components/base/Flex";
import Form from "@/components/base/Form";
import Input from "@/components/base/Input";
import Label from "@/components/base/Label";
import SubmitButton from "@/components/base/SubmitButton";
import Textarea from "@/components/base/Textarea";
import FormErrorMessage from "@/components/FormErrorMessage";
import { useCollaborativeText } from "@/components/Collaborative/useCollaborativeText";
import useChangeProjectDetails from "@/controllers/api/board/settings/useChangeProjectDetails";
import useForm from "@/core/hooks/form/useForm";
import { Project } from "@/core/models";
import { useBoardSettings } from "@/core/providers/BoardSettingsProvider";
import { EEditorCollaborationType } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import { memo, useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

const BoardSettingsBasic = memo(() => {
    const { canEditBasicInfo, isBasicInfoEditing, project, setIsBasicInfoEditing } = useBoardSettings();
    const [t] = useTranslation();
    const { mutate } = useChangeProjectDetails(project.uid);
    const title = project.useField("title");
    const description = project.useField("description");
    const aiDescription = project.useField("ai_description");
    const projectType = project.useField("project_type");
    const archiveVisibleDays = project.useField("archive_visible_days");
    const projectTypeRef = useRef(projectType);
    const projectTypeInputRef = useRef<HTMLInputElement>(null);
    const { errors, isValidating, handleSubmit, formRef } = useForm({
        errorLangPrefix: "project.errors",
        schema: {
            title: { required: true },
            description: {},
            project_type: { required: true },
            archive_visible_days: {
                required: true,
                custom: {
                    errorKey: "invalid_archive_visible_days",
                    validate: (value) => Utils.Type.isString(value) && Number.isInteger(Number(value)) && Number(value) >= 1,
                },
            },
        },
        mutate,
        mutateOnSuccess: () => {
            setIsBasicInfoEditing(false);
        },
        useDefaultBadRequestHandler: true,
    });
    const {
        remoteCursors: projectTypeRemoteCursors,
        updateSelection: updateProjectTypeSelection,
        value: collaborativeProjectType,
        updateValue: updateCollaborativeProjectType,
    } = useCollaborativeText({
        collaborationType: EEditorCollaborationType.BoardSettings,
        uid: project.uid,
        field: "project_type",
        defaultValue: projectType,
        disabled: !isBasicInfoEditing,
    });

    const setProjectType = (value: string) => {
        projectTypeRef.current = value;
        projectTypeInputRef.current!.value = value;
        updateCollaborativeProjectType(value);
    };

    useEffect(() => {
        projectTypeRef.current = collaborativeProjectType;
        if (projectTypeInputRef.current) {
            projectTypeInputRef.current.value = collaborativeProjectType;
        }
    }, [collaborativeProjectType]);

    const handleCancelEditing = useCallback(() => {
        setIsBasicInfoEditing(false);
    }, [setIsBasicInfoEditing]);

    const handleStartEditing = useCallback(() => {
        if (!canEditBasicInfo) {
            return;
        }

        setIsBasicInfoEditing(true);
    }, [canEditBasicInfo, setIsBasicInfoEditing]);

    return (
        <Flex direction="col" py="4" gap="4" items="center">
            <Form.Root className="flex w-full max-w-96 flex-col gap-3" onSubmit={handleSubmit} ref={formRef}>
                {canEditBasicInfo && (
                    <Flex items="center" justify="end" gap="2">
                        {!isBasicInfoEditing ? (
                            <Button type="button" variant="default" onClick={handleStartEditing}>
                                {t("common.Edit")}
                            </Button>
                        ) : (
                            <>
                                <Button type="button" variant="secondary" onClick={handleCancelEditing}>
                                    {t("common.Cancel")}
                                </Button>
                                <SubmitButton type="submit" isValidating={isValidating}>
                                    {t("common.Save")}
                                </SubmitButton>
                            </>
                        )}
                    </Flex>
                )}
                <Label display="inline-grid" items="center" gap="2" w="full">
                    <Box>{t("project.Project title")}</Box>
                    <Form.Field name="title">
                        <Collaborative.Input
                            name="title"
                            collaborationType={EEditorCollaborationType.BoardSettings}
                            uid={project.uid}
                            field="title"
                            defaultValue={title}
                            disabled={!isBasicInfoEditing}
                            readOnly={isValidating}
                        />
                    </Form.Field>
                </Label>
                {errors.title && <FormErrorMessage error={errors.title} icon="circle-alert" />}
                <Label display="inline-grid" items="center" gap="2" w="full">
                    <Box>{t("project.Project description")}</Box>
                    <Form.Field name="description">
                        <Collaborative.Textarea
                            name="description"
                            collaborationType={EEditorCollaborationType.BoardSettings}
                            uid={project.uid}
                            field="description"
                            defaultValue={description}
                            disabled={!isBasicInfoEditing}
                            readOnly={isValidating}
                            resize="none"
                            className="max-h-36 min-h-36"
                        />
                    </Form.Field>
                </Label>
                <Form.Field name="project_type">
                    <Label display="inline-grid" items="center" gap="2" w="full">
                        <Box>{t("project.Project type")}</Box>
                        <Input type="hidden" name="project_type" value={projectTypeRef.current} ref={projectTypeInputRef} />
                        <AutoComplete
                            selectedValue={collaborativeProjectType}
                            onValueChange={setProjectType}
                            collaborativeCursors={projectTypeRemoteCursors}
                            items={Project.TYPES.map((project_type) => ({
                                value: project_type,
                                label: t(project_type === "Other" ? "common.Other" : `project.types.${project_type}`),
                            }))}
                            emptyMessage={projectTypeRef.current ?? ""}
                            disabled={isValidating || !isBasicInfoEditing}
                            onSelectionChange={updateProjectTypeSelection}
                            placeholder={t("project.Project type")}
                        />
                    </Label>
                    {errors.project_type && <FormErrorMessage error={errors.project_type} icon="circle-alert" />}
                </Form.Field>
                <Label display="inline-grid" items="center" gap="2" w="full">
                    <Box>{t("project.Archive visible days")}</Box>
                    <Form.Field name="archive_visible_days">
                        <Collaborative.Input
                            type="number"
                            min="1"
                            step="1"
                            name="archive_visible_days"
                            collaborationType={EEditorCollaborationType.BoardSettings}
                            uid={project.uid}
                            field="archive_visible_days"
                            defaultValue={archiveVisibleDays ?? 3}
                            disabled={!isBasicInfoEditing}
                            readOnly={isValidating}
                        />
                    </Form.Field>
                </Label>
                {errors.archive_visible_days && <FormErrorMessage error={errors.archive_visible_days} icon="circle-alert" />}
                {aiDescription && (
                    <Box>
                        <Box textSize="sm" weight="semibold" className="select-none">
                            {t("project.AI summary")}
                        </Box>
                        <Textarea value={aiDescription} disabled className="min-h-36" />
                    </Box>
                )}
            </Form.Root>
        </Flex>
    );
});

export default BoardSettingsBasic;
