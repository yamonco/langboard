/* eslint-disable @typescript-eslint/no-explicit-any */
import { TBigIntString } from "@/core/db/BaseModel";
import { EAgentApprovalPolicy, EAgentPermissionLevel, EApiPermission } from "@langboard/core/ai";

export interface IBotRequestModel {
    message: string;
    projectUID: string;
    userId: TBigIntString;
    inputType?: string;
    outputType?: string;
    sessionId?: string;
    runId?: string;
    threadScope?: "run" | "session";
    tweaks?: Record<string, Record<string, any>>;
    restData?: Record<string, any> & {
        api_permission_level?: EAgentPermissionLevel;
        api_approval_policy?: Partial<Record<EApiPermission, EAgentApprovalPolicy>>;
    };
    isTitle?: bool;
    filePath?: string;
}
