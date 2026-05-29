; Inno Setup script for the Windows installer. Built in CI:
;   ISCC.exe packaging\chess.iss   (after a onedir PyInstaller build into dist\ChessShootout)
; Per-user install (no admin), Start-menu shortcut, uninstaller; data lives in %APPDATA%.

[Setup]
AppName=Chess Shootout
AppVersion=1.0.0
AppPublisher=xiaomyung
DefaultDirName={localappdata}\Programs\ChessShootout
DefaultGroupName=Chess Shootout
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\out
OutputBaseFilename=ChessShootoutSetup
SetupIconFile=..\assets\icons\icon.ico
WizardStyle=modern
Compression=lzma2
SolidCompression=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "..\dist\ChessShootout\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Chess Shootout"; Filename: "{app}\ChessShootout.exe"
Name: "{autodesktop}\Chess Shootout"; Filename: "{app}\ChessShootout.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ChessShootout.exe"; Description: "Launch Chess Shootout"; Flags: nowait postinstall skipifsilent
