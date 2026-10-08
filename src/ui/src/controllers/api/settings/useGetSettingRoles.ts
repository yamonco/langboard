import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TQueryOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { SettingRole, ApiKeyRole, McpRole } from "@/core/models/roles";

export interface IGetSettingRolesResponse {
    setting_role_actions: SettingRole.TActions[];
    api_key_role_actions: ApiKeyRole.TActions[];
    mcp_role_actions: McpRole.TActions[];
}

const useGetSettingRoles = (options?: TQueryOptions<unknown, IGetSettingRolesResponse>) => {
    const { query } = useQueryMutation();

    const getSettingRoles = async () => {
        const res = await api.post(Routing.API.SETTINGS.GET_SETTING_ROLES, undefined, {
            timeout: 30000,
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        return res.data;
    };

    const result = query(["get-setting-roles"], getSettingRoles, {
        ...options,
        retry: 0,
        refetchInterval: Infinity,
        refetchOnWindowFocus: false,
    });
    return result;
};

export default useGetSettingRoles;
