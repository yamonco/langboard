import { lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { createMemoryRouter, Outlet } from "react-router";
import { RouterProvider } from "react-router/dom";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import RouteLoadError from "./index";
import "@/assets/styles/main.css";

const lang = new URLSearchParams(location.search).get("lang") ?? "en-US";
await i18n.use(initReactI18next).init({
    lng: lang,
    fallbackLng: "en-US",
    resources: {
        [lang]: {
            translation: {
                common: (await import(`../../assets/locales/${lang}/common.json`)).default,
                errors: (await import(`../../assets/locales/${lang}/errors.json`)).default,
            },
        },
    },
});
const Page = lazy(async () => {
    const key = "route-load-fixture:" + location.search;
    if (!sessionStorage.getItem(key)) {
        sessionStorage.setItem(key, "failed");
        throw new TypeError("Failed to fetch dynamically imported module: private-chunk-path");
    }
    return { default: () => <h1>Recovered card route</h1> };
});
const router = createMemoryRouter([
    {
        element: (
            <Suspense fallback="Loading">
                <Outlet />
            </Suspense>
        ),
        errorElement: <RouteLoadError />,
        children: [{ path: "/", element: <Page /> }],
    },
]);
createRoot(document.getElementById("root")!).render(<RouterProvider router={router} />);
