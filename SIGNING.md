# Release signing and credentials

This document records the signing keys retained for AllN1Downloader, how to use them,
and the trust limits of the current Windows signature. It contains public
fingerprints and paths only—never passwords or private key material.

## Credential handling

Generated private files are kept outside the project in
`%USERPROFILE%\Documents\AllInOneSigning`. The directory ACL is limited to
the current Windows account and SYSTEM. Credential XML files contain
DPAPI-encrypted `SecureString` values and require this Windows user profile to
decrypt; do not assume they are portable. Back up signing keys and passwords
securely before changing or losing this profile; use a password manager for
portable recovery.

Do not commit PFX/P12/JKS files, private GPG exports, or passwords. The project
ignores common signing-key file extensions, and the actual credential files are
outside the repository.

## Generated key inventory

| Platform | Local files | Identity and verification | Current status |
|---|---|---|---|
| Android | `android-release.p12`; `android-release-credentials.xml` | Alias `allinone-release`; RSA 4096; certificate SHA-256 `04443938D6DD999B672D3EFE481D8091AF3D91D5396CACF9988D005BCAE4F279`; valid through 2054-04-11. | AllN1Downloader 1.0.1 signed APK/AAB use `versionCode` 4 and preserve the previous application ID/signing identity for upgrades. |
| Debian | `debian-signing-private.asc`; `debian-signing-public.asc`; `debian-release-credentials.xml`; `gnupg/` | Legacy user ID `AllInOne Debian Release Signing`; fingerprint `B35D6EB69B04DC9B521186AC2C0170ED38933245`; five-year expiration. | Private export was imported into a clean GPG home and test-signature verified. |
| Windows | `windows-alln1-selfsigned.pfx`; `windows-alln1-credentials.xml` | Subject `CN=AllN1Downloader Self-Signed Code Signing`; thumbprint `9F1BFF66846716DC3E579D9F61E7A412D36E6336`; expires 2031-11-24. | The new EXE is timestamped and smoke-tested. Its self-signed publisher is **not trusted by Windows**; the updater pins this signer identity. |

Gpg4win was installed temporarily to create and test the Debian key, then
uninstalled. The key files and isolated GnuPG home remain in the protected
signing directory. The Windows self-signed certificate was not added to any
Windows trust store.
The original Android application ID (`com.allinone.android`) and on-device data
folder (`AllInOne`) are retained so existing users can update and keep their
data. The legacy Android namespace, Windows signing subject, Android certificate
subject and GPG user ID remain as signing identities; the user-facing product
name is AllN1Downloader.

## Configure GitHub Actions secrets

In the repository, open **Settings → Secrets and variables → Actions** and add
the secrets below. The clipboard commands avoid printing passwords into the
terminal; paste each clipboard value into the indicated secret before running
the next command. `Set-Clipboard` replaces the current clipboard contents.

### Android

Add `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`,
and `ANDROID_KEY_PASSWORD`:

```powershell
$root = "$env:USERPROFILE\Documents\AllInOneSigning"
$credential = Import-Clixml "$root\android-release-credentials.xml"
[Convert]::ToBase64String([IO.File]::ReadAllBytes("$root\android-release.p12")) | Set-Clipboard
# Paste into ANDROID_KEYSTORE_BASE64.
[Net.NetworkCredential]::new('', $credential.Password).Password | Set-Clipboard
# Paste into ANDROID_KEYSTORE_PASSWORD, then repeat for ANDROID_KEY_PASSWORD.
$credential.UserName
# Use this value for ANDROID_KEY_ALIAS: allinone-release.
```

The Android workflow decodes the keystore into its temporary runner directory.
Do not use a different keystore for later releases; Android will reject updates
signed with another identity.

### Debian

Add `DEB_SIGNING_KEY_BASE64`, `DEB_SIGNING_KEY_ID`, and
`DEB_SIGNING_PASSPHRASE`:

```powershell
$root = "$env:USERPROFILE\Documents\AllInOneSigning"
$credential = Import-Clixml "$root\debian-release-credentials.xml"
[Convert]::ToBase64String([IO.File]::ReadAllBytes("$root\debian-signing-private.asc")) | Set-Clipboard
# Paste into DEB_SIGNING_KEY_BASE64.
$credential.UserName
# Use this fingerprint for DEB_SIGNING_KEY_ID.
[Net.NetworkCredential]::new('', $credential.Password).Password | Set-Clipboard
# Paste into DEB_SIGNING_PASSPHRASE.
```

The Ubuntu workflow imports this private key in an isolated runner GPG home,
signs the `.deb` and `SHA256SUMS`, then uploads detached `.asc` signatures. The
GPG public key is committed at
`packaging/apt/alln1downloader-archive-keyring.asc` and published in the APT
repository so clients can verify repository metadata.

### Windows

The release workflow can use the generated self-signed PFX when
`WINDOWS_SIGN_ALLOW_SELF_SIGNED` is enabled and the expected thumbprint is
configured. This lets the updater authenticate the publisher identity, but
Windows still displays an unknown-publisher warning. For a publicly trusted
publisher identity, obtain a CA-issued certificate or supported cloud/HSM
signer. The workflow must be adapted if that provider keeps its key in hardware
or a cloud service rather than exporting a PFX.

The release workflow uses this PFX and pins thumbprint
`9F1BFF66846716DC3E579D9F61E7A412D36E6336`. Add the matching GitHub Actions
secrets yourself without printing the password:

