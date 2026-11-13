[Setup]
AppId={{38F27F47-D6F6-4B2A-BFD4-2C562C513283}
AppName=Shadow AFK
AppVersion=0.1.1
DefaultDirName={localappdata}\Programs\Shadow AFK
DefaultGroupName=Shadow AFK
DisableDirPage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=release
OutputBaseFilename=ShadowAFK_Setup
SetupIconFile=shadowafk\ui\shadow.ico
UninstallDisplayIcon={app}\ShadowAFK.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "dist\ShadowAFK\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Shadow AFK"; Filename: "{app}\ShadowAFK.exe"
Name: "{autodesktop}\Shadow AFK"; Filename: "{app}\ShadowAFK.exe"
