export interface IHeaderNavItem {
    name: React.ReactNode;
    subNavs?: Omit<IHeaderNavItem, "subNavs">[];
    href?: string;
    onClick?: () => void;
    active?: bool;
    hidden?: bool;
}

export interface IHeaderProps {
    navs: IHeaderNavItem[];
    title?: React.ReactNode;
    compact?: boolean;
    navigationReady?: boolean;
}

interface IBaseHeaderNavItemsProps {
    isMobile?: bool;
    navs: IHeaderProps["navs"];
    setIsOpen?: (value: bool) => void;
    activatedClass?: string;
    deactivatedClass?: string;
    shardClass?: string;
}

interface IMobileHeaderNavItemsProps extends IBaseHeaderNavItemsProps {
    isMobile: true;
    setIsOpen: (value: bool) => void;
    activatedClass: string;
    deactivatedClass: string;
    shardClass: string;
}

interface IDesktopHeaderNavItemsProps extends IBaseHeaderNavItemsProps {
    isMobile?: false;
}

export type THeaderNavItemsProps = IMobileHeaderNavItemsProps | IDesktopHeaderNavItemsProps;
