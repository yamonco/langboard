/* eslint-disable @typescript-eslint/no-explicit-any */
export type TGetModelOptions = {
    api?: {
        get(url: string): Promise<{ data: any }>;
        post(url: string, data: Record<string, unknown>): Promise<{ data: any }>;
    };
    values: Record<string, any>;
    envs: Record<string, any>;
};
