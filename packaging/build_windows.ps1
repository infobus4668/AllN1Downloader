$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

$Python = if ($env:PYTHON) { $env:PYTHON } else { (Get-Command python -ErrorAction Stop).Source }
& $Python -m pip install -r requirements.txt -r packaging/requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Could not install packaging dependencies.' }

$AppName = 'AllN1Downloader'
$ConsoleFlag = '--noconsole'
if ($env:ALLINONE_CONSOLE -eq '1') {
  $AppName = 'AllN1DownloaderConsole'
  $ConsoleFlag = '--console'
}
$Arguments = @(
  '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', $ConsoleFlag,
  '--name', $AppName, '--collect-all', 'yt_dlp', '--collect-all', 'fastapi',
  '--collect-all', 'uvicorn', '--collect-all', 'starlette', '--add-data', 'static;static'
)

if ($env:FFMPEG_DIR) {
  foreach ($Name in @('ffmpeg.exe', 'ffprobe.exe')) {
    $Binary = Join-Path $env:FFMPEG_DIR $Name
    if (-not (Test-Path -LiteralPath $Binary)) { throw "Missing bundled media tool: $Binary" }
    $Arguments += @('--add-binary', "$Binary;.")
  }
  foreach ($Library in Get-ChildItem -LiteralPath $env:FFMPEG_DIR -Filter '*.dll' -File) {
    $Arguments += @('--add-binary', "$($Library.FullName);.")
  }
} else {
  Write-Output 'FFmpeg/ffprobe will not be bundled. Set FFMPEG_DIR to include them.'
}

$Node = if ($env:NODE_EXE) { $env:NODE_EXE } else {
  $NodeCommand = Get-Command node -ErrorAction SilentlyContinue
  if ($NodeCommand) { $NodeCommand.Source } else { $null }
}
if ($Node) {
  if (-not (Test-Path -LiteralPath $Node)) { throw "Node executable not found: $Node" }
  $Arguments += @('--add-binary', "$Node;.")
}

& $Python @Arguments app.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

$SigningPfx = $env:WINDOWS_SIGN_PFX
$TemporaryPfx = $null
if ($env:WINDOWS_SIGN_PFX_BASE64) {
  $TemporaryPfx = Join-Path $env:TEMP "alln1downloader-signing-$PID.pfx"
  [System.IO.File]::WriteAllBytes($TemporaryPfx, [Convert]::FromBase64String($env:WINDOWS_SIGN_PFX_BASE64))
  $SigningPfx = $TemporaryPfx
}
try {
  if ($SigningPfx) {
    if (-not $env:WINDOWS_SIGN_PASSWORD) { throw 'WINDOWS_SIGN_PASSWORD is required when signing the Windows executable.' }
    if (-not (Test-Path -LiteralPath $SigningPfx)) { throw "Signing PFX not found: $SigningPfx" }
    $SignTool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
    if (-not $SignTool) {
      $KitRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
      $SignTool = Get-ChildItem -Path $KitRoot -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
        Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $SignTool) { throw 'Windows SDK signtool.exe is required to Authenticode-sign the executable.' }
    $Executable = Join-Path $ProjectRoot "dist\$AppName.exe"
    & $SignTool sign /fd SHA256 /tr 'http://timestamp.digicert.com' /td SHA256 /f $SigningPfx /p $env:WINDOWS_SIGN_PASSWORD /d 'AllN1Downloader (Self-Signed)' $Executable
    if ($LASTEXITCODE -ne 0) { throw 'Authenticode signing failed.' }
    if ($env:WINDOWS_SIGN_ALLOW_SELF_SIGNED -eq '1') {
      if (-not $env:WINDOWS_SIGN_CERT_THUMBPRINT) { throw 'WINDOWS_SIGN_CERT_THUMBPRINT is required for pinned self-signed signing.' }
      $Signature = Get-AuthenticodeSignature -FilePath $Executable
      if (-not $Signature.SignerCertificate -or $Signature.SignerCertificate.Thumbprint -ne $env:WINDOWS_SIGN_CERT_THUMBPRINT) {
        throw 'The signed executable does not match the configured update signer thumbprint.'
      }
      if ($Signature.Status -in @('NotSigned', 'HashMismatch') -or -not $Signature.TimeStamperCertificate) {
        throw "Self-signed Authenticode integrity/timestamp verification failed: $($Signature.Status)"
      }
      if ($Signature.Status -notin @('Valid', 'UnknownError')) {
        throw "Unexpected self-signed Authenticode status: $($Signature.StatusMessage)"
      }
      Write-Output "Built and timestamped $Executable with the pinned self-signed updater identity (not publicly trusted)."
    } else {
      & $SignTool verify /pa $Executable
      if ($LASTEXITCODE -ne 0) { throw 'Authenticode verification failed.' }
      Write-Output "Built and Authenticode-signed $Executable"
    }
  } elseif ($env:REQUIRE_WINDOWS_SIGNING -eq '1') {
    throw 'Windows signing was required but WINDOWS_SIGN_PFX or WINDOWS_SIGN_PFX_BASE64 was not supplied.'
  } else {
    Write-Output "Built unsigned $ProjectRoot\dist\$AppName.exe (supply a code-signing certificate to sign it)."
  }
} finally {
  if ($TemporaryPfx -and (Test-Path -LiteralPath $TemporaryPfx)) { Remove-Item -LiteralPath $TemporaryPfx -Force }
}
if (-not $Node) { Write-Output 'Node.js is not bundled; install Node.js 20+ for YouTube JS solving.' }
