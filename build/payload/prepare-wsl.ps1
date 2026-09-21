param([string]$LogPath)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$result = 0
Start-Transcript -LiteralPath $LogPath | Out-Null
try {
    $restart = $false
    foreach ($name in @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform')) {
        $feature = Get-WindowsOptionalFeature -Online -FeatureName $name
        if ($feature.State -eq 'EnablePending') { $restart = $true; continue }
        if ($feature.State -ne 'Enabled') {
            $change = Enable-WindowsOptionalFeature -Online -FeatureName $name -All -NoRestart
            $restart = $true
        }
    }
    $wsl = Join-Path $env:WINDIR 'System32\wsl.exe'
    # Install the WSL runtime without an unnecessary Ubuntu/user setup prompt.
    & $wsl --install --no-distribution
    $code = $LASTEXITCODE
    if ($code -in @(3010,1641)) { $restart = $true }
    elseif ($code -ne 0) { throw "wsl --install --no-distribution failed: $code" }
    if ($restart) { $result = 3010 }
    else {
        & $wsl --update
        $code = $LASTEXITCODE
        if ($code -in @(3010,1641)) { $result = 3010 }
        elseif ($code -ne 0) { throw "wsl --update failed: $code" }
        if ($result -eq 0) {
            & $wsl --set-default-version 2
            if ($LASTEXITCODE -ne 0) { throw "wsl --set-default-version 2 failed: $LASTEXITCODE" }
        }
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    $result = 1
} finally { Stop-Transcript | Out-Null }
exit $result
