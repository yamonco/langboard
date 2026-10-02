import Checkbox from "@/components/base/Checkbox";
import { ICollaborativeTextMeta } from "@/components/Collaborative/useCollaborativeText";
import Flex from "@/components/base/Flex";
import Label from "@/components/base/Label";
import ScrollArea from "@/components/base/ScrollArea";
import Input from "@/components/base/Input";
import { ProjectLabel } from "@/core/models";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import BoardCardActionLabel from "@/pages/BoardPage/components/card/action/label/BoardCardActionLabel";
import type { IGlobalLabel } from "@/controllers/api/settings/globalLabels/useGlobalLabels";
import { globalLabelDisplay } from "@/core/utils/LabelDisplay";
import { memo, useState } from "react";
import { useTranslation } from "react-i18next";

interface ILabelToggleMeta {
    checked: bool;
    labelUID: string;
    updatedAt: number;
}

export interface IBoardCardActionLabelListProps {
    disabled?: bool;
    globalLabels?: IGlobalLabel[];
    globalLoading?: bool;
    globalError?: bool;
    remoteLabelStates: Record<string, ICollaborativeTextMeta<ILabelToggleMeta>>;
    selectedLabelUIDs: string[];
    setSelectedLabelUIDs: React.Dispatch<React.SetStateAction<string[]>>;
}

const BoardCardActionLabelList = memo(
    ({
        disabled,
        globalLabels = [],
        globalLoading,
        globalError,
        remoteLabelStates,
        selectedLabelUIDs,
        setSelectedLabelUIDs,
    }: IBoardCardActionLabelListProps) => {
        const { card } = useBoardCard();
        const [t, i18n] = useTranslation();
        const [query, setQuery] = useState("");
        const flatProjectLabels = ProjectLabel.Model.useModels((model) => model.project_uid === card.project_uid);
        const projectLabels = [...flatProjectLabels]
            .sort((a, b) => a.order - b.order)
            .filter((label) => `${label.name} ${label.description}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
        const remainingGlobalLabels = globalLabels
            .filter(
                (label) =>
                    !flatProjectLabels.some(
                        (local) =>
                            local.global_label_uid === label.uid || local.name.trim().toLocaleLowerCase() === label.name.trim().toLocaleLowerCase()
                    )
            )
            .filter((label) =>
                `${label.name} ${label.description} ${Object.values(label.translations)
                    .map((text) => `${text.name} ${text.description}`)
                    .join(" ")}`
                    .toLocaleLowerCase()
                    .includes(query.trim().toLocaleLowerCase())
            );
        ProjectLabel.Model.subscribe("DELETION", `board-card-action-label-list-${card.uid}`, (uids) => {
            setSelectedLabelUIDs((prev) => prev.filter((uid) => !uids.includes(uid)));
        });

        const changeSelectedState = (labelUID: string) => {
            if (disabled) {
                return;
            }

            if (selectedLabelUIDs.includes(labelUID)) {
                setSelectedLabelUIDs((prev) => prev.filter((uid) => uid !== labelUID));
            } else {
                setSelectedLabelUIDs((prev) => [...prev, labelUID]);
            }
        };

        return (
            <div className="space-y-2">
                <Input
                    aria-label={t("card.Search labels")}
                    placeholder={t("card.Search labels")}
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    className="h-8 rounded-lg text-sm"
                />
                <ScrollArea.Root className="rounded-lg border bg-muted/20">
                    <Flex direction="col" position="relative" className="max-h-[min(theme(spacing.64),35vh)] select-none">
                        {!projectLabels.length && !remainingGlobalLabels.length && (
                            <p className="p-4 text-center text-xs text-muted-foreground">{t("card.No matching labels")}</p>
                        )}
                        {projectLabels.map((label) => {
                            const remoteLabelState = remoteLabelStates[label.uid];
                            const remoteColor = remoteLabelState?.color;
                            const remoteName = remoteLabelState?.name;

                            return (
                                <Label
                                    key={`board-card-action-label-${label.uid}`}
                                    display="flex"
                                    items="center"
                                    gap="3"
                                    p="2"
                                    cursor="pointer"
                                    className="rounded-md transition-colors hover:bg-secondary/60"
                                    style={
                                        remoteColor ? { backgroundColor: `${remoteColor}14`, boxShadow: `inset 0 0 0 1px ${remoteColor}` } : undefined
                                    }
                                    title={remoteName ? `${remoteName}` : undefined}
                                >
                                    <Checkbox
                                        aria-label={label.name}
                                        checked={selectedLabelUIDs.includes(label.uid)}
                                        disabled={disabled}
                                        onCheckedChange={() => changeSelectedState(label.uid)}
                                        style={remoteColor ? { borderColor: remoteColor, boxShadow: `0 0 0 1px ${remoteColor}` } : undefined}
                                    />
                                    <Flex items="center" justify="between" className="min-w-0 flex-1 gap-2">
                                        <BoardCardActionLabel label={label} />
                                        {remoteName ? (
                                            <span
                                                className="shrink-0 truncate rounded px-1.5 py-0.5"
                                                style={{
                                                    backgroundColor: remoteColor ? `${remoteColor}14` : undefined,
                                                    color: remoteColor || undefined,
                                                    fontSize: "0.75rem",
                                                    lineHeight: "1rem",
                                                }}
                                            >
                                                {remoteName}
                                            </span>
                                        ) : null}
                                    </Flex>
                                </Label>
                            );
                        })}
                        {!!remainingGlobalLabels.length && <p className="px-2 pt-3 text-xs text-muted-foreground">{t("card.Global labels")}</p>}
                        {remainingGlobalLabels.map((label) => {
                            const display = globalLabelDisplay(label.name, label.description, label, i18n.language);
                            const uid = `global:${label.uid}`;
                            return (
                                <Label
                                    key={uid}
                                    display="flex"
                                    items="center"
                                    gap="3"
                                    p="2"
                                    cursor="pointer"
                                    className="rounded-md hover:bg-secondary/60"
                                    title={display.description}
                                >
                                    <Checkbox
                                        aria-label={display.name}
                                        checked={selectedLabelUIDs.includes(uid)}
                                        disabled={disabled}
                                        onCheckedChange={() => changeSelectedState(uid)}
                                    />
                                    <span className="size-6 shrink-0 rounded-md" style={{ backgroundColor: label.color }} />
                                    <span className="truncate text-sm">{display.name}</span>
                                </Label>
                            );
                        })}
                        {globalLoading && <p className="p-2 text-xs text-muted-foreground">{t("common.Loading...")}</p>}
                        {globalError && (
                            <p role="alert" className="p-2 text-xs text-destructive">
                                {t("card.Global labels unavailable")}
                            </p>
                        )}
                    </Flex>
                </ScrollArea.Root>
            </div>
        );
    }
);

export default BoardCardActionLabelList;
