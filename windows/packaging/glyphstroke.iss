; Установщик Glyphstroke для Windows — Inno Setup 6.
;
; Собирается вместе с программой скриптом packaging\build.ps1; отдельно
; запускать не нужно. Установщик один файл: поставил, ярлык, автозапуск,
; значок в области уведомлений. Ни командной строки, ни лишних вопросов.

#define AppName "Glyphstroke"
#define AppPublisher "runetrace"
#define AppExe "Glyphstroke.exe"

; Версия берётся из собранной программы, чтобы не разъезжаться с ней.
#define AppVersion GetVersionNumbersString(SourcePath + "\..\dist\app\" + AppExe)

[Setup]
AppId={{B7C5F7E2-6C21-4C4E-9C0A-6E7E5C3B1A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Ставим для одного пользователя: прав администратора не потребуется, а
; перехват мыши их и не требует — программа работает в своём сеансе.
PrivilegesRequired=lowest
OutputDir={#SourcePath}\..\dist
OutputBaseFilename=Glyphstroke-{#AppVersion}-setup
SetupIconFile={#SourcePath}\..\src\Glyphstroke.App\glyphstroke.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "autostart"; Description: "Запускать при входе в систему"; GroupDescription: "Дополнительно:"
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
Source: "{#SourcePath}\..\dist\app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Автозапуск той же записью, что правит сама программа в настройках, — иначе
; получилось бы два источника правды и переключатель врал бы.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "Glyphstroke"; ValueData: """{app}\{#AppExe}"""; \
    Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "Запустить Glyphstroke"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Настройки и жесты остаются: человек мог ставить их часами, и удалять их
; вместе с программой было бы бесцеремонно.
Type: files; Name: "{app}\*.log"
