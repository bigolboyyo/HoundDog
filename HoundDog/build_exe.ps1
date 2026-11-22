$ErrorActionPreference = "Stop"
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

    Copy-Item -LiteralPath build/dist/HoundDog.exe -Destination HoundDog.exe -Force
    Write-Output "Built $PSScriptRoot\HoundDog.exe"
}
finally {
    Pop-Location
}
