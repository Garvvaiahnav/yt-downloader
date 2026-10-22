; Inno Setup script for the Windows installer. Built by build_windows.ps1.
; Per-user install: no admin prompt, no UAC.

#define AppName "Video Downloader"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F1C2B7A-4E2D-4C8B-9F3A-7D5E1A2B3C4D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Garv
AppPublisherURL=https://github.com/Garvvaiahnav/yt-downloader
AppCopyright=Developed by Garv
VersionInfoVersion={#AppVersion}
VersionInfoCompany=Garv
VersionInfoDescription={#AppName} Setup
VersionInfoProductName={#AppName}
VersionInfoCopyright=Developed by Garv
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Video Downloader Setup
SetupIconFile=icon.ico
WizardImageFile=wizard.bmp,wizard@2x.bmp
WizardSmallImageFile=wizard-small.bmp,wizard-small@2x.bmp
UninstallDisplayIcon={app}\{#AppName}.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[InstallDelete]
; The app was called "YT Downloader" up to 1.3; clear its exe and shortcuts.
Type: files; Name: "{app}\YT Downloader.exe"
Type: files; Name: "{autoprograms}\YT Downloader.lnk"
Type: files; Name: "{autodesktop}\YT Downloader.lnk"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\build\dist\{#AppName}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "Open {#AppName}"; Flags: nowait postinstall skipifsilent
; In-app updates install silently; reopen the app afterwards.
Filename: "{app}\{#AppName}.exe"; Flags: nowait; Check: WizardSilent and ShouldRelaunch

[Messages]
WelcomeLabel1=Video Downloader
WelcomeLabel2=Developed by Garv.%n%nDownloads videos from YouTube, Instagram, Facebook, X, Threads and TikTok, and converts them so Premiere Pro and After Effects actually open them.%n%nIt downloads videos; it doesn't judge your watch history.
FinishedHeadingLabel=Done. Go make something good.
FinishedLabel=Video Downloader is installed. Developed by Garv; the mascot did the heavy lifting.

[Code]
// The app passes /relaunch=0 when it applies an update on quit.
function ShouldRelaunch(): Boolean;
begin
  Result := ExpandConstant('{param:relaunch|1}') <> '0';
end;
