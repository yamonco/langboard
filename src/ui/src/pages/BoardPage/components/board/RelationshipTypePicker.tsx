import { useTranslation } from "react-i18next";
import Button from "@/components/base/Button";
import { GlobalRelationshipType } from "@/core/models";
import { cn } from "@/core/utils/ComponentUtils";
import { Boxes, GitBranch, Link2, type LucideIcon } from "lucide-react";

type Semantic = "contains" | "blocks" | "references";

export const RELATIONSHIP_GROUPS: { semantic: Semantic; label: string; hint: string; Icon: LucideIcon }[] = [
    { semantic: "contains", label: "board.Composition", hint: "board.Included in the same sprint, epic or feature", Icon: Boxes },
    { semantic: "blocks", label: "board.Execution dependencies", hint: "board.Start after prerequisite work is complete", Icon: GitBranch },
    { semantic: "references", label: "board.References", hint: "board.Link designs, evidence and related work", Icon: Link2 },
];

interface Props {
    types: GlobalRelationshipType.TModel[];
    selectedUid?: string;
    isParent: boolean;
    onSelect: (uid: string) => void;
}

/** Inactive legacy edges remain selectable only when already attached to this card. */
const RelationshipTypePicker = ({ types, selectedUid, isParent, onSelect }: Props) => {
    const [t] = useTranslation();
    const visible = types.filter((type) => type.is_active !== false || type.uid === selectedUid);
    const renderOption = (type: GlobalRelationshipType.TModel, Icon: LucideIcon, hint: string) => {
        const name = isParent ? type.parent_name : type.child_name;
        return (
            <Button
                key={type.uid}
                type="button"
                variant="ghost"
                title={`${name} · ${hint}`}
                aria-pressed={selectedUid === type.uid}
                className={cn(
                    "w-full justify-start gap-2 rounded-none border-b p-2 text-left",
                    selectedUid === type.uid && "bg-accent/70 text-accent-foreground"
                )}
                onClick={() => onSelect(type.uid)}
            >
                <Icon size={16} aria-hidden="true" />
                <span className="truncate">{name}</span>
            </Button>
        );
    };

    return (
        <div className="flex flex-col text-sm">
            {RELATIONSHIP_GROUPS.map(({ semantic, label, hint, Icon }) => {
                const matches = visible.filter((type) => type.machine_semantic === semantic);
                if (!matches.length) return null;
                return (
                    <div key={semantic}>
                        <div className="px-2 py-1 text-xs font-semibold text-muted-foreground">{t(label)}</div>
                        {matches.map((type) => renderOption(type, Icon, t(hint)))}
                    </div>
                );
            })}
            {visible.filter((type) => !type.machine_semantic).map((type) => renderOption(type, Link2, t("board.Legacy unclassified relationships")))}
        </div>
    );
};

export default RelationshipTypePicker;
