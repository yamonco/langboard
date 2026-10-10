import DocumentRetrievalSettings from "./DocumentRetrievalSettings";
import Checkbox from "@/components/base/Checkbox";
import Switch from "@/components/base/Switch";
import { EInternalBotType } from "@/core/models/InternalBotModel";
import Box from "@/components/base/Box";
import Toast from "@/components/base/Toast";
import useUpdateInternalBot from "@/controllers/api/settings/internalBots/useUpdateInternalBot";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import useRoleActionFilter from "@/core/hooks/useRoleActionFilter";
import { useAppSetting } from "@/core/providers/AppSettingProvider";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { SettingRole } from "@/core/models/roles";
import { ROUTES } from "@/core/routing/constants";
import { memo, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { EHttpStatus } from "@langboard/core/enums";
import { EEditorCollaborationType } from "@langboard/core/constants";
import { getValueType, syncPendingBotValueInputChange } from "@/components/bots/BotValueInput/utils";
import BotValueInput from "@/components/bots/BotValueInput";
import { TBotValueDefaultInputRefLike } from "@/components/bots/BotValueInput/types";

const InternalBotValue = memo(() => {
    const [t] = useTranslation();
    const { model: internalBot } = ModelRegistry.InternalBotModel.useContext();
    const navigate = usePageNavigateRef();
    const { currentUser } = useAppSetting();
    const settingRoleActions = currentUser.useField("setting_role_actions");
    const { hasRoleAction } = useRoleActionFilter(settingRoleActions);
    const canUpdateInternalBot = hasRoleAction(SettingRole.EAction.InternalBotUpdate);
    const platform = internalBot.useField("platform");
    const platformRunningType = internalBot.useField("platform_running_type");
    const value = internalBot.useField("value");
    const botType = internalBot.useField("bot_type");
    const documentSettings = useMemo(() => {
        try {
            const config = JSON.parse(value);
            return config && typeof config === "object" && !Array.isArray(config) ? config : null;
        } catch {
            return null;
        }
    }, [value]);
    const valueType = useMemo(() => getValueType(platform, platformRunningType), [platform, platformRunningType]);
    const shouldUseEditMode = valueType === "default";
    const { mutateAsync } = useUpdateInternalBot(internalBot, { interceptToast: true });
    const newValueRef = useRef<string>(value);
    const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement | TBotValueDefaultInputRefLike | null>(null);
    const [isValidating, setIsValidating] = useState(false);
    const [isEditing, setIsEditing] = useState(false);

    const change = async () => {
        const input = inputRef.current;
        if (isValidating || !newValueRef.current || !input || !canUpdateInternalBot) {
            return;
        }

        if (input.type === "default-bot-json") {
            const validated = (input as TBotValueDefaultInputRefLike).validate(true);
            if (!validated) {
                return;
            }
        }

        await syncPendingBotValueInputChange(input);
        let newValue = newValueRef.current.trim();
        if (botType === EInternalBotType.DocumentVision && documentSettings) {
            try {
                const config = JSON.parse(newValue);
                newValue = JSON.stringify({
                    ...config,
                    document_processing_enabled: documentSettings.document_processing_enabled ?? true,
                    keyword_languages: documentSettings.keyword_languages ?? ["ko", "en", "ja", "zh"],
                });
            } catch {
                return;
            }
        }
        if (botType === EInternalBotType.DocumentEmbedding && documentSettings) {
            try {
                newValue = JSON.stringify({ ...JSON.parse(newValue), retrieval: documentSettings.retrieval ?? {} });
            } catch {
                return;
            }
        }
        if (value.trim() === newValue || !newValue) {
            newValueRef.current = newValue;
            setIsEditing(false);
            return;
        }

        setIsValidating(true);

        const promise = mutateAsync({
            value: newValue,
        });

        Toast.Add.promise(promise, {
            loading: t("common.Changing..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler(
                    {
                        [EHttpStatus.HTTP_403_FORBIDDEN]: {
                            after: () => navigate(ROUTES.ERROR(EHttpStatus.HTTP_403_FORBIDDEN), { replace: true }),
                        },
                    },
                    messageRef
                );

                handle(error);
                return messageRef.message;
            },
            success: () => {
                return t("successes.Internal bot value changed successfully.");
            },
            finally: () => {
                setIsValidating(false);
                setIsEditing(false);
            },
        });
    };

    const startEditing = () => {
        if (!canUpdateInternalBot || isValidating) {
            return;
        }

        newValueRef.current = value;
        setIsEditing(true);
    };

    const cancelEditing = () => {
        if (isValidating) {
            return;
        }

        newValueRef.current = value;
        setIsEditing(false);
    };

    const saveDocumentSettings = (config: Record<string, unknown>) => {
        if (!canUpdateInternalBot || isEditing || isValidating) return;
        setIsValidating(true);
        Toast.Add.promise(mutateAsync({ value: JSON.stringify(config) }), {
            loading: t("common.Changing..."),
            success: () => t("successes.Internal bot value changed successfully."),
            error: (error) => {
                const message = { message: "" };
                setupApiErrorHandler({}, message).handle(error);
                return message.message;
            },
            finally: () => setIsValidating(false),
        });
    };

    const setKeywordLanguage = (language: string, enabled: boolean) => {
        if (!documentSettings) return;
        const selected = Array.isArray(documentSettings.keyword_languages) ? documentSettings.keyword_languages : ["ko", "en", "ja", "zh"];
        const languages = enabled ? [...new Set([...selected, language])] : selected.filter((value: string) => value !== language);
        saveDocumentSettings({ ...documentSettings, keyword_languages: languages });
    };

    const setDocumentProcessing = (enabled: bool) => {
        if (documentSettings) saveDocumentSettings({ ...documentSettings, document_processing_enabled: enabled });
    };

    return (
        <Box w="full">
            {botType === EInternalBotType.DocumentVision && (
                <div className="mb-4 flex items-start justify-between gap-4 rounded-lg border p-3">
                    <div>
                        <div className="text-sm font-medium">{t("internalBot.Process new uploads")}</div>
                        <p className="mt-1 text-xs text-muted-foreground">{t("internalBot.Existing attachments require explicit processing")}</p>
                    </div>
                    <Switch
                        aria-label={t("internalBot.Process new uploads")}
                        checked={!!documentSettings && (documentSettings.document_processing_enabled ?? true) === true}
                        disabled={!documentSettings || !canUpdateInternalBot || isEditing || isValidating}
                        onCheckedChange={setDocumentProcessing}
                    />
                </div>
            )}
            {botType === EInternalBotType.DocumentVision && (
                <fieldset className="mb-4 rounded-lg border p-3">
                    <legend className="px-1 text-sm font-medium">{t("internalBot.Search keyword languages")}</legend>
                    <div className="flex flex-wrap gap-4">
                        {(
                            [
                                ["ko", "한국어"],
                                ["en", "English"],
                                ["ja", "日本語"],
                                ["zh", "中文"],
                            ] as const
                        ).map(([language, name]) => (
                            <label key={language} className="flex items-center gap-2 text-sm">
                                <Checkbox
                                    checked={
                                        !!documentSettings &&
                                        (!Array.isArray(documentSettings.keyword_languages) || documentSettings.keyword_languages.includes(language))
                                    }
                                    disabled={!documentSettings || !canUpdateInternalBot || isEditing || isValidating}
                                    onCheckedChange={(checked) => setKeywordLanguage(language, checked === true)}
                                />
                                {name}
                            </label>
                        ))}
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">{t("internalBot.Keywords apply to requested processing")}</p>
                </fieldset>
            )}
            {botType === EInternalBotType.DocumentEmbedding && documentSettings && (
                <DocumentRetrievalSettings
                    key={value}
                    value={documentSettings}
                    disabled={!canUpdateInternalBot || isEditing || isValidating}
                    onSave={(retrieval) => saveDocumentSettings({ ...documentSettings, retrieval })}
                />
            )}
            <BotValueInput
                purpose={botType === EInternalBotType.DocumentEmbedding ? "embedding" : "chat"}
                collaborationType={EEditorCollaborationType.AppSettings}
                currentUser={currentUser}
                uid={internalBot.uid}
                section="internal-bot-value"
                platform={platform}
                platformRunningType={platformRunningType}
                value={value}
                label={t(`bot.platformRunningTypes.${platformRunningType}`)}
                valueType={valueType}
                newValueRef={newValueRef}
                isValidating={isValidating}
                isEditing={isEditing}
                startEditing={canUpdateInternalBot ? startEditing : undefined}
                cancelEditing={canUpdateInternalBot ? cancelEditing : undefined}
                change={canUpdateInternalBot ? change : undefined}
                required
                disabled={!canUpdateInternalBot || (shouldUseEditMode && !isEditing)}
                ref={inputRef}
            />
        </Box>
    );
});

export default InternalBotValue;
