#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\Build\Work Timer Portable"
#endif
#ifndef OutputDir
  #define OutputDir "..\Build"
#endif
[Setup]
AppId={{6EF693C7-8D5C-4B82-9E62-3512D8055A93}
AppName=WorkTimer
AppVersion={#AppVersion}
AppPublisher=WorkTimer
DefaultDirName={localappdata}\Programs\WorkTimer
DefaultGroupName=WorkTimer
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=WorkTimer-Setup-{#AppVersion}
SetupIconFile=..\web\assets\worktimer.ico
UninstallDisplayIcon={app}\WorkTimer.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=no
[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: unchecked
[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\WorkTimer"; Filename: "{app}\WorkTimer.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\WorkTimer"; Filename: "{app}\WorkTimer.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\WorkTimer.exe"; Description: "Запустить WorkTimer"; Flags: nowait postinstall skipifsilent
; User history lives in LocalAppData\WorkTimer and is deliberately preserved by uninstall.
