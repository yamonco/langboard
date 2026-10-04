import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TQueryOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { ProjectWiki, User } from "@/core/models";
import { Utils } from "@langboard/core/utils";

export interface IGetWikisForm {
    project_uid: string;
}

export interface IGetWikisResponse {
    wikis: ProjectWiki.TModel[];
    project_members: User.TModel[];
}

const useGetWikis = (params: IGetWikisForm, options?: TQueryOptions<unknown, IGetWikisResponse>) => {
    const { query } = useQueryMutation();

    const getWikis = async () => {
        const url = Utils.String.format(Routing.API.BOARD.WIKI.GET_ALL, { uid: params.project_uid });
        const res = await api.get(url, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        return {
            wikis: ProjectWiki.Model.fromArray(res.data.wikis, true),
            project_members: User.Model.fromArray(res.data.project_members),
        };
    };

    const result = query([`get-wikis-${params.project_uid}`], getWikis, {
        ...options,
        retry: 0,
        refetchInterval: Infinity,
        refetchOnWindowFocus: false,
    });

    return result;
};

export default useGetWikis;
