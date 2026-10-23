# Video Downloader installer for Windows (64-bit). Developed by Garv.
#
#   irm https://raw.githubusercontent.com/Garvvaiahnav/yt-downloader/main/install.ps1 | iex
#
# Why this exists: an installer downloaded in a browser carries a "Mark of the
# Web", and SmartScreen then warns about an unknown publisher. A file saved by
# PowerShell has no such mark, so the installer runs without that warning.
# Installs for the current user, no admin needed. The app updates itself
# afterwards the same way.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # the progress bar makes Invoke-WebRequest very slow
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = "Garvvaiahnav/yt-downloader"
$Feed = "https://github.com/$Repo/releases/latest/download"

function Stop-Install($msg) { Write-Host "Install stopped: $msg" -ForegroundColor Red; throw $msg }

if (-not [Environment]::Is64BitOperatingSystem) { Stop-Install "Video Downloader needs 64-bit Windows." }

Write-Host "Looking up the latest version..." -ForegroundColor Cyan
try { $m = Invoke-RestMethod "$Feed/manifest.json" } catch { Stop-Install "could not reach GitHub." }
$a = $m.assets.'win32-x64'
if (-not $a.url.StartsWith("https://github.com/$Repo/releases/download/")) { Stop-Install "the release points somewhere unexpected." }

$file = Join-Path $env:TEMP "Video-Downloader-Setup.exe"
Write-Host "Downloading Video Downloader $($m.version)..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $a.url -OutFile $file -UseBasicParsing
if ((Get-FileHash $file -Algorithm SHA256).Hash.ToLower() -ne $a.sha256.ToLower()) {
  Remove-Item $file -Force
  Stop-Install "the download is corrupted (checksum mismatch). Run the command again."
}
Unblock-File $file

Write-Host "Installing..." -ForegroundColor Cyan
# /SILENT shows the install progress; the installer closes a running copy and reopens the app.
$installArgs = @("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS")
# Wait for the installer only. Start-Process -Wait would also wait for the app
# the installer opens at the end, and never return.
$p = Start-Process -FilePath $file -ArgumentList $installArgs -PassThru
$p.WaitForExit()
Remove-Item $file -Force -ErrorAction SilentlyContinue
if ($p.ExitCode -ne 0) { Stop-Install "the installer exited with code $($p.ExitCode)." }

Write-Host "Done. Video Downloader $($m.version) is installed." -ForegroundColor Green
