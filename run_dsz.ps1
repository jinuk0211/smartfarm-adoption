param(
    [switch]$Demo,
    [string]$InputDir,
    [string]$Plans,
    [string]$OutputDir,
    [ValidateSet('single_record_per_cycle', 'incremental_sum', 'latest_cumulative')]
    [string]$ManagementPolicy = 'single_record_per_cycle',
    [ValidateSet('utf-8-sig', 'cp949')]
    [string]$Encoding = 'utf-8-sig',
    [string]$Python = 'python',
    [switch]$UseExistingEnvironment
)

$ErrorActionPreference = 'Stop'
if ($Demo) {
    if ($InputDir -or $Plans) { throw '-Demo cannot be combined with -InputDir or -Plans.' }
    $InputDir = Join-Path $PSScriptRoot 'data\examples\dsz\input'
    $Plans = Join-Path $PSScriptRoot 'data\examples\dsz\example_plans.csv'
} elseif (-not $InputDir -or -not $Plans) {
    throw 'Use -Demo, or provide both -InputDir and -Plans for onsite data.'
}
$InputDir = (Resolve-Path -LiteralPath $InputDir).Path
$Plans = (Resolve-Path -LiteralPath $Plans).Path
if (-not $OutputDir) {
    $OutputDir = Join-Path $PSScriptRoot ('runs\' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
}
if (Test-Path -LiteralPath $OutputDir) { throw 'OutputDir already exists. Choose a new run directory.' }

if (-not $UseExistingEnvironment) {
    $Wheelhouse = Join-Path $PSScriptRoot 'wheelhouse'
    if (-not (Test-Path -LiteralPath $Wheelhouse)) {
        throw 'Use the offline bundle with wheelhouse, or an installed Python environment with -UseExistingEnvironment.'
    }
    & $Python -c "import sys,platform; assert sys.version_info[:2] == (3,12) and sys.platform == 'win32' and platform.machine().upper() == 'AMD64', 'Bundled wheels require Windows x64 Python 3.12'"
    if ($LASTEXITCODE -ne 0) { throw 'Python platform/version check failed.' }
    $Venv = Join-Path $PSScriptRoot '.venv-dsz'
    if (-not (Test-Path -LiteralPath (Join-Path $Venv 'Scripts\python.exe'))) {
        & $Python -m venv $Venv
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
    }
    $Python = Join-Path $Venv 'Scripts\python.exe'
    & $Python -m pip install --no-index --find-links $Wheelhouse -r (Join-Path $PSScriptRoot 'requirements-dsz-cpu.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Offline package installation failed.' }
}

$Prepared = Join-Path $OutputDir 'prepared'
$Models = Join-Path $OutputDir 'models'
& $Python (Join-Path $PSScriptRoot 'scripts\prepare_dsz.py') --input-dir $InputDir --output-dir $Prepared --management-policy $ManagementPolicy --encoding $Encoding
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed. Review the validation report before training.' }
& $Python (Join-Path $PSScriptRoot 'scripts\train_dsz.py') --data-dir $Prepared --output-dir $Models
if ($LASTEXITCODE -ne 0) { throw 'Model comparison/training failed.' }
& $Python (Join-Path $PSScriptRoot 'scripts\predict_dsz.py') --artifact-dir $Models --plans $Plans --output (Join-Path $OutputDir 'predictions.csv')
if ($LASTEXITCODE -ne 0) { throw 'Plan prediction failed.' }
Write-Output "Completed: $OutputDir"
if ($Demo) { Write-Output 'SYNTHETIC DEMO ONLY: these scores and predictions are not actual farm performance.' }
