$ErrorActionPreference = 'Stop'
$buildRoot = $PSScriptRoot
$payloadRoot = Join-Path $buildRoot 'payload'
$outputRoot = Split-Path $buildRoot -Parent
$requiredPayloadFiles = @(
    'setup.ps1',
    'compose.yaml',
    'backend\app\main.py',
    'llm-service\app\main.py',
    'llm-service\app\installer_check.py',
    'web\index.html'
)
foreach ($relativePath in $requiredPayloadFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $payloadRoot $relativePath))) {
        throw "Required payload file is missing: $relativePath"
    }
}
# Windows PowerShell 5.1 requires a BOM for Korean script literals.
foreach ($name in @('setup.ps1','prepare-wsl.ps1')) {
    $scriptPath = Join-Path $payloadRoot $name
    $scriptText = [IO.File]::ReadAllText($scriptPath)
    [IO.File]::WriteAllText($scriptPath, $scriptText, (New-Object Text.UTF8Encoding $true))
}
$manifestPath = Join-Path $payloadRoot 'manifest.json'
$files = @(Get-ChildItem -LiteralPath $payloadRoot -File -Recurse | Where-Object {
    $_.FullName -ne $manifestPath -and $_.FullName -notmatch '[\\/]__pycache__[\\/]|\.pyc$'
} | ForEach-Object {
    @{ path=$_.FullName.Substring($payloadRoot.Length + 1).Replace('\','/'); sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
})
@{branch='fix/korean-only-llm-output-20260919'; commit='34aba2d8730b20050f9b9bfe6db8f1559b9db069'; source='packaged-source-local-patches'; patch='exe-audit-practice-trait-validation-20260920'; files=$files} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
$zip = Join-Path $buildRoot 'payload.zip'
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
& tar.exe -a -cf $zip --exclude='*/__pycache__/*' --exclude='*.pyc' -C $payloadRoot .
if ($LASTEXITCODE -ne 0) { throw 'Payload archive creation failed' }
$exe = Join-Path $outputRoot 'Metaverse-Setup.exe'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compiler /nologo /target:exe /platform:x64 /optimize+ /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll "/resource:$zip,payload.zip" "/out:$exe" (Join-Path $buildRoot 'Launcher.cs')
if ($LASTEXITCODE -ne 0) { throw 'EXE compilation failed' }
Copy-Item -LiteralPath (Join-Path $payloadRoot 'examples\sample-presentation.pdf') -Destination $outputRoot -Force
$hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash
"$hash  Metaverse-Setup.exe" | Set-Content -LiteralPath (Join-Path $outputRoot 'SHA256.txt') -Encoding ASCII
Get-Item -LiteralPath $exe | Select-Object FullName,Length
