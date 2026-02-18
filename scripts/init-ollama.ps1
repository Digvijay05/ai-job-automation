# init-ollama.ps1 — Pull the configured cloud model on first startup.
#
# Usage:
#   docker compose up -d
#   .\scripts\init-ollama.ps1
#
# Idempotent: safe to re-run. Ollama skips if model already exists.

param(
    [string]$ContainerName = "ollama",
    [string]$Model = $env:OLLAMA_MODEL,
    [string]$Tag = "cloud",
    [int]$MaxRetries = 30,
    [int]$RetryInterval = 5
)

if (-not $Model) { $Model = "llama3" }
$FullModel = "${Model}:${Tag}"

Write-Host "[init-ollama] Waiting for container '$ContainerName' to be healthy..."

for ($i = 1; $i -le $MaxRetries; $i++) {
    try {
        $status = docker inspect --format='{{.State.Health.Status}}' $ContainerName 2>$null
    } catch {
        $status = "not_found"
    }

    if ($status -eq "healthy") {
        Write-Host "[init-ollama] Container is healthy."
        break
    }

    if ($i -eq $MaxRetries) {
        Write-Error "[init-ollama] ERROR: Container did not become healthy after $($MaxRetries * $RetryInterval)s."
        exit 1
    }

    Write-Host "[init-ollama] Status: $status. Retrying in ${RetryInterval}s... ($i/$MaxRetries)"
    Start-Sleep -Seconds $RetryInterval
}

Write-Host "[init-ollama] Checking if model '$Model' is already available..."
$existing = docker exec $ContainerName ollama list 2>$null | Select-String -Pattern $Model -Quiet

if ($existing) {
    Write-Host "[init-ollama] Model '$Model' already cached. Skipping pull."
} else {
    Write-Host "[init-ollama] Pulling model '$FullModel' from Cloud Registry..."
    docker exec $ContainerName ollama pull $FullModel
    Write-Host "[init-ollama] Pull complete."
}

Write-Host "[init-ollama] Warming up model (loading into memory)..."
docker exec $ContainerName ollama run $FullModel "ping" 2>$null | Out-Null

Write-Host "[init-ollama] Verifying model is loaded..."
$tags = docker exec $ContainerName curl -sf http://localhost:11434/api/tags 2>$null
if ($tags -match $Model) {
    Write-Host "[init-ollama] Model '$FullModel' is ready."
} else {
    Write-Warning "[init-ollama] Model may not be fully loaded. Check: docker exec $ContainerName ollama list"
}

Write-Host "[init-ollama] Done."
