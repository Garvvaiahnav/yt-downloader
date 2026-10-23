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
$ProgressPreference = "SilentlyContinue"   # PowerShell's own bar makes Invoke-RestMethod slow; we draw ours
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = "Garvvaiahnav/yt-downloader"
$Feed = "https://github.com/$Repo/releases/latest/download"

function Stop-Install($msg) { Write-Host "Install stopped: $msg" -ForegroundColor Red; throw $msg }

# One line, redrawn in place: [#########---------]  45%   52 / 113 MB   8.4 MB/s
function Show-Progress([long]$done, [long]$total, [double]$seconds) {
  $pct = if ($total -gt 0) { [math]::Min(100, [math]::Floor($done * 100 / $total)) } else { 0 }
  $bar = ("#" * [math]::Floor($pct / 4)).PadRight(25, "-")
  $mbps = if ($seconds -gt 0) { $done / 1MB / $seconds } else { 0 }
  # Built first: inside a method call's parentheses the commas would split the -f list into arguments.
  $line = "`r  [{0}] {1,3}%  {2,4:N0} / {3:N0} MB  {4,5:N1} MB/s " -f @($bar, $pct, ($done / 1MB), ($total / 1MB), $mbps)
  [Console]::Write($line)
}

# Streams the file to disk and shows progress (Invoke-WebRequest would either
# show nothing or crawl with its own progress bar on Windows PowerShell 5.1).
function Get-WithProgress($url, $path, [long]$size) {
  Add-Type -AssemblyName System.Net.Http
  $client = New-Object System.Net.Http.HttpClient
  $client.Timeout = [TimeSpan]::FromMinutes(30)
  $in = $null; $out = $null
  try {
    $resp = $client.GetAsync($url, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
    [void]$resp.EnsureSuccessStatusCode()
    $total = $resp.Content.Headers.ContentLength
    if (-not $total) { $total = $size }
    $in = $resp.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
    $out = [IO.File]::Create($path)
    $buf = New-Object byte[] (1MB)
    $done = 0L; $shown = -1L
    $clock = [Diagnostics.Stopwatch]::StartNew()
    while (($n = $in.Read($buf, 0, $buf.Length)) -gt 0) {
      $out.Write($buf, 0, $n)
      $done += $n
      if ($clock.ElapsedMilliseconds - $shown -ge 250) {
        $shown = $clock.ElapsedMilliseconds
        Show-Progress $done $total $clock.Elapsed.TotalSeconds
      }
    }
    Show-Progress $done $total $clock.Elapsed.TotalSeconds
    Write-Host ""
  } finally {
    if ($out) { $out.Dispose() }
    if ($in) { $in.Dispose() }
    $client.Dispose()
  }
}

if (-not [Environment]::Is64BitOperatingSystem) { Stop-Install "Video Downloader needs 64-bit Windows." }

Write-Host "Looking up the latest version..." -ForegroundColor Cyan
try { $m = Invoke-RestMethod "$Feed/manifest.json" } catch { Stop-Install "could not reach GitHub." }
$a = $m.assets.'win32-x64'
if (-not $a.url.StartsWith("https://github.com/$Repo/releases/download/")) { Stop-Install "the release points somewhere unexpected." }

$file = Join-Path $env:TEMP "Video-Downloader-Setup.exe"
Write-Host "Downloading Video Downloader $($m.version)..." -ForegroundColor Cyan
try { Get-WithProgress $a.url $file ([long]$a.size) } catch { Write-Host ""; Stop-Install "the download failed ($($_.Exception.Message)). Run the command again." }
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
