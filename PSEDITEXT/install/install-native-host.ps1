param(
    [Parameter(Mandatory = $true)]
    [string]$ExtensionId,

    [Parameter(Mandatory = $true)]
    [string]$AppExe
)

$ErrorActionPreference = "Stop"
$InstallRoot = Split-Path -Parent $PSScriptRoot
$ManifestPath = Join-Path $InstallRoot "native_host\com.psedit.bridge.json"

if (-not (Test-Path -LiteralPath $AppExe -PathType Leaf)) {
    throw "PseDIT.exe not found: $AppExe"
}

$dir = Split-Path -Parent $ManifestPath
New-Item -ItemType Directory -Path $dir -Force | Out-Null

$manifest = [ordered]@{
    name = "com.psedit.bridge"
    description = "PseDIT AI Runtime Native Messaging bridge"
    path = (Resolve-Path -LiteralPath $AppExe).Path
    type = "stdio"
    allowed_origins = @("chrome-extension://$ExtensionId/")
}

$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ManifestPath -Encoding UTF8

$registryLocations = @(
    "HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.psedit.bridge",
    "HKCU:\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\com.psedit.bridge",
    "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\com.psedit.bridge"
)

foreach ($key in $registryLocations) {
    New-Item -Path $key -Force | Out-Null
    Set-ItemProperty -Path $key -Name "(Default)" -Value $ManifestPath
}

Write-Host "Native Messaging host registered."
Write-Host "Manifest: $ManifestPath"
Write-Host "Host: $AppExe"
