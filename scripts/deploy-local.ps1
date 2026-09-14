[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-EnvironmentVariable {
    param([Parameter(Mandatory = $true)][string]$Name)

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Variavel obrigatoria ausente: $Name"
    }
}

function Get-HealthSnapshot {
    $output = @(
        & docker compose run --rm --no-deps backend `
            python -m src.healthcheck --wait --tentativas 10 --intervalo 1
    )
    $exitCode = $LASTEXITCODE
    $output | ForEach-Object { Write-Host $_ }
    if ($exitCode -ne 0) {
        throw "Healthcheck somente leitura falhou com codigo $exitCode."
    }
    $jsonLine = $output |
        ForEach-Object { "$_".Trim() } |
        Where-Object { $_.StartsWith("{") } |
        Select-Object -Last 1
    if ([string]::IsNullOrWhiteSpace($jsonLine)) {
        throw "Healthcheck nao retornou o snapshot JSON esperado."
    }
    return $jsonLine | ConvertFrom-Json
}

$requiredVariables = @(
    "PDOH_CX_ALLOWED_REPOSITORY",
    "PDOH_DB_USER",
    "PDOH_DB_PASSWORD",
    "PDOH_MIGRATION_USER",
    "PDOH_MIGRATION_PASSWORD",
    "MYSQL_ROOT_PASSWORD"
)
$requiredVariables | ForEach-Object { Assert-EnvironmentVariable -Name $_ }

if ($env:PDOH_CX_ALLOWED_REPOSITORY -notmatch '(?i)/PDOH_CX$') {
    throw "Deploy recusado: PDOH_CX_ALLOWED_REPOSITORY deve terminar em /PDOH_CX."
}
if ($env:GITHUB_REPOSITORY -and $env:GITHUB_REPOSITORY -ne $env:PDOH_CX_ALLOWED_REPOSITORY) {
    throw "Deploy recusado: o runner recebeu um repositorio nao autorizado."
}

$remoteOutput = @(& git remote get-url --push origin 2>$null)
$remoteExitCode = $LASTEXITCODE
$remote = if ($remoteOutput.Count -gt 0) { "$($remoteOutput[-1])".Trim() } else { "" }
if ($remoteExitCode -ne 0 -or $remote -notmatch '(?i)(?:/|:)PDOH_CX(?:\.git)?$') {
    throw "Deploy recusado: remote origin nao aponta para o repositorio PDOH_CX."
}
if ($remote -match '(?i)(?:/|:)PDOH_EXCLUSIVO(?:\.git)?$') {
    throw "Deploy recusado: o projeto original PDOH_EXCLUSIVO nunca pode ser destino do CD."
}

$mysqlHealth = (& docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}ausente{{end}}' pdoh_cx_mysql).Trim()
if ($LASTEXITCODE -ne 0 -or $mysqlHealth -ne "healthy") {
    throw "Deploy interrompido: o MySQL local pdoh_cx_mysql nao esta healthy."
}

& docker compose --profile pipeline config --quiet
if ($LASTEXITCODE -ne 0) { throw "docker compose config falhou." }

Write-Host "Construindo somente a imagem do backend; banco e volumes permanecem intactos."
& docker compose build backend
if ($LASTEXITCODE -ne 0) { throw "Build do backend falhou." }

$snapshotAntes = Get-HealthSnapshot

Write-Host "Recriando somente o backend com --no-deps; migracao e pipeline nao sao executados."
& docker compose up --no-deps --force-recreate --abort-on-container-exit --exit-code-from backend backend
if ($LASTEXITCODE -ne 0) { throw "Backend falhou durante o deploy." }

$snapshotDepois = Get-HealthSnapshot
$antesCanonico = $snapshotAntes | ConvertTo-Json -Depth 8 -Compress
$depoisCanonico = $snapshotDepois | ConvertTo-Json -Depth 8 -Compress
if ($antesCanonico -ne $depoisCanonico) {
    throw "Deploy recusado: contagens dos bancos mudaram durante uma etapa que deve ser somente leitura."
}

$artifactDirectory = Join-Path $PSScriptRoot "..\artifacts"
New-Item -ItemType Directory -Path $artifactDirectory -Force | Out-Null
$commit = (& git rev-parse HEAD).Trim()
$evidence = [ordered]@{
    timestamp_utc = [DateTime]::UtcNow.ToString("o")
    status = "APROVADO"
    repository = $env:PDOH_CX_ALLOWED_REPOSITORY
    commit = $commit
    mysql_container = "pdoh_cx_mysql"
    mysql_health = $mysqlHealth
    rede = "pdoh_cx_network"
    servico_atualizado = "backend"
    migracao_executada = $false
    pipeline_executado = $false
    carga_executada = $false
    contagens_preservadas = $true
    snapshot = $snapshotDepois
}
$evidence |
    ConvertTo-Json -Depth 10 |
    Set-Content -LiteralPath (Join-Path $artifactDirectory "cd-deploy.json") -Encoding utf8

Write-Host "DEPLOY_LOCAL_OK: backend validado; banco, migracoes e dados permaneceram inalterados."
