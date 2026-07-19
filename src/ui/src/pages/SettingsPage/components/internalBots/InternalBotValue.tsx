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
        const newValue = newValueRef.current.trim();
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

    return (
        <Box w="full">
            <BotValueInput
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
