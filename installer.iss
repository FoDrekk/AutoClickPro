#define MyAppName "AutoClick Pro"
; Version comes from the built EXE, which takes it from autoclick_pro/__init__.py.
#define MyAppVersion GetStringFileInfo(AddBackslash(SourcePath) + "dist\AutoClickPro\AutoClickPro.exe", "ProductVersion")
#if MyAppVersion == ""
  #error Build the EXE first: pyinstaller --noconfirm --clean AutoClickPro.spec
#endif
#define MyAppPublisher "AutoClick Pro"
#define MyAppExeName "AutoClickPro.exe"

[Setup]
AppId={{7C4E9A1B-3F2D-4E6A-8C1D-5B0A9F2E4D6C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=AutoClickPro-Setup-{#MyAppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; The PyInstaller build is 64-bit only (needs Inno Setup 6.3 or newer).
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\AutoClickPro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
