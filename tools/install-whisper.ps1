# Laedt whisper.cpp (CPU-Build) und ein Sprachmodell nach tools\whisper.
# Einmal ausfuehren: Rechtsklick -> "Mit PowerShell ausfuehren", oder in PowerShell:
#   powershell -ExecutionPolicy Bypass -File tools\install-whisper.ps1
# Ein weiteres Modell, das dann in den Einstellungen zur Wahl steht:
#   ... -File tools\install-whisper.ps1 -Model large-v3-turbo-q5_0   (genauer, auf der CPU langsam)
#   ... -File tools\install-whisper.ps1 -Model base-q5_1             (schneller, ungenauer)

param([string]$Model = "small-q5_1")
# Danach Lumen neu starten und in den Einstellungen ein Mikrofon waehlen.

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # sonst bremst die Fortschrittsanzeige den Download

# Ein fester Build, kein "latest": was hier steht, ist getestet.
$build = "b5454"
$zip = "https://github.com/ggml-org/whisper.cpp/releases/download/$build/whisper-bin-x64.zip"
if ($Model -notmatch '^[a-z0-9.-]+$') { throw "Modellname: nur Buchstaben, Ziffern, Punkt, Bindestrich" }
$url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$Model.bin"

$ziel = Join-Path $PSScriptRoot "whisper"
$tmp = Join-Path $env:TEMP "lumen-whisper-$build"
New-Item -ItemType Directory -Force $ziel | Out-Null
New-Item -ItemType Directory -Force $tmp | Out-Null

if (-not (Test-Path (Join-Path $ziel "whisper-cli.exe"))) {
    Write-Host "Lade whisper.cpp ($build) ..."
    Invoke-WebRequest $zip -OutFile (Join-Path $tmp "whisper.zip")
    Expand-Archive (Join-Path $tmp "whisper.zip") -DestinationPath $tmp -Force
    $cli = Get-ChildItem $tmp -Recurse -Filter "whisper-cli.exe" | Select-Object -First 1
    if (-not $cli) { throw "whisper-cli.exe nicht im Archiv gefunden" }
    # Nur whisper-cli und die DLLs daneben -- das Archiv bringt zwanzig weitere Programme mit.
    Copy-Item $cli.FullName $ziel -Force
    Copy-Item (Join-Path $cli.DirectoryName "*.dll") $ziel -Force
}

$bin = Join-Path $ziel "ggml-$Model.bin"
if (-not (Test-Path $bin)) {
    Write-Host "Lade das Sprachmodell $Model ..."
    Invoke-WebRequest $url -OutFile "$bin.part"
    Move-Item "$bin.part" $bin -Force
}

Write-Host "Fertig: $ziel"
