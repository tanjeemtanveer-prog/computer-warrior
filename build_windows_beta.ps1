[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$BuildRoot = (Join-Path $env:USERPROFILE "cwbuild\computer-warrior-v0.2.1"),
    [switch]$Windowed
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-LastExitCode {
    param([Parameter(Mandatory = $true)][string]$Step)

    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE. The build folder was retained for inspection."
    }
}

$projectRoot = Split-Path -Parent $PSCommandPath
$sourceEntry = Join-Path $projectRoot "run_computer_warrior.py"
$webSource = Join-Path $projectRoot "web"
$requirementsPath = Join-Path $projectRoot "requirements.txt"
$configPath = Join-Path $projectRoot "computer_warrior\config.py"

foreach ($requiredPath in @($sourceEntry, $webSource, $requirementsPath, $configPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required source path is missing: $requiredPath"
    }
}

$configText = [System.IO.File]::ReadAllText($configPath)
if ($configText -notmatch 'APP_VERSION\s*=\s*"([^"]+)"') {
    throw "Could not read APP_VERSION from $configPath"
}
$appVersion = $Matches[1]

$git = Get-Command git -ErrorAction Stop
$dirty = & $git.Source -C $projectRoot status --porcelain
Assert-LastExitCode "Git status check"
if (-not [string]::IsNullOrWhiteSpace(($dirty -join "`n"))) {
    throw "The source tree has uncommitted changes. Commit or stash them before packaging."
}

$sourceRevision = (& $git.Source -C $projectRoot rev-parse HEAD).Trim()
Assert-LastExitCode "Git revision lookup"

$resolvedBuildRoot = [System.IO.Path]::GetFullPath($BuildRoot)
if (Test-Path -LiteralPath $resolvedBuildRoot) {
    throw "Build root already exists: $resolvedBuildRoot`nChoose a new -BuildRoot. Existing files were not changed."
}

$venvDir = Join-Path $resolvedBuildRoot ".venv"
$buildPython = Join-Path $venvDir "Scripts\python.exe"
$distRoot = Join-Path $resolvedBuildRoot "dist"
$workRoot = Join-Path $resolvedBuildRoot "work"
$specRoot = Join-Path $resolvedBuildRoot "spec"
$appName = "ComputerWarrior"
$uiMode = if ($Windowed) { "--windowed" } else { "--console" }
$modeName = if ($Windowed) { "windowed" } else { "console" }

New-Item -ItemType Directory -Path $resolvedBuildRoot | Out-Null

Write-Host "Creating isolated build environment in $resolvedBuildRoot"
& py -3 --version
Assert-LastExitCode "Python launcher check"

& py -3 -m venv $venvDir
Assert-LastExitCode "Virtual-environment creation"

& $buildPython -m pip install --upgrade pip
Assert-LastExitCode "pip update"

& $buildPython -m pip install -r $requirementsPath
Assert-LastExitCode "Computer Warrior dependency installation"

& $buildPython -m pip install "pyinstaller==6.21.0" "pyinstaller-hooks-contrib==2026.6"
Assert-LastExitCode "PyInstaller installation"

$webDataArgument = "--add-data=$($webSource):web"
Write-Host "Bundling dashboard files as: $webDataArgument"

& $buildPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    $uiMode `
    --name $appName `
    --paths $projectRoot `
    $webDataArgument `
    --collect-all pynput `
    --copy-metadata pynput `
    --distpath $distRoot `
    --workpath $workRoot `
    --specpath $specRoot `
    $sourceEntry
Assert-LastExitCode "PyInstaller bundle creation"

$appFolder = Join-Path $distRoot $appName
$appExe = Join-Path $appFolder "$appName.exe"
$bundleDashboard = Join-Path $appFolder "_internal\web\index.html"
foreach ($requiredOutput in @($appExe, $bundleDashboard)) {
    if (-not (Test-Path -LiteralPath $requiredOutput)) {
        throw "Required packaged file is missing: $requiredOutput"
    }
}

$pythonVersion = (& $buildPython --version).Trim()
Assert-LastExitCode "Packaged Python version lookup"
$pyInstallerVersion = (& $buildPython -m PyInstaller --version).Trim()
Assert-LastExitCode "PyInstaller version lookup"
$appSizeBytes = (Get-ChildItem -LiteralPath $appFolder -Recurse -File |
    Measure-Object -Property Length -Sum).Sum
$appHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $appExe).Hash
$buildInfoPath = Join-Path $appFolder "BUILD_INFO.txt"
$buildInfo = @(
    "Computer Warrior package build",
    "Version: $appVersion",
    "Mode: $modeName",
    "Source revision: $sourceRevision",
    "Built UTC: $((Get-Date).ToUniversalTime().ToString('o'))",
    "Python: $pythonVersion",
    "PyInstaller: $pyInstallerVersion",
    "Executable SHA-256: $appHash",
    "Bundle payload MiB before checksum manifest: $([math]::Round($appSizeBytes / 1MB, 1))"
)
[System.IO.File]::WriteAllLines(
    $buildInfoPath,
    [string[]]$buildInfo,
    (New-Object System.Text.UTF8Encoding($false))
)

$manifestPath = Join-Path $appFolder "SHA256SUMS.txt"
$manifestLines = Get-ChildItem -LiteralPath $appFolder -Recurse -File |
    Where-Object { $_.FullName -ne $manifestPath } |
    Sort-Object FullName |
    ForEach-Object {
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
        $relative = "./" + $_.FullName.Substring($appFolder.Length + 1).Replace("\", "/")
        "$hash  $relative"
    }
[System.IO.File]::WriteAllLines(
    $manifestPath,
    [string[]]$manifestLines,
    (New-Object System.Text.UTF8Encoding($false))
)

Write-Host ""
Write-Host "Package build complete."
Write-Host "Executable: $appExe"
Write-Host "Dashboard: $bundleDashboard"
Write-Host "Manifest: $manifestPath"
Write-Host "Build information: $buildInfoPath"
if (-not $Windowed) {
    Write-Host "Next: run this console build through the Windows QA steps before creating a -Windowed candidate."
}
