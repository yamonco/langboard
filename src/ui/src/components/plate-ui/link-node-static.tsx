import type { TLinkElement } from "platejs";
import type { SlateElementProps } from "platejs/static";
import { SlateElement } from "platejs/static";
import { secretReferenceHistoryHref } from "@/core/utils/SecretReferenceLink";

export function LinkElementStatic(props: SlateElementProps<TLinkElement>) {
    return (
        <SlateElement
            {...props}
            as="a"
            className="font-medium text-primary underline decoration-primary underline-offset-4"
            attributes={{
                ...props.attributes,
                href: secretReferenceHistoryHref(props.element.url) ?? (props.element.url.startsWith("secret:") ? undefined : props.element.url),
            }}
        >
            {props.children}
        </SlateElement>
    );
}
