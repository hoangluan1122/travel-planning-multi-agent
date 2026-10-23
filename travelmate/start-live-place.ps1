param(
    [ValidateRange(1024, 65535)][int]$Port = 8001,
    [ValidateSet('tool_workflow', 'adk_llm')][string]$Mode = 'tool_workflow'
)

$previousLivePlaceMode = $env:LIVE_PLACE_MODE
Push-Location -LiteralPath $PSScriptRoot
try {
    $env:LIVE_PLACE_MODE = $Mode
    Write-Host "Place Agent: http://127.0.0.1:$Port/ (engine: $Mode)"
    uv run --no-sync uvicorn app.live_place_api:create_app --factory --host 127.0.0.1 --port $Port
}
finally {
    $env:LIVE_PLACE_MODE = $previousLivePlaceMode
    Pop-Location
}
