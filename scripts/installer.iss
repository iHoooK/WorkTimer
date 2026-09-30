#ifndef AppVersion
  #error Build using scripts/build.py to supply the product version and documents
#endif
#ifndef LicensePath
  #error Supply LicensePath and InfoPath using scripts/build.py
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
AppPublisher={#PublisherName}
AppPublisherURL={#PublisherURL}
AppSupportURL={#SupportURL}
AppComments=Локальный таймер: сценарии, Pomodoro, задачи, история и оверлеи OBS
VersionInfoVersion={#AppVersion}
VersionInfoDescription=WorkTimer — локальный таймер для работы и стримов
VersionInfoCopyright={#CopyrightNotice}
LicenseFile={#LicensePath}
InfoBeforeFile={#InfoPath}
MinVersion=10.0
DefaultDirName={commonpf64}\WorkTimer
UsePreviousAppDir=no
DefaultGroupName=WorkTimer
PrivilegesRequired=admin
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
Name: "{group}\Руководство WorkTimer"; Filename: "{app}\HELP.html"
Name: "{group}\Сайт автора"; Filename: "{#PublisherURL}"
Name: "{group}\Удалить WorkTimer"; Filename: "{uninstallexe}"
Name: "{autodesktop}\WorkTimer"; Filename: "{app}\WorkTimer.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\WorkTimer.exe"; Description: "Запустить WorkTimer"; Flags: nowait postinstall skipifsilent; Check: not IsWorkTimerUpdate
Filename: "{app}\WorkTimer.exe"; Parameters: "{code:UpdateArguments}"; Flags: nowait runasoriginaluser; Check: IsWorkTimerUpdate
; User history lives in LocalAppData\WorkTimer and is deliberately preserved by uninstall.

[Code]
var
  UpdateParentExited: Boolean;
  UpdateCompleted: Boolean;

function OpenProcess(Access: LongWord; Inherit: Boolean; ProcessId: LongWord): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function WaitForSingleObject(Handle: THandle; Milliseconds: LongWord): LongWord;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function CloseHandle(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';
function GetLastError: LongWord;
  external 'GetLastError@kernel32.dll stdcall';

function IsWorkTimerUpdate: Boolean;
begin
  Result := ExpandConstant('{param:WORKTIMERUPDATE|0}') = '1';
end;

function UpdateArguments(Param: String): String;
begin
  Result := '--port ' + IntToStr(StrToIntDef(ExpandConstant('{param:WORKTIMERPORT|8765}'), 8765)) +
    ' --data-dir ' + AddQuotes(ExpandConstant('{param:WORKTIMERDATA}'));
  if ExpandConstant('{param:WORKTIMERNOBROWSER|0}') = '1' then Result := Result + ' --no-browser';
  if ExpandConstant('{param:WORKTIMERNOTRAY|0}') = '1' then Result := Result + ' --no-tray';
  if ExpandConstant('{param:WORKTIMERNOHOTKEYS|0}') = '1' then Result := Result + ' --no-hotkeys';
end;

function InitializeSetup: Boolean;
var
  ParentHandle: THandle;
  ParentId: Integer;
  WaitResult: LongWord;
begin
  Result := True;
  if not IsWorkTimerUpdate then Exit;
  ParentId := StrToIntDef(ExpandConstant('{param:WORKTIMERPID|0}'), 0);
  if ParentId <= 0 then begin
    Result := False;
    Exit;
  end;
  if ExpandConstant('{param:WORKTIMERHANDOFF|0}') = '1' then begin
    if not SaveStringToFile(ExpandConstant('{src}\update-ready'), 'ready', False) then begin
      Result := False;
      Exit;
    end;
  end;
  ParentHandle := OpenProcess($00100000, False, ParentId);
  if ParentHandle = 0 then begin
    UpdateParentExited := GetLastError = 87;
    Result := UpdateParentExited;
    if not Result then
      MsgBox('Не удалось дождаться завершения WorkTimer. Закройте программу и запустите установщик вручную.', mbError, MB_OK);
    Exit;
  end;
  WaitResult := WaitForSingleObject(ParentHandle, 120000);
  CloseHandle(ParentHandle);
  UpdateParentExited := WaitResult = 0;
  Result := UpdateParentExited;
  if not Result then
    MsgBox('WorkTimer не завершился. Закройте программу и повторите обновление.', mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssDone then UpdateCompleted := True;
end;

procedure DeinitializeSetup;
var
  ResultCode: Integer;
  Target: String;
begin
  if IsWorkTimerUpdate and UpdateParentExited and not UpdateCompleted then begin
    Target := ExpandConstant('{param:DIR}') + '\WorkTimer.exe';
    if FileExists(Target) then
      ExecAsOriginalUser(Target, UpdateArguments(''), ExtractFileDir(Target), SW_SHOWNORMAL, ewNoWait, ResultCode);
  end;
end;
