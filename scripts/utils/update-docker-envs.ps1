$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $root

$values = @{}
if (Test-Path ".env") {
    foreach ($line in Get-Content ".env") {
        if ($line -match "^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$") {
            $value = $matches[2].Trim()
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            $values[$matches[1]] = $value
        }
    }
}

# Compose gives explicitly exported variables precedence over .env values.
foreach ($item in Get-ChildItem Env:) {
    $values[$item.Name] = $item.Value
}

function Get-Value {
    param([string]$Name)

    if ($values.ContainsKey($Name)) {
        return [string]$values[$Name]
    }
    return ""
}

function Resolve-Template {
    param([string]$Text)

    $result = $Text
    while ($true) {
        $start = $result.IndexOf('${', [StringComparison]::Ordinal)
        if ($start -lt 0) {
            return $result
        }

        $depth = 0
        $end = -1
        for ($index = $start; $index -lt $result.Length; $index++) {
            if ($index -lt $result.Length - 1 -and $result.Substring($index, 2) -eq '${') {
                $depth++
                continue
            }
            if ($result[$index] -eq '}' -and $depth -gt 0) {
                $depth--
                if ($depth -eq 0) {
                    $end = $index
                    break
                }
            }
        }
        if ($end -lt 0) {
            throw "Unclosed environment placeholder in '$Text'."
        }

        $body = $result.Substring($start + 2, $end - $start - 2)
        $separator = $body.IndexOf(':-', [StringComparison]::Ordinal)
        if ($separator -ge 0) {
            $name = $body.Substring(0, $separator)
            $fallback = $body.Substring($separator + 2)
        } else {
            $name = $body
            $fallback = $null
        }

        $replacement = Get-Value $name
        if ([string]::IsNullOrEmpty($replacement) -and $null -ne $fallback) {
            $replacement = Resolve-Template $fallback
        }

        $result = $result.Substring(0, $start) + $replacement + $result.Substring($end + 1)
    }
}

function Require-Value {
    param([string]$Name)

    if ([string]::IsNullOrEmpty((Get-Value $Name))) {
        throw "$Name is required before Phoenix can own the socket ingress."
    }
}

function Test-PositiveInteger {
    param([string]$Name)

    if ((Get-Value $Name) -notmatch '^[1-9][0-9]*$') {
        throw "$Name must be a positive integer before Phoenix can own the socket ingress."
    }
}

function Test-PostgresUrl {
    param([string]$Name)

    $value = Get-Value $Name
    if ([string]::IsNullOrEmpty($value)) {
        return
    }
    if ($value -notmatch '^postgres(ql)?://') {
        throw "$Name must start with postgresql:// or postgres://."
    }
    if ($value -notmatch '^postgres(ql)?://[^:]+(:[^@]+)?@[^:]+:[0-9]+/.+$') {
        throw "$Name may not be in the expected postgresql://user:password@host:port/database format."
    }
}

$maxFileSizeMb = Get-Value "MAX_FILE_SIZE_MB"
if ($maxFileSizeMb -notmatch '^[1-9][0-9]*$') {
    throw "MAX_FILE_SIZE_MB must be a positive integer."
}

# Leave room for multipart fields while preserving the configured per-file limit.
$values["MAX_REQUEST_BODY_SIZE_BYTES"] = (([int64]$maxFileSizeMb + 1) * 1MB).ToString()

$projectName = Get-Value "PROJECT_NAME"
if ([string]::IsNullOrEmpty($projectName)) {
    throw "PROJECT_NAME is required."
}

$socketOwner = Get-Value "SOCKET_OWNER"
if ([string]::IsNullOrEmpty($socketOwner)) { $socketOwner = "node" }
$socketRuntime = Get-Value "SOCKET_RUNTIME"
if ([string]::IsNullOrEmpty($socketRuntime)) { $socketRuntime = $socketOwner }
$editorOwner = Get-Value "EDITOR_SYNC_OWNER"
if ([string]::IsNullOrEmpty($editorOwner)) { $editorOwner = "node" }

