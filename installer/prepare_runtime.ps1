# AI OFFICE - Paket ici Python calisma ortami hazirlayici
# Yonetici yetkisi GEREKTIRMEZ. Her sey bu klasorun icine kurulur (USB'de tasinabilir).
# Yarida kalirsa tekrar calistirin: tamamlanan adimlar atlanir.
param([string]$Root = (Split-Path -Parent $PSScriptRoot))

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$PyVer = "3.11.9"
$Runtime = Join-Path $Root "runtime"
$PyDir = Join-Path $Runtime "python"
$PyExe = Join-Path $PyDir "python.exe"
$Cache = Join-Path $Root "cache"
New-Item -ItemType Directory -Force -Path $Runtime, $Cache | Out-Null

function Get-File($Url, $Out) {
    if (Test-Path $Out) { return }
    Write-Host "  Indiriliyor: $Url"
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & curl.exe -L --fail --retry 3 -C - -o "$Out.part" $Url
        if ($LASTEXITCODE -ne 0) { throw "Indirme basarisiz: $Url" }
        Move-Item -Force "$Out.part" $Out
    } else {
        Invoke-WebRequest -Uri $Url -OutFile $Out -UseBasicParsing
    }
}

Write-Host "[1/3] Paket ici Python $PyVer (embeddable) hazirlaniyor..."
if (-not (Test-Path $PyExe)) {
    $zip = Join-Path $Cache "python-$PyVer-embed-amd64.zip"
    Get-File "https://www.python.org/ftp/python/$PyVer/python-$PyVer-embed-amd64.zip" $zip
    Expand-Archive -Force -Path $zip -DestinationPath $PyDir
    # site-packages ve 'import site' etkinlestir
    $pth = Get-ChildItem $PyDir -Filter "python*._pth" | Select-Object -First 1
    $lines = Get-Content $pth.FullName | ForEach-Object { if ($_ -match "^#\s*import site") { "import site" } else { $_ } }
    if (-not ($lines -contains "Lib\site-packages")) { $lines += "Lib\site-packages" }
    Set-Content -Path $pth.FullName -Value $lines -Encoding ASCII
} else { Write-Host "  Zaten hazir." }

Write-Host "[2/3] pip hazirlaniyor..."
& $PyExe -m pip --version 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    $gp = Join-Path $Cache "get-pip.py"
    Get-File "https://bootstrap.pypa.io/get-pip.py" $gp
    & $PyExe $gp --no-warn-script-location
    if ($LASTEXITCODE -ne 0) { throw "pip kurulamadi" }
} else { Write-Host "  Zaten hazir." }

Write-Host "[3/3] Python paketleri kuruluyor (FastAPI, python-docx, openpyxl, python-pptx, PyMuPDF...)"
& $PyExe -m pip install --no-warn-script-location --disable-pip-version-check -r (Join-Path $Root "backend\requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Paket kurulumu basarisiz. Internet baglantinizi kontrol edip tekrar deneyin." }
Write-Host "Python calisma ortami hazir: $PyExe"
