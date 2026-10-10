import { Utils } from "@langboard/core/utils";
import { Duration } from "date-fns";
import currentI18n, { TFunction, i18n } from "i18next";
import { formatDateDistance, formatDateTime, formatTimerDuration } from "@/core/utils/LocaleFormat";
import { API_URL } from "@/constants";

Utils.String.formatDateLocale = (date: Date) => formatDateTime(date, currentI18n.language);

Utils.String.formatDateDistance = (i18n: i18n, _translate: TFunction<"translation", undefined>, date: Date): string =>
    formatDateDistance(date, i18n.language);

Utils.String.formatTimerDuration = (duration: Duration) => formatTimerDuration(duration, currentI18n.language);

Utils.String.convertServerFileURL = <TURL extends string | undefined>(url: TURL): TURL extends string ? string : undefined => {
    if (!url) {
        return url as unknown as TURL extends string ? string : undefined;
    }

    if (url.startsWith("http")) {
        return url as unknown as TURL extends string ? string : undefined;
    }

    return `${API_URL}${url}` as unknown as TURL extends string ? string : undefined;
};

Utils.String.isValidURL = (str: unknown): bool => {
    if (!Utils.Type.isString(str)) {
        return false;
    }

    try {
        new URL(str);
        return true;
    } catch (err) {
        return false;
    }
};
