!include "MUI2.nsh"

Name "WindowsNote"
BrandingText "WindowsNote Installer"
OutFile "..\\release\\WindowsNote-Setup.exe"
InstallDir "$LOCALAPPDATA\\WindowsNote"
InstallDirRegKey HKCU "Software\\WindowsNote" "InstallDir"
RequestExecutionLevel user
Unicode True

!define MUI_ABORTWARNING

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Section "Install"
  SetOutPath "$INSTDIR"
  File "..\\dist\\WindowsNote.exe"
  File "..\\config.json"
  File "..\\README.md"

  WriteRegStr HKCU "Software\\WindowsNote" "InstallDir" "$INSTDIR"
  WriteUninstaller "$INSTDIR\\Uninstall.exe"

  CreateShortCut "$DESKTOP\\WindowsNote.lnk" "$INSTDIR\\WindowsNote.exe"
  CreateDirectory "$SMPROGRAMS\\WindowsNote"
  CreateShortCut "$SMPROGRAMS\\WindowsNote\\WindowsNote.lnk" "$INSTDIR\\WindowsNote.exe"
  CreateShortCut "$SMPROGRAMS\\WindowsNote\\Uninstall WindowsNote.lnk" "$INSTDIR\\Uninstall.exe"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\\WindowsNote.lnk"
  Delete "$SMPROGRAMS\\WindowsNote\\WindowsNote.lnk"
  Delete "$SMPROGRAMS\\WindowsNote\\Uninstall WindowsNote.lnk"
  RMDir "$SMPROGRAMS\\WindowsNote"

  Delete "$INSTDIR\\WindowsNote.exe"
  Delete "$INSTDIR\\config.json"
  Delete "$INSTDIR\\README.md"
  Delete "$INSTDIR\\Uninstall.exe"
  RMDir "$INSTDIR"

  DeleteRegKey HKCU "Software\\WindowsNote"
SectionEnd
