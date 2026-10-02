import { Utils } from "@langboard/core/utils";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

const useUpdateDateDistance = (date: Date | undefined, timeout: number = 60000) => {
    const [t, i18n] = useTranslation();
    const [distance, setDistance] = useState(date ? Utils.String.formatDateDistance(i18n, t, date) : "");

    useEffect(() => {
        let runningTimeout: NodeJS.Timeout | undefined;
        const updateCommentedAt = () => {
            if (runningTimeout) {
                clearTimeout(runningTimeout);
                runningTimeout = undefined;
            }

            setDistance(date ? Utils.String.formatDateDistance(i18n, t, date) : "");

            runningTimeout = setTimeout(updateCommentedAt, timeout);
        };

        updateCommentedAt();

        return () => {
            clearTimeout(runningTimeout);
            runningTimeout = undefined;
        };
    }, [date, i18n, i18n.language, t, timeout]);

    return distance;
};

export default useUpdateDateDistance;
