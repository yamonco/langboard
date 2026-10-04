[System.Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($null -eq $docker) {
    Write-Host "Docker is not installed or not found in PATH. Please install Docker to proceed."
    Write-Host "You can download it from https://docs.docker.com/desktop/setup/install/windows-install/"
    Pause
    Exit 1
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env" -Force | Out-Null
}

# Set environment variables for get-compose-args.ps1
$env:WITH_DOCS = "false"
$env:WITH_UI_WATCHER = "false"
$env:WITH_OLLAMA_CPU = "false"
$env:WITH_OLLAMA_GPU = "false"

# Parse arguments to set compose options
foreach ($arg in $args) {
    if ($arg -eq "docs") {
        $env:WITH_DOCS = "true"
    }
    elseif ($arg -eq "ui-watcher") {
        $env:WITH_UI_WATCHER = "true"
    }
    elseif ($arg -eq "ollama-cpu") {
        $env:WITH_OLLAMA_CPU = "true"
    }
    elseif ($arg -eq "ollama-gpu") {
        $env:WITH_OLLAMA_GPU = "true"
    }
}

& make start_docker "WITH_DOCS=$env:WITH_DOCS" "WITH_UI_WATCHER=$env:WITH_UI_WATCHER" "WITH_OLLAMA_CPU=$env:WITH_OLLAMA_CPU" "WITH_OLLAMA_GPU=$env:WITH_OLLAMA_GPU" "WITH_OTEL=true"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Pause
