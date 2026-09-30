import { memo, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router";
import { useTranslation } from "react-i18next";
import CachedImage from "@/components/CachedImage";
import HedaerNavItems from "@/components/Header/HedaerNavItems";
import { IHeaderProps } from "@/components/Header/types";
import ThemeSwitcher from "@/components/ThemeSwitcher";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import NavigationMenu from "@/components/base/NavigationMenu";
import Separator from "@/components/base/Separator";
import Sheet from "@/components/base/Sheet";
import { useAuth } from "@/core/providers/AuthProvider";
import { ROUTES } from "@/core/routing/constants";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import HeaderUserMenu from "@/components/Header/HeaderUserMenu";
import HeaderUserNotification from "@/components/Header/HeaderUserNotification";
import { PROJECT_QUICK_SWITCHER_EVENT } from "@/pages/DashboardPage/components/ProjectDiscovery";

const Header = memo(({ navs, title, compact, navigationReady = true }: IHeaderProps) => {
    const [t] = useTranslation();
    const { currentUser } = useAuth();
    const [isOpened, setIsOpen] = useState(false);
    const navigate = usePageNavigateRef();
    const location = useLocation();
    const commandTrigger = useRef<HTMLButtonElement>(null);

    useEffect(() => {
        if (navigationReady && location.state?.commandPaletteFocus === true) {
            commandTrigger.current?.focus({ preventScroll: true });
        }
    }, [location.key, location.state, navigationReady]);

    const toDashboard = () => {
        navigate(ROUTES.DASHBOARD.PROJECTS.ALL, { smooth: true });
    };

    const separator = <Separator className="h-5" orientation="vertical" />;

    return (
        <header
            data-workbench-context=""
            className={
                compact
                    ? "sticky top-0 z-10 flex h-11 items-center justify-between gap-4 border-b bg-background px-4"
                    : "sticky top-0 z-10 flex h-16 items-center justify-between gap-4 border-b bg-background px-4 md:px-6"
            }
        >
            {!navs.length && (
                <Flex className="flex md:hidden">
                    <a onClick={toDashboard} className="flex size-6 cursor-pointer items-center gap-2 text-lg font-semibold md:text-base">
                        <CachedImage src="/images/logo.png" alt="Logo" size="full" />
                    </a>
                </Flex>
            )}
            <Flex
                items="center"
                gap={{
                    initial: "6",
                    md: "5",
                    lg: "6",
                }}
                textSize={{
                    initial: "lg",
                    md: "sm",
                }}
                weight="medium"
                className={compact ? "min-w-0 flex-1" : "hidden md:flex"}
            >
                <a
                    onClick={toDashboard}
                    className={compact ? "hidden size-6 shrink-0 cursor-pointer items-center md:flex" : "flex size-6 cursor-pointer items-center"}
                >
                    <CachedImage src="/images/logo.png" alt="Logo" size="full" />
                </a>
                {compact ? (
                    <span className="flex min-w-0 items-center gap-2 text-sm font-medium">
                        <span className="hidden shrink-0 font-semibold md:inline">Langboard</span>
                        {!!title && <IconComponent icon="chevron-right" size="3.5" className="hidden shrink-0 text-muted-foreground md:inline" />}
                        {!!title && <span className="min-w-0 truncate">{title}</span>}
                    </span>
                ) : (
                    !!title && <span className="text-lg font-semibold">{title}</span>
                )}
                {navs.length > 0 && !compact && (
                    <NavigationMenu.Root>
                        <NavigationMenu.List>
                            <HedaerNavItems navs={navs} />
                        </NavigationMenu.List>
                    </NavigationMenu.Root>
                )}
            </Flex>
            {navs.length > 0 && (
                <Sheet.Root open={isOpened} onOpenChange={setIsOpen}>
                    <Sheet.Title hidden />
                    <Sheet.Description hidden />
                    <Sheet.Trigger asChild>
                        <Button variant="outline" size="icon" className={compact ? "order-first shrink-0 md:hidden" : "shrink-0 md:hidden"}>
                            <IconComponent icon="menu" size="5" />
                            <span className="sr-only">Toggle navigation menu</span>
                        </Button>
                    </Sheet.Trigger>
                    <Sheet.Content side="left" data-workbench-context="" className="flex flex-col justify-between">
                        <Flex
                            items="center"
                            position="absolute"
                            left="6"
                            top="6"
                            gap="2"
                            w="full"
                            className="max-w-[calc(100%_-_theme(spacing.16))] truncate sm:max-w-[calc(24rem_-_theme(spacing.16))]"
                        >
                            <a onClick={toDashboard} className="flex cursor-pointer items-center gap-2 text-lg font-semibold">
                                <CachedImage src="/images/logo.png" alt="Logo" size="6" />
                            </a>
                            {!!title && (
                                <>
                                    <IconComponent icon="chevron-right" size="5" />
                                    <span className="max-w-[calc(100%_-_theme(spacing.16))] truncate text-lg font-semibold">{title}</span>
                                </>
                            )}
                        </Flex>
                        <nav className="mt-9 grid gap-2 overflow-y-auto text-lg font-medium">
                            <HedaerNavItems
                                isMobile
                                navs={navs}
                                setIsOpen={setIsOpen}
                                activatedClass=""
                                deactivatedClass="text-muted-foreground"
                                shardClass="hover:text-foreground"
                            />
                        </nav>
                    </Sheet.Content>
                </Sheet.Root>
            )}
            <Flex
                items="center"
                justify="end"
                gap={{
                    initial: "2",
                    md: "3",
                }}
                ml={{
                    md: "auto",
                }}
            >
                {compact && (
                    <Button
                        ref={commandTrigger}
                        data-command-palette-trigger
                        type="button"
                        variant="outline"
                        size="sm"
                        aria-label={t("dashboard.Command palette")}
                        title={t("dashboard.Command palette")}
                        className="h-8 shrink-0 gap-2 px-2"
                        onClick={() => window.dispatchEvent(new Event(PROJECT_QUICK_SWITCHER_EVENT))}
                    >
                        <IconComponent icon="search" size="4" />
                        <span className="hidden lg:inline">{t("dashboard.Search")}</span>
                        <kbd className="hidden rounded border px-1 font-mono text-[10px] text-muted-foreground lg:inline">⌘K</kbd>
                    </Button>
                )}
                <span className={compact ? "hidden sm:inline-flex" : "inline-flex"}>
                    <ThemeSwitcher variant="ghost" hideTriggerIcon buttonClassNames="p-2" />
                </span>
                {currentUser ? (
                    <>
                        {!compact && separator}
                        <HeaderUserNotification currentUser={currentUser} />
                        {!compact && separator}
                        <HeaderUserMenu currentUser={currentUser} />
                    </>
                ) : null}
            </Flex>
        </header>
    );
});

export default Header;
