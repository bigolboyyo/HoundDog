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

# Moves a folder, retrying for up to 30 seconds. Right after a build, antivirus
# or the search indexer often holds new files open briefly, and Windows refuses
# to move a folder while any file in it is open.
function Move-DirectoryWithRetry([string]$source, [string]$destination) {
    for ($attempt = 1; ; $attempt++) {
        try {
            [System.IO.Directory]::Move($source, $destination)
            return
        }
        catch {
            # Only access denied (how Windows reports a folder holding an open
            # file) or a sharing or lock violation is worth waiting for; a
            # missing folder or an existing target is not.
            $cause = $_.Exception.GetBaseException()
            $code = $cause.HResult -band 0xFFFF
            $locked = $cause -is [System.UnauthorizedAccessException] -or
                ($cause -is [System.IO.IOException] -and $code -in 5, 32, 33)
            if (-not $locked -or $attempt -ge 15) { throw }
            Write-Host "Waiting for files in $source to be released (attempt $attempt of 15)..."
            Start-Sleep -Seconds 2
        }
    }
}

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
        Move-DirectoryWithRetry $release $backup
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
        Move-DirectoryWithRetry $staged $release
    }
    catch {
        if ($hasPrevious) {
            Move-DirectoryWithRetry $backup $release
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
