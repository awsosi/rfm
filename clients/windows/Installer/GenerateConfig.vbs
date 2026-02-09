On Error Resume Next

' Get CustomActionData (format: "INSTALLFOLDER|API_URL|FRONTEND_URL|ALLOWED_PATHS|UI_LANGUAGE|CREDENTIAL_PREFIX")
Dim customData, dataParts, installFolder, apiUrl, frontendUrl, allowedPaths, language, credPrefix
Dim fso, configFile, json, pathArray, i, pathCount, currentPath

customData = Session.Property("CustomActionData")

' Split the custom data
dataParts = Split(customData, "|")

' Extract values with defaults
If UBound(dataParts) >= 5 Then
    installFolder = dataParts(0)
    apiUrl = dataParts(1)
    frontendUrl = dataParts(2)
    allowedPaths = dataParts(3)
    language = dataParts(4)
    credPrefix = dataParts(5)
Else
    installFolder = "C:\Program Files\RFM"
    apiUrl = "https://rfm.company.com"
    frontendUrl = ""
    allowedPaths = "C:\"
    language = "en-US"
    credPrefix = "RFM_ContextMenu"
End If

' Parse allowed paths (split by semicolon)
allowedPaths = Replace(allowedPaths, vbCrLf, ";")
allowedPaths = Replace(allowedPaths, vbCr, ";")
allowedPaths = Replace(allowedPaths, vbLf, ";")
pathArray = Split(allowedPaths, ";")

' Build JSON
json = "{" & vbCrLf
json = json & "  ""api_base_url"": """ & EscapeJson(apiUrl) & """," & vbCrLf

' Add frontend_base_url if provided
If frontendUrl <> "" Then
    json = json & "  ""frontend_base_url"": """ & EscapeJson(frontendUrl) & """," & vbCrLf
End If

json = json & "  ""allowed_paths"": [" & vbCrLf

' Add paths to JSON array
pathCount = 0
For i = 0 To UBound(pathArray)
    currentPath = Trim(pathArray(i))
    If currentPath <> "" Then
        If pathCount > 0 Then
            json = json & "," & vbCrLf
        End If
        json = json & "    """ & EscapeJson(currentPath) & """"
        pathCount = pathCount + 1
    End If
Next

json = json & vbCrLf & "  ]," & vbCrLf
json = json & "  ""language"": """ & EscapeJson(language) & """," & vbCrLf
json = json & "  ""credential_target_prefix"": """ & EscapeJson(credPrefix) & """" & vbCrLf
json = json & "}"

' Write config.json
Set fso = CreateObject("Scripting.FileSystemObject")
Set configFile = fso.CreateTextFile(installFolder & "\config.json", True)
configFile.Write json
configFile.Close

If Err.Number <> 0 Then
    Session.Property("CA_ERROR") = "VBScript Error: " & Err.Description
End If

' Function to escape JSON strings
Function EscapeJson(str)
    Dim result
    result = str
    result = Replace(result, "\", "\\")
    result = Replace(result, """", "\""")
    result = Replace(result, vbCrLf, "\n")
    result = Replace(result, vbCr, "\n")
    result = Replace(result, vbLf, "\n")
    result = Replace(result, vbTab, "\t")
    EscapeJson = result
End Function
