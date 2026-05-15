Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

scriptDirectory = fileSystem.GetParentFolderName(WScript.ScriptFullName)
batchPath = fileSystem.BuildPath(scriptDirectory, "Start_Market_Pulse.bat")

shell.Run "cmd /c """ & batchPath & """", 0, False