switch ($socketOwner) {
    "node" {
        $values["SOCKET_HOST"] = "${projectName}_socket"
        $values["SOCKET_PORT"] = Get-Value "SOCKET_PORT"
    }
    "phoenix" {
        if ($socketRuntime -ne "phoenix") { throw "SOCKET_RUNTIME must be phoenix when SOCKET_OWNER is phoenix." }
        if ((Get-Value "SOCKET_PHOENIX_KAFKA_ENABLED") -ne "true") { throw "SOCKET_PHOENIX_KAFKA_ENABLED must be true before Phoenix can own the socket ingress." }
        if ((Get-Value "NOTIFICATION_EMAIL_OUTBOX_ENABLED") -ne "true") { throw "NOTIFICATION_EMAIL_OUTBOX_ENABLED must be true before Phoenix can own the socket ingress." }
        Require-Value "MAIL_SERVER"
        Require-Value "MAIL_FROM"
        Test-PositiveInteger "MAIL_PORT"
        Require-Value "BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP"
        foreach ($name in @("BROADCAST_NODE_FANOUT_CONSUMER_GROUP", "BROADCAST_NODE_SIDE_EFFECT_CONSUMER_GROUP")) {
            $nodeGroup = Get-Value $name
            if (-not [string]::IsNullOrEmpty($nodeGroup) -and (Get-Value "BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP") -eq $nodeGroup) {
                throw "BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP must differ from $name."
            }
        }
        foreach ($name in @("SOCKET_PHOENIX_BOARD_CHAT_SEND_ENABLED", "SOCKET_PHOENIX_BOARD_CHAT_RESUME_ENABLED", "SOCKET_PHOENIX_BOARD_CHAT_RECOVERY_ENABLED", "SOCKET_PHOENIX_EDITOR_AI_ENABLED")) {
            if ((Get-Value $name) -ne "true") { throw "$name must be true before Phoenix can own the socket ingress." }
        }
        if ($editorOwner -ne "phoenix") { throw "EDITOR_SYNC_OWNER must be phoenix before Phoenix can own the socket ingress." }
        if ((Get-Value "SOCKET_PHOENIX_EDITOR_SYNC_ENABLED") -ne "true") { throw "SOCKET_PHOENIX_EDITOR_SYNC_ENABLED must be true before Phoenix can own the socket ingress." }
        Test-PositiveInteger "SOCKET_PHOENIX_EDITOR_SYNC_EXPECTED_NODES"
        $values["SOCKET_HOST"] = "${projectName}_socket_phoenix"
        $values["SOCKET_PORT"] = "5690"
    }
    default { throw "SOCKET_OWNER must be node or phoenix." }
}

switch ($editorOwner) {
    "node" {
        $values["SOCKET_EDITOR_HOST"] = "${projectName}_socket"
        $values["SOCKET_EDITOR_PORT"] = Get-Value "SOCKET_PORT"
    }
    "phoenix" {
        if ((Get-Value "SOCKET_PHOENIX_EDITOR_SYNC_ENABLED") -ne "true") { throw "SOCKET_PHOENIX_EDITOR_SYNC_ENABLED must be true before Phoenix can own editor sync." }
        Test-PositiveInteger "SOCKET_PHOENIX_EDITOR_SYNC_EXPECTED_NODES"
        $values["SOCKET_EDITOR_HOST"] = "${projectName}_socket_phoenix"
        $values["SOCKET_EDITOR_PORT"] = "5690"
    }
    default { throw "EDITOR_SYNC_OWNER must be node or phoenix." }
}

$values["SOCKET_OWNER"] = $socketOwner
$values["SOCKET_RUNTIME"] = $socketRuntime
$values["EDITOR_SYNC_OWNER"] = $editorOwner

if ((Get-Value "KEY_PROVIDER_TYPE") -eq "openbao-local") {
    $values["KEY_PROVIDER_OPENBAO_URL"] = "http://${projectName}_vault:8200"
}

Test-PostgresUrl "POSTGRES_EXTERNAL_MAIN_URL"
Test-PostgresUrl "POSTGRES_EXTERNAL_REPLICA_URL"

$serviceTemplates = [ordered]@{
    nginx = @("server-common")
    api = @("server-common", "server")
    ui = @("server-common")
    socket = @("server-common", "server")
    graph = @("server-common", "server")
    db_backup = @("db-backup")
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
foreach ($service in $serviceTemplates.Keys) {
    $outputPath = Join-Path $root "docker\envs\.${service}.env"
    $outputLines = [System.Collections.Generic.List[string]]::new()
    foreach ($template in $serviceTemplates[$service]) {
        $templatePath = Join-Path $root "docker\envs\${template}.env.template"
        if (-not (Test-Path $templatePath)) {
            Write-Warning "Template '$templatePath' not found."
            continue
        }
        foreach ($line in Get-Content $templatePath) {
            if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=') {
                $resolved = Resolve-Template $line
                $outputLines.Add($resolved)
            }
        }
    }
    [System.IO.File]::WriteAllLines($outputPath, $outputLines, $utf8NoBom)
    Write-Output "Generated $outputPath from templates: $($serviceTemplates[$service] -join ' ')"
}
