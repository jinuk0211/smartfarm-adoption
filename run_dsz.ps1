param(
    [switch]$Demo,
    [switch]$InSeason,
    [string]$InputDir,
    [string]$Plans,
    [string]$Requests,
    [string]$QueryInputDir,
    [ValidateRange(1, 730)]
    [int]$CutoffDays = 30,
    [ValidateRange(1, 365)]
    [int]$WindowDays = 28,
    [string]$Crop = '딸기',
    [string]$OutputDir,
    [string]$PeriodConfirmation,
    [ValidateSet('single_record_per_cycle', 'incremental_sum', 'latest_cumulative')]
    [string]$ManagementPolicy = 'single_record_per_cycle',
    [ValidateSet('utf-8-sig', 'cp949')]
    [string]$Encoding = 'utf-8-sig',
    [string]$Python = 'python',
    [switch]$UseExistingEnvironment
)

$ErrorActionPreference = 'Stop'
if ($Demo) {
    if ($InputDir -or $Plans -or $Requests -or $QueryInputDir -or $PeriodConfirmation) { throw '-Demo cannot be combined with custom input paths.' }
    if ($InSeason) {
        $InputDir = Join-Path $PSScriptRoot 'data\examples\dsz_inseason\input'
        $QueryInputDir = Join-Path $PSScriptRoot 'data\examples\dsz_inseason\query'
        $Requests = Join-Path $PSScriptRoot 'data\examples\dsz_inseason\requests.csv'
    } else {
        $InputDir = Join-Path $PSScriptRoot 'data\examples\dsz\input'
        $Plans = Join-Path $PSScriptRoot 'data\examples\dsz\example_plans.csv'
    }
    $PeriodConfirmation = Join-Path $InputDir 'period_confirmation.json'
} elseif (-not $InputDir -or ($InSeason -and -not $Requests) -or (-not $InSeason -and -not $Plans)) {
    throw 'Provide -InputDir and -Plans; for -InSeason provide -InputDir and -Requests instead.'
}
if (($InSeason -and $Plans) -or (-not $InSeason -and ($Requests -or $QueryInputDir))) { throw 'Preplant plans and in-season requests use separate input contracts.' }
if (-not $PeriodConfirmation) {
    throw 'Training requires -PeriodConfirmation with documented source periods. Run scripts/prepare_dsz.py alone for an audit without confirmation.'
}
$InputDir = (Resolve-Path -LiteralPath $InputDir).Path
if ($InSeason) {
    $Requests = (Resolve-Path -LiteralPath $Requests).Path
    if (-not $QueryInputDir) { $QueryInputDir = $InputDir }
    $QueryInputDir = (Resolve-Path -LiteralPath $QueryInputDir).Path
} else {
    $Plans = (Resolve-Path -LiteralPath $Plans).Path
}
$PeriodConfirmation = (Resolve-Path -LiteralPath $PeriodConfirmation).Path
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
& $Python (Join-Path $PSScriptRoot 'scripts\prepare_dsz.py') --input-dir $InputDir --output-dir $Prepared --management-policy $ManagementPolicy --period-confirmation $PeriodConfirmation --encoding $Encoding
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed. Review the validation report before training.' }
if ($InSeason) {
    & $Python (Join-Path $PSScriptRoot 'scripts\run_dsz_inseason.py') train --data-dir $Prepared --input-dir $InputDir --output-dir $Models --cutoff-days $CutoffDays --window-days $WindowDays --crop $Crop --encoding $Encoding
    if ($LASTEXITCODE -ne 0) { throw 'In-season model comparison/training failed.' }
    & $Python (Join-Path $PSScriptRoot 'scripts\run_dsz_inseason.py') predict --artifact-dir $Models --input-dir $QueryInputDir --requests $Requests --output (Join-Path $OutputDir 'predictions.csv') --encoding $Encoding
} else {
    & $Python (Join-Path $PSScriptRoot 'scripts\train_dsz.py') --data-dir $Prepared --output-dir $Models
    if ($LASTEXITCODE -ne 0) { throw 'Model comparison/training failed.' }
    & $Python (Join-Path $PSScriptRoot 'scripts\predict_dsz.py') --artifact-dir $Models --plans $Plans --output (Join-Path $OutputDir 'predictions.csv')
}
if ($LASTEXITCODE -ne 0) { throw 'Plan prediction failed.' }
Write-Output "Completed: $OutputDir"
if ($Demo) { Write-Output 'SYNTHETIC DEMO ONLY: these scores and predictions are not actual farm performance.' }
