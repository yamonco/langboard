import { AI_REQUEST_TIMEOUT } from "@/Constants";
import axios from "axios";

export const api = axios.create({
    timeout: AI_REQUEST_TIMEOUT * 1000,
    transformRequest: axios.defaults.transformRequest
        ? Array.isArray(axios.defaults.transformRequest)
            ? axios.defaults.transformRequest
            : [axios.defaults.transformRequest]
        : [],
});
