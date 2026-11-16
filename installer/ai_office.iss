; AI OFFICE - Windows kurulum paketi (Inno Setup 6)
; Yonetici yetkisi GEREKTIRMEZ: kullanici klasorune (%LOCALAPPDATA%\AI_OFFICE\app) kurulur.
#define AppVer "1.1.0"

[Setup]
AppId={{6C1F3A52-7E1B-4C0B-9A2E-AI0FF1CE0001}
AppName=AI OFFICE
AppVersion={#AppVer}
AppPublisher=AI OFFICE
DefaultDirName={localappdata}\AI_OFFICE\app
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=AI_OFFICE_Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=AI OFFICE
DiskSpanning=no

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Files]
Source: "..\stage\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userdesktop}\AI OFFICE"; Filename: "{app}\AI_OFFICE.exe"; WorkingDir: "{app}"
Name: "{userprograms}\AI OFFICE\AI OFFICE"; Filename: "{app}\AI_OFFICE.exe"; WorkingDir: "{app}"
Name: "{userprograms}\AI OFFICE\Model ve motoru hazirla"; Filename: "{app}\INSTALL_AI_OFFICE.bat"; WorkingDir: "{app}"
Name: "{userprograms}\AI OFFICE\Yedekle"; Filename: "{app}\BACKUP_AI_OFFICE.bat"; WorkingDir: "{app}"
Name: "{userprograms}\AI OFFICE\AI OFFICE'i kaldir"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\INSTALL_AI_OFFICE.bat"; Description: "Model ve AI motorunu simdi hazirla (internet gerekir)"; Flags: postinstall shellexec skipifsilent unchecked; Check: NeedsPrepare
Filename: "{app}\AI_OFFICE.exe"; Description: "AI OFFICE'i baslat"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\cache"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\engines"
Type: filesandordirs; Name: "{app}\backend"
Type: filesandordirs; Name: "{app}\frontend"

[Code]
function NeedsPrepare: Boolean;
var FindRec: TFindRec;
begin
  Result := not FindFirst(ExpandConstant('{app}\models\*.gguf'), FindRec);
  if not Result then FindClose(FindRec);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if MsgBox('Ajanlariniz, hafizaniz, projeleriniz, yedekleriniz ve model dosyalari da silinsin mi?' + #13#10 +
              '(Hayir derseniz bu veriler ' + ExpandConstant('{app}') + ' klasorunde kalir.)',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{app}'), True, True, True);
end;
