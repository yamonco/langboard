import i18n, { BackendModule, ReadCallback, ResourceKey, ResourceLanguage } from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";
import { APP_NAME, IS_PRODUCTION, LANGUAGE_LOCALES } from "@/constants";
import { Utils } from "@langboard/core/utils";

const jsons = import.meta.glob<{ default: Record<string, unknown> }>("./assets/locales/**/*.json");
const tempLocales: Record<string, Record<string, () => Promise<{ default: ResourceKey }>>> = {};
const locales: Record<string, () => Promise<ResourceLanguage>> = {};
Object.keys(jsons).forEach((jsonPath) => {
    const [_, __, ___, lang, ns] = jsonPath.split("/");
    if (!tempLocales[lang]) {
        tempLocales[lang] = {};
    }
    tempLocales[lang][ns.replace(".json", "")] = jsons[jsonPath];
});
Object.entries(tempLocales).forEach(([lang, nsLoaders]) => {
    locales[lang] = async () => {
        const entries = await Promise.all(Object.entries(nsLoaders).map(async ([ns, loader]) => [ns, (await loader()).default]));
        return Object.fromEntries(entries);
    };
});

class I18NextBackend implements BackendModule {
    type: "backend" = "backend" as const;
    init(): void {}
    read(language: string, _: string, callback: ReadCallback): void {
        const loader = locales[language];
        if (!loader) {
            callback(null, {});
            return;
        }

        try {
            loader()
                .then((data) => callback(null, data))
                .catch((err) => callback(err, null));
        } catch (err) {
            callback(err as Error, null);
        }
    }
}

i18n.use(new I18NextBackend())
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
        debug: !IS_PRODUCTION && false,
        fallbackLng: "en-US",
        load: "currentOnly",
        keySeparator: ".",
        preload: false,

        interpolation: {
            escapeValue: false,
            defaultVariables: {
                app: new Utils.String.Case(APP_NAME).toPascal(),
            },
        },

        detection: {
            order: ["localStorage", "navigator"],
            lookupLocalStorage: "lang",
            caches: ["localStorage"],
            convertDetectedLanguage: (lng) => {
                if (!LANGUAGE_LOCALES.includes(lng)) {
                    return "en-US";
                }

                return lng;
            },
        },
    });

export default i18n;