```powershell
$root = "$env:USERPROFILE\Documents\AllInOneSigning"
$credential = Import-Clixml "$root\windows-alln1-credentials.xml"
[Convert]::ToBase64String([IO.File]::ReadAllBytes("$root\windows-alln1-selfsigned.pfx")) | Set-Clipboard
# Paste into WINDOWS_SIGN_PFX_BASE64.
[Net.NetworkCredential]::new('', $credential.Password).Password | Set-Clipboard
# Paste into WINDOWS_SIGN_PASSWORD.
```

The thumbprint is public configuration, not a secret. If the certificate is
rotated, update the pin in both the Windows build workflow and updater.

To obtain a public-trust certificate, apply for a code-signing certificate from
a CA such as [Sectigo](https://sectigo.com/ssl-certificates-tls/code-signing)
or [DigiCert](https://www.digicert.com/signing/code-signing-certificates), or
evaluate [Microsoft Artifact Signing](https://learn.microsoft.com/en-us/azure/artifact-signing/overview).
Microsoft manages its signing keys in cloud HSMs, so the build needs its signing
client and Azure identity rather than a PFX. Public-trust eligibility depends
on location and applicant type; Microsoft currently limits individual
developers to the US and Canada. For ordinary application EXEs, ask for a
standard/OV code-signing product; EV is mainly required for driver signing.
Neither a new certificate nor EV guarantees immediate SmartScreen reputation.

## Build and verification

### Android release

Set the environment variables from the Android credential file without
printing the password, then build with the existing release signing option:

```powershell
$root = "$env:USERPROFILE\Documents\AllInOneSigning"
$credential = Import-Clixml "$root\android-release-credentials.xml"
$password = [Net.NetworkCredential]::new('', $credential.Password).Password
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:ANDROID_KEYSTORE_PATH = "$root\android-release.p12"
$env:ANDROID_KEYSTORE_PASSWORD = $password
$env:ANDROID_KEY_ALIAS = $credential.UserName
$env:ANDROID_KEY_PASSWORD = $password
try {
  .\android\gradlew.bat -p android assembleRelease bundleRelease -PsignRelease=true `
    -PchaquopyBuildPython='C:/path/to/python3.12.exe'
} finally {
  Remove-Item Env:\ANDROID_KEYSTORE_PATH,Env:\ANDROID_KEYSTORE_PASSWORD,Env:\ANDROID_KEY_ALIAS,Env:\ANDROID_KEY_PASSWORD -ErrorAction SilentlyContinue
  $password = $null
}
```

Verify the APK and AAB:

```powershell
$sdk = "$env:LOCALAPPDATA\Android\Sdk"
$buildTools = (Get-Content android\build-tools-version.txt).Trim()
& "$sdk\build-tools\$buildTools\apksigner.bat" verify --print-certs `
  android\app\build\outputs\apk\release\app-release.apk
& "$env:JAVA_HOME\bin\jarsigner.exe" -verify `
  android\app\build\outputs\bundle\release\app-release.aab
```

### Debian artifacts

After downloading the package and sidecars, import the publisher's separately
obtained public key, then verify the signature and checksum:

```bash
gpg --import packaging/apt/alln1downloader-archive-keyring.asc
gpg --verify SHA256SUMS.asc SHA256SUMS
sha256sum --check SHA256SUMS
deb=$(find . -maxdepth 1 -type f -name 'alln1downloader_*.deb' -print -quit)
gpg --verify "$deb.asc" "$deb"
```

The local Windows machine no longer has Gpg4win installed. These verification
commands run on Linux, or on Windows after installing a GnuPG distribution.

### Current Windows self-signed build

The signed local executable is `dist/AllN1Downloader.exe`. PowerShell reports
`UnknownError` with “root certificate is not trusted”; this is expected for the
self-signed certificate and does not mean the file is unsigned. The signature
has a timestamp, the embedded signer subject is present, and the EXE smoke test
passed. Other computers will not trust this publisher unless their owner
explicitly installs and trusts the certificate; even then, SmartScreen
reputation may still affect warnings.

For a newly built EXE, the local PFX can be used with Windows SDK SignTool. This
does not use the release script's trusted-root verification:

```powershell
$root = "$env:USERPROFILE\Documents\AllInOneSigning"
$credential = Import-Clixml "$root\windows-alln1-credentials.xml"
$password = [Net.NetworkCredential]::new('', $credential.Password).Password
$signtool = 'C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe'
& $signtool sign /fd SHA256 /tr 'http://timestamp.digicert.com' /td SHA256 `
  /f "$root\windows-alln1-selfsigned.pfx" /p $password `
  /d 'AllN1Downloader (Self-Signed)' 'dist\AllN1Downloader.exe'
if ($LASTEXITCODE -ne 0) { throw 'Authenticode signing failed.' }
Get-AuthenticodeSignature 'dist\AllN1Downloader.exe' |
  Format-List Status, StatusMessage, SignerCertificate, TimeStamperCertificate
$password = $null
```

The expected status remains untrusted-root `UnknownError`; the signer and
timestamp should be present. Do not configure this PFX as the public-release
GitHub signing secret.

## Temporary dependency cleanup

Removed after testing: temporary Gpg4win, `aio-android-py312`, `aio-qa-py312`,
`aio-managed-python`, `aio-stable-tools`, and `aio-uv-cache` under
`%LOCALAPPDATA%\Temp\opencode`. Shared Android SDK/NDK and emulator packages,
the active app/runtime, Python installations, and shared caches were retained
to avoid disrupting Android Studio, the running app, or other projects.
