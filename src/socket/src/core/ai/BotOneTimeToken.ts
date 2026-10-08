import { JWT_ALGORITHM, JWT_SECRET_KEY, PROJECT_NAME } from "@/Constants";
import SnowflakeID from "@/core/db/SnowflakeID";
import { timegm } from "@/core/utils/DateTime";
import { EAgentPermissionLevel } from "@langboard/core/ai";
import jwt from "jsonwebtoken";

export const createOneTimeToken = (
    userId: number | SnowflakeID,
    apiPermissionLevel = EAgentPermissionLevel.Read,
    internal: "bot" | "socket_dispatch" = "bot"
) => {
    const date = new Date();
    date.setMinutes(date.getMinutes() + 5);
    const expiry = timegm(date);
    const encoded = jwt.sign(
        {
            sub: userId.toString(),
            internal,
            api_permission_level: apiPermissionLevel,
            exp: expiry,
        },
        JWT_SECRET_KEY,
        {
            algorithm: JWT_ALGORITHM,
            issuer: PROJECT_NAME,
        }
    );

    return encoded;
};
