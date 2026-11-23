$ErrorActionPreference = "Stop"
$releaseExecutable = Join-Path $PSScriptRoot "HoundDog.exe"
if (Get-Process -Name HoundDog -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $releaseExecutable }) {
    throw "Close the running HoundDog dashboard before replacing its executable."
}

Push-Location -LiteralPath $PSScriptRoot
try {
    $buildPython = ".\.venv-build\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $buildPython)) {
        python -m venv .venv-build
        if ($LASTEXITCODE -ne 0) { throw "Could not create the HoundDog build environment." }
    }
    & $buildPython -m pip --disable-pip-version-check install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "Could not install HoundDog's build dependencies." }

    New-Item -ItemType Directory -Path build -Force | Out-Null
    & $buildPython -m PyInstaller --noconfirm --onefile --name HoundDog `
        --specpath build --distpath build/dist --workpath build/work `
        --add-data "$PSScriptRoot/index.html:." --add-data "$PSScriptRoot/app.js:." `
        --add-data "$PSScriptRoot/styles.css:." `
        --add-data "$PSScriptRoot/pico-main/css/pico.min.css:pico-main/css" `
        --add-data "$PSScriptRoot/kongtext/kongtext.ttf:kongtext" `
        --add-data "$PSScriptRoot/kongtext/license.txt:kongtext" `
        --add-data "$PSScriptRoot/pico-main/LICENSE.md:pico-main" hounddog_app.py
    if ($LASTEXITCODE -ne 0) { throw "Could not build HoundDog.exe." }

    & $buildPython -m PyInstaller --noconfirm --onefile --windowed --name HoundDogScheduled `
        --specpath build --distpath build/dist --workpath build/work hounddog_scheduled.py
    if ($LASTEXITCODE -ne 0) { throw "Could not build HoundDogScheduled.exe." }

    Copy-Item -LiteralPath build/dist/HoundDogScheduled.exe -Destination HoundDogScheduled.exe -Force
    Copy-Item -LiteralPath build/dist/HoundDog.exe -Destination HoundDog.exe -Force
    Write-Output "Built HoundDog.exe and HoundDogScheduled.exe in $PSScriptRoot"

    & $buildPython scheduled_task.py --upgrade-windowless
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Could not upgrade the installed background task. Use Repair task in HoundDog Settings > Checking."
    }
}
finally {
    Pop-Location
}
