; Установщик GMAGC для Windows (Inno Setup). Ставит в папку пользователя (без прав администратора),
; чтобы не мешать автообновлению приложения — оно подменяет файлы в той же папке, где программа лежит,
; и права администратора ему взять неоткуда.
;
; Версия и папка со собранным приложением передаются при сборке:
;   ISCC.exe /DAppVersion=0.6.3 /DSourceDir=C:\path\to\apps\desktop\build\windows gmagc.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\apps\desktop\build\windows"
#endif

#define AppName "GMAGC"
#define AppPublisher "@ANDY_BUM"
#define AppExeName "gmagc-desktop.exe"
#define AppURL "https://github.com/spacesarmat/GMAGC"

[Setup]
; Постоянный идентификатор приложения: не менять между версиями, иначе установщик перестанет видеть
; прежнюю установку и обновление через установщик (не автообновление — оно работает независимо) сломается.
AppId={{6E7B7B7A-2C1A-4C5A-9E0A-9F6E6C8B0A1E}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={localappdata}\Programs\GMAGC
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
; Без прав администратора: устанавливаем только для текущего пользователя, как VS Code.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=GMAGC-Setup-{#AppVersion}
SetupIconFile=gmagc.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Сборка без подписи кода: пока нет сертификата, SmartScreen может один раз спросить подтверждение.

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
