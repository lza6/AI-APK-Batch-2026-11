# Import the MSVC environment, then run blutter in-process.
# Needed because calling cmake from a plain PowerShell session cannot find kernel32.lib.
$vcvars = "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat"
if (-not (Test-Path $vcvars)) { throw "vcvars64.bat not found: $vcvars" }

$envLines = & cmd.exe /c "call `"$vcvars`" >nul 2>&1 && set"
foreach ($line in $envLines) {
    if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }
}

$env:HTTP_PROXY  = "http://127.0.0.1:10808"
$env:HTTPS_PROXY = "http://127.0.0.1:10808"
$blutter = "C:\Users\Administrator.DESKTOP-EGNE9ND\Desktop\逆向产物\_tools\blutter"
$env:PYTHONPATH = $blutter

Set-Location $blutter
& python.exe "$blutter\blutter.py" `
    "C:\Users\Administrator.DESKTOP-EGNE9ND\Desktop\逆向产物\Viddo-VideoShow\work\lib\arm64-v8a" `
    "C:\Users\Administrator.DESKTOP-EGNE9ND\Desktop\逆向产物\Viddo-VideoShow\work\blutter_out" `
    --rebuild *>&1 | Tee-Object -FilePath "$blutter\blutter_run2.log" | Select-Object -Last 25