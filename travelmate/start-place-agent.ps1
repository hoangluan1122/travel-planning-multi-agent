$ErrorActionPreference = "Stop"
Push-Location -LiteralPath $PSScriptRoot
try {
    & uv sync --extra dev --extra ai
    if ($LASTEXITCODE -ne 0) { throw "Cannot install project dependencies." }
    & uv run --no-sync uvicorn app.place_api:create_app --factory --host 127.0.0.1 --port 8001
    if ($LASTEXITCODE -ne 0) { throw "Place Agent failed to start. Check .env configuration." }
}
finally {
    Pop-Location
}
