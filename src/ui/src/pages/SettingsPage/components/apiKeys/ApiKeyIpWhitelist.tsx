import { formatNumber } from "@/core/utils/LocaleFormat";
import { ApiKeySettingModel } from "@/core/models";
import { memo } from "react";
import { useTranslation } from "react-i18next";

export interface IApiKeyIpWhitelistProps {
    apiKey: ApiKeySettingModel.TModel;
}

const ApiKeyIpWhitelist = memo(({ apiKey }: IApiKeyIpWhitelistProps) => {
    const [t, i18n] = useTranslation();
    const ipWhitelist = apiKey.useField("ip_whitelist");

    const getIpWhitelistText = (ips: string[]) => {
        if (!ips || ips.length === 0) {
            return t("settings.All IPs");
        }
        if (ips.length === 1) {
            return ips[0];
        }
        return `${ips[0]} +${formatNumber(ips.length - 1, i18n.language)}`;
    };

    return <span className="truncate text-center">{getIpWhitelistText(ipWhitelist)}</span>;
});

export default ApiKeyIpWhitelist;
