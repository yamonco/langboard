import Button, { type ButtonProps } from "@/components/base/Button";
import DropdownMenu from "@/components/base/DropdownMenu";
import IconComponent from "@/components/base/IconComponent";
import { TIconName } from "@/components/base/IconComponent";
import { MoreMenuProvider } from "@/components/MoreMenu/Provider";
import useHandleInteractOutside from "@/core/hooks/useHandleInteractOutside";
import { useState } from "react";
import { useTranslation } from "react-i18next";

export interface IMoreMenuRootProps {
    modal?: bool;
    triggerProps?: ButtonProps;
    triggerIcon?: TIconName;
    triggerIconSize?: React.ComponentPropsWithoutRef<typeof IconComponent>["size"];
    contentProps?: React.ComponentProps<typeof DropdownMenu.Content>;
    children: React.ReactNode;
}

function MoreMenuRoot({
    modal,
    triggerProps,
    triggerIcon = "ellipsis-vertical",
    triggerIconSize = "4",
    contentProps,
    children,
}: IMoreMenuRootProps): React.JSX.Element {
    const [t] = useTranslation();
    const [isOpened, setIsOpened] = useState(false);
    const [isValidating, setIsValidating] = useState(false);
    const { onInteractOutside, onPointerDownOutside } = useHandleInteractOutside({ pointerDownOutside: () => setIsOpened(false) }, [setIsOpened]);
    const { variant = "ghost", size = "icon-sm" } = triggerProps || {};

    const changeOpenedState = (opened: bool) => {
        if (isValidating) {
            return;
        }
        setIsOpened(opened);
    };

    return (
        <MoreMenuProvider isValidating={isValidating} setIsValidating={setIsValidating} isOpened={isOpened} setIsOpened={setIsOpened}>
            <DropdownMenu.Root modal={modal} open={isOpened} onOpenChange={changeOpenedState}>
                <DropdownMenu.Trigger asChild>
                    <Button type="button" variant={variant} size={size} title={t("common.More")} aria-label={t("common.More")} {...triggerProps}>
                        <IconComponent icon={triggerIcon} size={triggerIconSize} />
                    </Button>
                </DropdownMenu.Trigger>
                <DropdownMenu.Content align="end" onInteractOutside={onInteractOutside} onPointerDownOutside={onPointerDownOutside} {...contentProps}>
                    <DropdownMenu.Group>{children}</DropdownMenu.Group>
                </DropdownMenu.Content>
            </DropdownMenu.Root>
        </MoreMenuProvider>
    );
}

export default MoreMenuRoot;
