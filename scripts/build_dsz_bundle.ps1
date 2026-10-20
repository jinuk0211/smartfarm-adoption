param([switch]$IncludeWheels)
$ErrorActionPreference = 'Stop'
$Project = Split-Path -Parent $PSScriptRoot
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$Flavor = if ($IncludeWheels) { 'windows_py312_offline' } else { 'source' }
$Name = "dsz_${Flavor}_${Stamp}"
$Stage = Join-Path $Project "artifacts\dsz_packages\$Name"
New-Item -ItemType Directory -Path $Stage -Force | Out-Null

# Explicit allowlist: no farm raw data, credentials, public-data models or GPU weights.
$Files = @(
    'requirements-dsz-cpu.txt', 'run_dsz.ps1',
    'src\dsz_data.py', 'src\dsz_model.py', 'src\dsz_period.py',
    'src\dsz_observations.py', 'src\dsz_inseason.py',
    'scripts\prepare_dsz.py', 'scripts\train_dsz.py', 'scripts\predict_dsz.py',
    'scripts\run_dsz_inseason.py',
    'config\dsz_schema.json',
    'reports\dsz_onsite_guide.md', 'reports\dsz_schema_contract.md', 'reports\dsz_model_method.md',
    'reports\dsz_inseason_guide.md',
    'data\raw\dsz\epis_data_dictionary.zip', 'data\raw\dsz\epis_columns_user_supplied.txt',
    'data\examples\dsz\example_plans.csv',
    'data\examples\dsz\input\synthetic_period_definition.txt'
)
foreach ($Relative in $Files) {
    $Destination = Join-Path $Stage $Relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $Project $Relative) -Destination $Destination
}
$FixtureDestination = Join-Path $Stage 'data\examples\dsz\input'
New-Item -ItemType Directory -Path $FixtureDestination -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $Project 'data\examples\dsz\input') -File |
    Where-Object { $_.Extension -in '.csv', '.json' } |
    Copy-Item -Destination $FixtureDestination

# Separate synthetic observations and unseen-facility query, never private inputs.
$InSeasonSource = Join-Path $Project 'data\examples\dsz_inseason'
Get-ChildItem -LiteralPath $InSeasonSource -File -Recurse |
    Where-Object { $_.Extension -in '.csv', '.json', '.txt', '.py' } |
    ForEach-Object {
        $Relative = $_.FullName.Substring($InSeasonSource.Length + 1)
        $Destination = Join-Path $Stage (Join-Path 'data\examples\dsz_inseason' $Relative)
        New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $Destination
    }

if ($IncludeWheels) {
    $WheelSource = Join-Path $Project 'artifacts\dsz_wheelhouse'
    $Wheels = @(Get-ChildItem -LiteralPath $WheelSource -Filter '*.whl' -File)
    if (-not $Wheels.Count) { throw 'No offline wheels. Download requirements-dsz-cpu.txt first.' }
    $WheelDestination = Join-Path $Stage 'wheelhouse'
    New-Item -ItemType Directory -Path $WheelDestination -Force | Out-Null
    $Wheels | Copy-Item -Destination $WheelDestination
}

$Records = @(Get-ChildItem -LiteralPath $Stage -File -Recurse | ForEach-Object {
    [ordered]@{
        path = $_.FullName.Substring($Stage.Length + 1).Replace('\', '/')
        bytes = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
})
$Manifest = [ordered]@{
    package = $Name
    purpose = 'DSZ schema-based offline training; bundled example data is synthetic'
    created_at_utc = [DateTime]::UtcNow.ToString('o')
    target_environment = 'Windows x64, CPython 3.12'
    includes_wheels = [bool]$IncludeWheels
    includes_nonpublic_farm_rows = $false
    requires_documented_management_periods = $true
    onsite_execution_approval_confirmed = $false
    files = $Records
}
$Manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $Stage 'bundle_manifest.json') -Encoding utf8
$Archive = "$Stage.zip"
Compress-Archive -LiteralPath $Stage -DestinationPath $Archive -CompressionLevel Optimal
[ordered]@{
    directory = $Stage
    archive = $Archive
    bytes = (Get-Item -LiteralPath $Archive).Length
    sha256 = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
} | ConvertTo-Json
