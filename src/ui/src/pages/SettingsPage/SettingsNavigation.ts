/** Use the visible route list for both navigation and permission fallback. */
export function settingsRedirect(
    routes: Readonly<Record<string, { hidden?: boolean }>>,
    pathname: string,
    defaultRoute: string
): string | undefined {
    if (routes[pathname] && !routes[pathname].hidden) return undefined;
    return Object.entries(routes).find(([, nav]) => !nav.hidden)?.[0] ?? defaultRoute;
}
