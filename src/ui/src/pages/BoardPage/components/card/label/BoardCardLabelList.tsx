import { ICollaborativeTextMeta, useCollaborativeText } from "@/components/Collaborative/useCollaborativeText";
import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import { LabelModelBadge } from "@/components/LabelBadge";
import { ProjectLabel } from "@/core/models";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { EEditorCollaborationType } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import BoardCardActionSetLabel from "@/pages/BoardPage/components/card/action/label/BoardCardActionSetLabel";

interface ILabelToggleMeta {
    checked: bool;
    labelUID: string;
    updatedAt: number;
}

function BoardCardLabelList(): React.JSX.Element {
    const { card } = useBoardCard();
    const labels = card.useForeignFieldArray("labels");
    const { remoteMeta } = useCollaborativeText({
        defaultValue: JSON.stringify(labels.map((label) => label.uid)),
        collaborationType: EEditorCollaborationType.Card,
        uid: card.uid,
        section: "labels",
        field: "selected-label-uids",
    });
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

    ProjectLabel.Model.subscribe("DELETION", `board-card-label-list-${card.uid}`, (uids) => {
        const newLabels = labels.filter((label) => !uids.includes(label.uid));
        card.labels = newLabels;
    });

    return (
        <Flex inline wrap gap="1.5">
            {labels.map((label) => {
                const remoteLabelState = remoteLabelStates[label.uid];

                return (
                    <Flex key={`board-card-label-${label.uid}`} inline items="center" gap="1.5">
                        <LabelModelBadge model={label} />
                        {!!remoteLabelState?.name && (
                            <Box
                                textSize="xs"
                                className="rounded px-1.5 py-0.5"
                                style={{
                                    backgroundColor: `${remoteLabelState.color}14`,
                                    color: remoteLabelState.color,
                                }}
                            >
                                {remoteLabelState.name}
                            </Box>
                        )}
                    </Flex>
                );
            })}
            <BoardCardActionSetLabel buttonClassName="h-7 gap-1 rounded-full border-dashed px-2.5 text-xs text-muted-foreground" />
        </Flex>
    );
}

export default BoardCardLabelList;
