import type { PlateElementProps } from "platejs/react";
import { PlateElement } from "platejs/react";
import type { SlateElementProps } from "platejs/static";
import { SlateElement } from "platejs/static";
import { useTranslation } from "react-i18next";
import IconComponent from "@/components/base/IconComponent";
import { secretReferenceHistoryHref } from "@/core/utils/SecretReferenceLink";
import type { TSecretReferenceElement } from "@/components/Editor/plugins/secret-reference-base";

function ReferenceLabel() {
    return (
        <>
            <IconComponent icon="lock-keyhole" size="3" />
            <span aria-hidden="true">••••</span>
        </>
    );
}
const referenceClass =
    "inline-flex items-center gap-1 rounded-md border bg-muted px-1.5 py-0.5 align-baseline text-xs text-muted-foreground hover:text-foreground";

export function SecretReferenceElement(props: PlateElementProps<TSecretReferenceElement>) {
    const [t] = useTranslation();
    const href = secretReferenceHistoryHref(props.element.uri);
    return (
        <PlateElement {...props} as="span" className="inline-block" attributes={{ ...props.attributes, contentEditable: false }}>
            <a
                className={referenceClass}
                href={href}
                aria-label={t("myAccount.secretHistory.title")}
                title={t("myAccount.secretHistory.title")}
                onClick={href ? () => window.location.assign(href) : undefined}
            >
                <ReferenceLabel />
            </a>
            {props.children}
        </PlateElement>
    );
}

export function SecretReferenceElementStatic(props: SlateElementProps<TSecretReferenceElement>) {
    const [t] = useTranslation();
    return (
        <SlateElement {...props} as="span" className="inline-block">
            <a
                className={referenceClass}
                href={secretReferenceHistoryHref(props.element.uri)}
                aria-label={t("myAccount.secretHistory.title")}
                title={t("myAccount.secretHistory.title")}
            >
                <ReferenceLabel />
            </a>
        </SlateElement>
    );
}
