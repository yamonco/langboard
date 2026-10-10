"use client";

import * as React from "react";
import type { TLinkElement } from "platejs";
import type { PlateElementProps } from "platejs/react";
import { useLink } from "@platejs/link/react";
import { PlateElement } from "platejs/react";
import LinkElementDialog from "@/components/plate-ui/link-node-dialog";
import { secretReferenceHistoryHref } from "@/core/utils/SecretReferenceLink";

export function LinkElement(props: PlateElementProps<TLinkElement>) {
    const { props: linkProps } = useLink({ element: props.element });
    const [dialogOpen, setDialogOpen] = React.useState(false);
    const historyHref = secretReferenceHistoryHref(props.element.url);
    const handleClick = React.useCallback(() => {
        if (!linkProps.href) {
            return;
        }

        setDialogOpen(true);
    }, [linkProps.href, setDialogOpen]);

    return (
        <>
            <PlateElement
                {...props}
                as="a"
                className="link cursor-pointer font-medium text-primary underline decoration-primary underline-offset-4"
                attributes={{
                    ...props.attributes,
                    onMouseOver: linkProps.onMouseOver,
                    href: historyHref,
                    onClick: historyHref ? () => window.location.assign(historyHref) : handleClick,
                }}
            >
                {props.children}
            </PlateElement>
            <LinkElementDialog isOpened={dialogOpen} setIsOpened={setDialogOpen} href={linkProps.href} />
        </>
    );
}
