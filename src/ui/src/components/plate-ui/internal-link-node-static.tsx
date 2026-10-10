import type { TComboboxInputElement } from "platejs";
import { KEYS } from "platejs";
import type { SlateElementProps } from "platejs/static";
import { SlateElement } from "platejs/static";
import React from "react";

import type { TInternalLinkElement } from "@/components/Editor/plugins/customs/internal-link/InternalLinkPlugin";
import IconComponent from "@/components/base/IconComponent";
import { ProjectCard, ProjectWiki } from "@/core/models";
import { isModel } from "@/core/models/ModelRegistry";
import { cn } from "@/core/utils/ComponentUtils";
import { useEditorData } from "@/core/providers/EditorDataProvider";

export function InternalLinkElementStatic(props: SlateElementProps<TInternalLinkElement>) {
    const { element } = props;
    const { linkables, createInternalLink } = useEditorData();
    const linkable = linkables.find((candidate) => candidate.uid === element.uid) ?? element;
    const icon = React.useMemo(() => {
        if (linkables.some((candidate) => isModel(candidate, "ProjectCard") && candidate.uid === element.uid)) {
            return "credit-card";
        }

        if (linkables.some((candidate) => isModel(candidate, "ProjectWiki") && candidate.uid === element.uid)) {
            return "brain";
        }

        return "circle-slash";
    }, [element.uid, linkables]);

    return (
        <SlateElement
            {...props}
            as="span"
            className={cn(
                "internal-link inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 align-baseline text-sm font-medium",
                element.children[0][KEYS.bold] === true && "font-bold",
                element.children[0][KEYS.italic] === true && "italic",
                element.children[0][KEYS.underline] === true && "underline"
            )}
            attributes={{
                ...props.attributes,
                "data-slate-value": element.value,
                draggable: false,
            }}
        >
            <IconComponent icon={icon} size="4" />
            <InternalLinkLabelStatic linkable={linkable} toLink={createInternalLink(element.internalType, element.uid)} />
        </SlateElement>
    );
}

export function InternalLinkInputElementStatic(props: SlateElementProps<TComboboxInputElement>) {
    return (
        <SlateElement {...props} as="span" className="inline-block rounded-md bg-muted px-1.5 py-0.5 align-baseline text-sm">
            {props.children}
        </SlateElement>
    );
}

const InternalLinkLabelStatic = ({ linkable, toLink }: { linkable: TInternalLinkElement | TInternalLinkElement["uid"]; toLink: string }) => {
    if (isModel(linkable, "ProjectCard")) {
        return <InternalLinkCardLabel linkable={linkable} toLink={toLink} />;
    }

    if (isModel(linkable, "ProjectWiki")) {
        return <InternalLinkWikiLabel linkable={linkable} toLink={toLink} />;
    }

    return <>{(linkable as TInternalLinkElement).uid || "Unknown"}</>;
};

const InternalLinkCardLabel = ({ linkable, toLink }: { linkable: ProjectCard.TModel; toLink: string }) => {
    return (
        <a className="text-primary underline decoration-primary underline-offset-4" href={toLink}>
            {linkable.useField("title")}
        </a>
    );
};

const InternalLinkWikiLabel = ({ linkable, toLink }: { linkable: ProjectWiki.TModel; toLink: string }) => {
    return (
        <a className="text-primary underline decoration-primary underline-offset-4" href={toLink}>
            {linkable.useField("title")}
        </a>
    );
};
