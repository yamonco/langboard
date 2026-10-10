import Box from "@/components/base/Box";
import Select from "@/components/base/Select";
import CollaborativeControlOverlay from "@/components/Collaborative/ControlOverlay";
import type { ICollaborativeTextMeta } from "@/components/Collaborative/useCollaborativeText";
import { useTranslation } from "react-i18next";

interface IRuleControlMeta {
    field: string;
    label: string;
    updatedAt: number;
}

export interface IRuleSelectProps {
    label: string;
    remoteMeta?: ICollaborativeTextMeta<IRuleControlMeta>;
    value: string;
    values: string[];
    disabled: bool;
    onChange: (value: string) => void;
}

function RuleSelect({ label, remoteMeta, value, values, disabled, onChange }: IRuleSelectProps) {
    const [t] = useTranslation();
    const remoteOverlay = remoteMeta ? (
        <CollaborativeControlOverlay
            color={remoteMeta.color}
            labelClassName="absolute right-2 z-[9999] max-w-32 truncate"
            labelStyle={{ top: "-0.75rem" }}
            name={remoteMeta.name}
            title={t("common.User changed field", { name: remoteMeta.name, field: remoteMeta.value.label })}
        />
    ) : null;

    return (
        <Box className="min-w-0 flex-1 space-y-2">
            <label className="text-sm font-medium">{label}</label>
            <div className="relative">
                <Select.Root value={value} onValueChange={onChange} disabled={disabled || !values.length}>
                    <Select.Trigger>
                        <Select.Value />
                    </Select.Trigger>
                    <Select.Content>
                        {values.map((item) => (
                            <Select.Item key={`${label}-${item}`} value={item}>
                                {t(`settings.notificationSchedules.ruleSchema.${item}`)}
                            </Select.Item>
                        ))}
                    </Select.Content>
                </Select.Root>
                {remoteOverlay}
            </div>
        </Box>
    );
}

export default RuleSelect;
