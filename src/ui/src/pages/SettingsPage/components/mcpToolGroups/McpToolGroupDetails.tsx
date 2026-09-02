import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import MarkdownCodeBlock from "@/components/Markdown/CodeBlock";
import { API_URL, APP_NAME } from "@/constants";
import { McpToolGroup } from "@/core/models";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { copyToClipboard } from "@/core/utils/ComponentUtils";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import McpToolGroupActivation from "./McpToolGroupActivation";
import McpToolGroupName from "@/pages/SettingsPage/components/mcpToolGroups/McpToolGroupName";
import McpToolGroupDescription from "@/pages/SettingsPage/components/mcpToolGroups/McpToolGroupDescription";
import McpToolGroupTools from "@/pages/SettingsPage/components/mcpToolGroups/McpToolGroupTools";

export interface IMcpToolGroupDetailsProps {
    toolGroupUID?: string;
}

function McpToolGroupDetails({ toolGroupUID }: IMcpToolGroupDetailsProps) {
    const toolGroup = McpToolGroup.Model.useModel((model) => !!toolGroupUID && model.uid === toolGroupUID, [toolGroupUID]);
    if (!toolGroup) {
        return null;
    }

    return (
        <ModelRegistry.McpToolGroup.Provider model={toolGroup}>
            <McpToolGroupDetailsDisplay />
        </ModelRegistry.McpToolGroup.Provider>
    );
}

function McpToolGroupDetailsDisplay() {
    const [t] = useTranslation();
    const { model: toolGroup } = ModelRegistry.McpToolGroup.useContext();
    const [copied, setCopied] = useState(false);

    const mcpEndpoint = `${API_URL}/mcp/stream`;

    const mcpServerConfig = {
        mcpServers: {
            [`${APP_NAME}-${toolGroup.name}-${toolGroup.uid}`]: {
                transport: "http",
                url: mcpEndpoint,
                headers: {
                    "X-Api-Key": "YOUR_API_KEY_HERE",
                    "X-MCP-Tool-Group-UID": toolGroup.uid,
                },
            },
        },
    };

    const mcpConfigJson = JSON.stringify(mcpServerConfig, null, 2);

    const handleCopy = async () => {
        await copyToClipboard(mcpConfigJson);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    return (
        <Flex direction="col" gap="6" w="full">
            <Flex justify="between" items="start" gap="2">
                <Flex direction="col" gap="2" w="full">
                    <McpToolGroupName />
                    <McpToolGroupDescription />
                </Flex>
                <Box className="whitespace-nowrap">
                    <McpToolGroupActivation toolGroup={toolGroup} />
                </Box>
            </Flex>

            <Flex direction="col" gap="3">
                <Flex justify="between" items="center">
                    <h3 className="text-sm font-semibold">{t("mcp.MCP Server Configuration")}</h3>
                    <Button variant="outline" size="sm" className="gap-2" onClick={handleCopy}>
                        <IconComponent icon={copied ? "check" : "copy"} size="4" />
                        {t(copied ? "common.Copied." : "mcp.Copy config")}
                    </Button>
                </Flex>

                <Box w="full" className="[&_.prose]:!max-w-full">
                    <MarkdownCodeBlock code={mcpConfigJson} language="json" />
                </Box>
            </Flex>

            <McpToolGroupTools />
        </Flex>
    );
}

export default McpToolGroupDetails;
