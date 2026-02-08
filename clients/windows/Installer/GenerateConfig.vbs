Option Explicit

' Get CustomActionData (format: "INSTALLFOLDER|API_URL|ALLOWED_PATHS|UI_LANGUAGE|CREDENTIAL_PREFIX")
Dim customData, dataParts, installFolder, apiUrl, allowedPaths, language, credPrefix

customData = Session.Property("CustomActionData")
dataParts = Split(customData, "|")

If UBound(dataParts) < 4 Then
    ' Fallback to defaults if data is missing
    installFolder = "C:\Program Files\RFM"
    apiUrl = "https://rfm.company.com"
    allowedPaths = "C:\"
    language = "en-US"
    credPrefix = "RFM_ContextMenu"
Else
    installFolder = dataParts(0)
    apiUrl = dataParts(1)
    allowedPaths = dataParts(2)
    language = dataParts(3)
    credPrefix = dataParts(4)
End If

' Parse allowed paths (split by newline or semicolon)
Dim pathArray, paths, i
pathArray = Split(Replace(allowedPaths, vbCrLf, ";"), ";")

' Build JSON
Dim fso, configFile, json
Set fso = CreateObject("Scripting.FileSystemObject")

json = "{" & vbCrLf
json = json & "  ""api_base_url"": """ & EscapeJson(apiUrl) & """," & vbCrLf
json = json & "  ""allowed_paths"": [" & vbCrLf

For i = 0 To UBound(pathArray)
    If Trim(pathArray(i)) <> "" Then
        json = json & "    """ & EscapeJson(Trim(pathArray(i))) & """"
        If i < UBound(pathArray) And Trim(pathArray(i+1)) <> "" Then
            json = json & ","
        End If
        json = json & vbCrLf
    End If
Next

json = json & "  ]," & vbCrLf
json = json & "  ""language"": """ & EscapeJson(language) & """," & vbCrLf
json = json & "  ""credential_target_prefix"": """ & EscapeJson(credPrefix) & """" & vbCrLf
json = json & "}" & vbCrLf

' Write config.json
Set configFile = fso.CreateTextFile(installFolder & "\config.json", True)
configFile.Write json
configFile.Close

' Function to escape JSON strings
Function EscapeJson(str)
    EscapeJson = Replace(Replace(Replace(str, "\", "\\"), """", "\"""), vbCrLf, "\n")
End Function
