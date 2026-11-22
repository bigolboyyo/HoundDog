$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$frontend = Join-Path $projectRoot "frontend"
$releaseParent = Join-Path $projectRoot "dist"
$release = Join-Path $releaseParent "ThetaDesk"
$releaseExecutable = Join-Path $release "ThetaDesk.exe"
$stagingParent = Join-Path $projectRoot "build\release"
$staged = Join-Path $stagingParent "ThetaDesk"
$backup = Join-Path $releaseParent ("ThetaDesk-previous-" + [Guid]::NewGuid().ToString("N"))
$configFiles = @(".env", "creds.txt")

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project environment not found. Run python start_project.py first."
}
if (Get-Process -Name ThetaDesk -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $releaseExecutable }) {
    throw "Close the running ThetaDesk app before replacing its executable."
}

Push-Location -LiteralPath $projectRoot
try {
    & $python -m pip --disable-pip-version-check install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "Could not install executable build dependencies." }

    $buildOptions = @(
        "--noconfirm", "--onedir", "--name", "ThetaDesk",
        "--specpath", "build", "--workpath", "build\pyinstaller",
        "--distpath", $stagingParent, "--add-data", "$frontend;frontend",
        "--collect-all", "thetadata", "--collect-all", "tzdata", "start_project.py"
    )
    & $python -m PyInstaller @buildOptions
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $staged "ThetaDesk.exe"))) {
        throw "Could not build ThetaDesk.exe."
    }
    Copy-Item -LiteralPath (Join-Path $projectRoot "ThetaTerminal.jar") -Destination $staged

    New-Item -ItemType Directory -Path $releaseParent -Force | Out-Null
    $hasPrevious = Test-Path -LiteralPath $release -PathType Container
    if ($hasPrevious) {
        [System.IO.Directory]::Move($release, $backup)
    }
    try {
        if ($hasPrevious) {
            foreach ($name in $configFiles) {
                $file = Join-Path $backup $name
                if (Test-Path -LiteralPath $file -PathType Leaf) {
                    Copy-Item -LiteralPath $file -Destination $staged
                }
            }
        }
        [System.IO.Directory]::Move($staged, $release)
    }
    catch {
        if ($hasPrevious) {
            [System.IO.Directory]::Move($backup, $release)
            foreach ($name in $configFiles) {
                Remove-Item -LiteralPath (Join-Path $staged $name) -Force -ErrorAction SilentlyContinue
            }
        }
        throw
    }
    if ($hasPrevious) {
        $resolvedBackup = (Resolve-Path -LiteralPath $backup).ProviderPath
        $resolvedParent = (Resolve-Path -LiteralPath $releaseParent).ProviderPath
        if ((Split-Path -Parent $resolvedBackup) -ne $resolvedParent) {
            throw "Unexpected path for the previous release: $resolvedBackup"
        }
        Remove-Item -LiteralPath $resolvedBackup -Recurse -Force
    }
    Write-Output "Executable created: $releaseExecutable"
}
finally {
    Pop-Location
}
