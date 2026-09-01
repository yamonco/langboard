import { CHAT_UPLOAD_MAX_CONCURRENCY, MAX_FILE_SIZE_MB } from "@/Constants";
import BotRunner from "@/core/ai/BotRunner";
import { ApiErrorResponse, JsonResponse } from "@/core/server/ApiResponse";
import Routes from "@/core/server/Routes";
import Logger from "@/core/utils/Logger";
import { EInternalBotType } from "@/models/InternalBot";
import ProjectAssignedInternalBot from "@/models/ProjectAssignedInternalBot";
import ProjectAssignedUser from "@/models/ProjectAssignedUser";
import { Routing } from "@langboard/core/constants";
import { EApiErrorCode, EHttpStatus } from "@langboard/core/enums";
import fs from "fs";
import { File, IncomingForm } from "formidable";

let activeUploads = 0;

Routes.post(Routing.API.BOARD.CHAT.UPLOAD, async ({ req, user, params }) => {
    const { uid: projectUID } = params;
    if (!projectUID) {
        return ApiErrorResponse(EApiErrorCode.NF2001, EHttpStatus.HTTP_404_NOT_FOUND);
    }

    if (!(await ProjectAssignedUser.isAssigned(user.id, projectUID))) {
        return ApiErrorResponse(EApiErrorCode.PE1001, EHttpStatus.HTTP_403_FORBIDDEN);
    }

    const internalBotResult = await ProjectAssignedInternalBot.getInternalBotByProjectUID(EInternalBotType.ProjectChat, projectUID);
    if (!internalBotResult) {
        return ApiErrorResponse(EApiErrorCode.NF3004, EHttpStatus.HTTP_404_NOT_FOUND);
    }

    const [internalBot, _] = internalBotResult;

    if (activeUploads >= CHAT_UPLOAD_MAX_CONCURRENCY) {
        req.resume();
        return JsonResponse({ message: "Too many concurrent chat uploads." }, EHttpStatus.HTTP_503_SERVICE_UNAVAILABLE);
    }

    const form = new IncomingForm({
        keepExtensions: true,
        multiples: false,
        maxFileSize: MAX_FILE_SIZE_MB * 1024 * 1024,
    });

    let file: File | undefined;
    let filePath: string | null = null;
    activeUploads++;
    try {
        const [_, files] = await form.parse(req);
        file = files.attachment?.[0];
        if (!file) {
            return ApiErrorResponse(EApiErrorCode.OP1002, EHttpStatus.HTTP_406_NOT_ACCEPTABLE);
        }

        filePath = await BotRunner.upload({ internalBot, file });
        if (!filePath) {
            return ApiErrorResponse(EApiErrorCode.OP1002, EHttpStatus.HTTP_406_NOT_ACCEPTABLE);
        }

        return JsonResponse({ file_path: filePath }, EHttpStatus.HTTP_201_CREATED);
    } catch (error) {
        Logger.error(error, "\n");
        return ApiErrorResponse(EApiErrorCode.OP1002, EHttpStatus.HTTP_406_NOT_ACCEPTABLE);
    } finally {
        activeUploads--;
        if (file && filePath !== file.filepath) {
            await fs.promises.rm(file.filepath, { force: true }).catch((error) => Logger.error(error, "\n"));
        }
    }
});
