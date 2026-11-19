' Den Assistenten starten und das Fenster aufmachen. Doppelklick genuegt; eine Verknuepfung auf den
' Desktop oder in den Autostart (Win+R, shell:startup) geht genauso.
'
' Gestartet wird immer. Laeuft er schon, beendet sich die neue Instanz nach einer Sekunde
' von selbst, weil sie an die Sperre in data\lumen.lock nicht herankommt.
'
' python.exe mit verstecktem Fenster (0), nicht pythonw.exe: pythonw hat gar keine Konsole,
' und dann macht Windows dem Claude-Prozess, den er startet, eine eigene sichtbare auf.

Option Explicit
Dim shell, fso, ordner, adresse

adresse = "http://127.0.0.1:8770"
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
ordner = fso.GetParentFolderName(WScript.ScriptFullName)

shell.CurrentDirectory = ordner
shell.Run "python -m lumen", 0, False
WScript.Sleep 4000   ' Boot plus Selbsttests, bis der Port aufgeht

' Als eigenes Fenster ohne Adressleiste, damit es sich wie ein Programm anfuehlt. Ohne
' Chrome tut es Edge, und ohne beide der Standardbrowser.
On Error Resume Next
shell.Run "chrome.exe --app=" & adresse, 1, False
If Err.Number <> 0 Then
  Err.Clear
  shell.Run "msedge.exe --app=" & adresse, 1, False
  If Err.Number <> 0 Then
    Err.Clear
    shell.Run adresse, 1, False
  End If
End If
