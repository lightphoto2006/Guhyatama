' dbcomposer.vbs — запуск окна dbcomposer двойным кликом.
' Без консоли: работает через pythonw. Положи рядом с проектом, пути ищет сама.
Option Explicit

Dim fso, sh, root, toolsDir, pyw, py
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
toolsDir = fso.BuildPath(root, "tools\dbcomposer")

pyw = "F:\AI\portable-files\python\pythonw.exe"
py = "F:\AI\portable-files\python\python.exe"
If Not fso.FileExists(pyw) Then pyw = py

If Not fso.FileExists(fso.BuildPath(toolsDir, "gui.py")) Then
    MsgBox "Не найдено: " & fso.BuildPath(toolsDir, "gui.py"), 16, "dbcomposer"
    WScript.Quit 1
End If

sh.CurrentDirectory = toolsDir
sh.Run """" & pyw & """ """ & fso.BuildPath(toolsDir, "gui.py") & """", 1, False
