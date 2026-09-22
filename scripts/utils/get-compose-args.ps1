param(
    [string]$WithDocs = "false",
    [string]$WithUiWatcher = "false",
    [string]$WithOllamaCpu = "false",
    [string]$WithOllamaGpu = "false",
    [string]$WithOtel = "false",
    [string]$WithDbBackup = "true"
)

# Get Docker Compose arguments based on environment variables
# Usage: .\scripts\get-compose-args.ps1

# Load .env file
if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        if ($_ -match '^([^=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            Set-Item -Path "env:$name" -Value $value
        }
    }
}

$env:WITH_DOCS = $WithDocs
$env:WITH_UI_WATCHER = $WithUiWatcher
$env:WITH_OLLAMA_CPU = $WithOllamaCpu
$env:WITH_OLLAMA_GPU = $WithOllamaGpu
$env:WITH_OTEL = $WithOtel
$env:WITH_DB_BACKUP = $WithDbBackup

# Function to validate PostgreSQL URL
function Test-PostgresUrl {
    param(
        [string]$Url,
        [string]$UrlName
    )

    if (-not [string]::IsNullOrEmpty($Url)) {
        # Check if URL matches postgresql:// or postgres:// format
        if ($Url -notmatch '^postgres(ql)?://') {
            Write-Host "Error: $UrlName must start with postgresql:// or postgres://" -ForegroundColor Red
            Write-Host "Current value: $Url"
            exit 1
        }

        # Basic structure check: postgresql://user:pass@host:port/db
        if ($Url -notmatch '^postgres(ql)?://[^:]+(:[^@]+)?@[^:]+:[0-9]+/.+$') {
            Write-Host "Warning: $UrlName may not be in correct format (postgresql://user:password@host:port/database)" -ForegroundColor Yellow
            Write-Host "Current value: $Url"
            $response = Read-Host "Continue anyway? (y/N)"
            if ($response -ne 'y' -and $response -ne 'Y') {
                exit 1
            }
        }

        Write-Host "✓ $UrlName is valid: $Url" -ForegroundColor Green
    }
}

# Validate external postgres URLs if they are set
if (-not [string]::IsNullOrEmpty($env:POSTGRES_EXTERNAL_MAIN_URL)) {
    Test-PostgresUrl -Url $env:POSTGRES_EXTERNAL_MAIN_URL -UrlName "POSTGRES_EXTERNAL_MAIN_URL"

    if (-not [string]::IsNullOrEmpty($env:POSTGRES_EXTERNAL_REPLICA_URL)) {
        Test-PostgresUrl -Url $env:POSTGRES_EXTERNAL_REPLICA_URL -UrlName "POSTGRES_EXTERNAL_REPLICA_URL"
    }
}

$COMPOSE_PREFIX = "./docker/docker-compose"

# Base compose args (include the main compose file)
$COMPOSE_ARGS = "-f ${COMPOSE_PREFIX}.yaml -f ${COMPOSE_PREFIX}.kafka.yaml"

# Check if we should use external postgres (skip postgres compose files)
if ([string]::IsNullOrEmpty($env:POSTGRES_EXTERNAL_MAIN_URL)) {
    $COMPOSE_ARGS += " -f ${COMPOSE_PREFIX}.pg.yaml"
}

# Backup service is enabled by default
$withDbBackup = if ([string]::IsNullOrEmpty($env:WITH_DB_BACKUP)) { "true" } else { $env:WITH_DB_BACKUP.ToLowerInvariant() }
if ($withDbBackup -eq "true") {
    $COMPOSE_ARGS += " -f ${COMPOSE_PREFIX}.backup.yaml"
}

$COMPOSE_ARGS += " -f ${COMPOSE_PREFIX}.redis.yaml -f ${COMPOSE_PREFIX}.server.yaml --env-file ./.env"

if ($env:SOCKET_OWNER -eq "phoenix") {
    $COMPOSE_ARGS += " -f ${COMPOSE_PREFIX}.phoenix-owner.yaml --profile socket-phoenix"
}
elseif ($env:EDITOR_SYNC_OWNER -eq "phoenix") {
    $COMPOSE_ARGS += " -f ${COMPOSE_PREFIX}.phoenix-editor-owner.yaml --profile socket-phoenix"
}

# Optional compose args
$VAULT_COMPOSE_ARGS = "-f ${COMPOSE_PREFIX}.vault.yaml"
$DOCS_COMPOSE_ARGS = "-f ${COMPOSE_PREFIX}.docs.yaml"
$UI_WATCHER_COMPOSE_ARGS = "-f ${COMPOSE_PREFIX}.ui-watcher.yaml"
$OLLAMA_SHARED_COMPOSE_ARGS = "-f ${COMPOSE_PREFIX}.ollama.shared.yaml"
$OLLAMA_CPU_COMPOSE_ARGS = "-f ${COMPOSE_PREFIX}.ollama.cpu.yaml ${OLLAMA_SHARED_COMPOSE_ARGS}"
$OLLAMA_GPU_COMPOSE_ARGS = "-f ${COMPOSE_PREFIX}.ollama.gpu.yaml ${OLLAMA_SHARED_COMPOSE_ARGS}"
$OTEL_COMPOSE_ARGS = "-f ${COMPOSE_PREFIX}.otel.yaml --profile socket-phoenix --profile socket-phoenix-otel"

# Append optional compose args based on environment variables
if ($env:WITH_DOCS -eq "true") {
    $COMPOSE_ARGS += " ${DOCS_COMPOSE_ARGS}"
}

if ($env:WITH_UI_WATCHER -eq "true") {
    $COMPOSE_ARGS += " ${UI_WATCHER_COMPOSE_ARGS}"
}

if ($env:WITH_OLLAMA_CPU -eq "true") {
    $COMPOSE_ARGS += " ${OLLAMA_CPU_COMPOSE_ARGS}"
}

if ($env:WITH_OLLAMA_GPU -eq "true") {
    $COMPOSE_ARGS += " ${OLLAMA_GPU_COMPOSE_ARGS}"
}

if ($env:WITH_OTEL -eq "true") {
    $COMPOSE_ARGS += " ${OTEL_COMPOSE_ARGS}"
}

# Check if vault is needed based on KEY_PROVIDER_TYPE in .env file
if (Test-Path ".env") {
    $envContent = Get-Content ".env" | Where-Object { $_ -match '^KEY_PROVIDER_TYPE=openbao-local' }
    if ($envContent) {
        $COMPOSE_ARGS += " ${VAULT_COMPOSE_ARGS}"
    }
}

# Native commands require each Compose argument as a separate array item.
Write-Output ($COMPOSE_ARGS -split ' ')
