# Build "dist\Video Downloader Setup.exe" on Windows x64.
# Needs: uv (https://docs.astral.sh/uv/) and Inno Setup 6 (iscc on PATH or default install dir).
#
# Signing (optional). Without it Windows SmartScreen warns on first run.
#   WINDOWS_PFX_BASE64, WINDOWS_PFX_PASSWORD   an Authenticode code-signing certificate
$ErrorActionPreference = "Stop"
$Root = Resolve-Path "$PSScriptRoot\.."
Set-Location $Root

function Sign-File($path) {
  if (-not $env:WINDOWS_PFX_BASE64) { return }
  $pfx = Join-Path $env:RUNNER_TEMP "sign.pfx"
  [IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:WINDOWS_PFX_BASE64))
  $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" | Sort-Object FullName | Select-Object -Last 1
  & $signtool.FullName sign /f $pfx /p $env:WINDOWS_PFX_PASSWORD /fd sha256 /tr http://timestamp.digicert.com /td sha256 $path
  if ($LASTEXITCODE -ne 0) { throw "Signing failed: $path" }
  Remove-Item $pfx
}

uv sync --group build --frozen
uv run --frozen python packaging\fetch_bins.py
uv run --frozen pyinstaller --noconfirm --clean --workpath build\work --distpath build\dist packaging\ytd.spec
Sign-File "build\dist\Video Downloader\Video Downloader.exe"

$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
$version = (Select-String -Path ytd\__init__.py -Pattern '"(.+)"').Matches[0].Groups[1].Value
& $iscc "/DAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Sign-File "dist\Video Downloader Setup.exe"
Write-Host "Built dist\Video Downloader Setup.exe"
