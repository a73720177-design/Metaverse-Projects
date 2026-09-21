$ErrorActionPreference = 'Stop'
$setup = Join-Path $PSScriptRoot 'payload\setup.ps1'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($setup, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($file in @('payload\prepare-wsl.ps1','build.ps1')) {
    $null = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $file), [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
}
foreach ($name in @('Status','RequireRestart','PrepareWsl','PullModel','SelectChatModel')) {
    $node = $ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name}, $true)
    Invoke-Expression $node.Extent.Text
}
$testRoot = Join-Path $env:TEMP ('metaverse-installer-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$InstallRoot = $testRoot; $logDir = $testRoot; $payload = Join-Path $PSScriptRoot 'payload'
$rebootPath = Join-Path $testRoot 'restart-required.json'
function Get-CimInstance($ClassName) {
    switch ($ClassName) {
        Win32_OperatingSystem { [pscustomobject]@{LastBootUpTime=$script:boot} }
        Win32_ComputerSystem { [pscustomobject]@{HypervisorPresent=$script:hypervisor} }
        Win32_Processor { [pscustomobject]@{VirtualizationFirmwareEnabled=$script:firmware} }
    }
}
function ProbeWsl { return $script:ready }
function Start-Process {
    param($FilePath,$ArgumentList,$Verb,[switch]$Wait,[switch]$PassThru,$WindowStyle)
    $script:calls++
    if ($script:cancel) { throw 'UAC cancelled' }
    if ($script:success) { $script:ready=$true; $script:hypervisor=$true }
    return [pscustomobject]@{ExitCode=$script:childCode}
}
function Case($name,$expected,$action) {
    $script:boot=[datetime]'2026-09-13T00:00:00Z'; $script:hypervisor=$true; $script:firmware=$true
    $script:ready=$false; $script:childCode=0; $script:calls=0; $script:cancel=$false; $script:success=$false
    if (Test-Path -LiteralPath $rebootPath) { Remove-Item -LiteralPath $rebootPath }
    $actual='ok'
    try { & $action } catch { if ($_.Exception.Data['RestartRequired']) { $actual='restart' } else { $actual='error' } }
    if ($actual -ne $expected) { throw "$name expected=$expected actual=$actual" }
    Write-Host "PASS $name"
}
Case 'Already ready skips installation' 'ok' { $script:ready=$true; PrepareWsl; if ($script:calls) { throw 'Unexpected install' } }
Case 'First install requires reboot' 'restart' { $script:childCode=3010; PrepareWsl }
Case 'Same boot does not reinstall' 'ok' {
    try { RequireRestart 'test' } catch {}
    try { PrepareWsl; throw 'Missing restart' } catch { if (-not $_.Exception.Data['RestartRequired']) { throw } }
    if ($script:calls -ne 0) { throw 'Repeated installation' }
}
Case 'After reboot resumes' 'ok' {
    try { RequireRestart 'test' } catch {}
    $script:boot=$script:boot.AddMinutes(5); $script:ready=$true; PrepareWsl
    if (Test-Path -LiteralPath $rebootPath) { throw 'Stale reboot marker' }
}
Case 'Install error is not reboot' 'error' { $script:childCode=1; PrepareWsl }
Case 'UAC cancellation is not reboot' 'error' { $script:cancel=$true; PrepareWsl }
Case 'Firmware disabled is not reboot' 'error' { $script:hypervisor=$false; $script:firmware=$false; PrepareWsl }
Case 'Successful repair continues' 'ok' { $script:success=$true; PrepareWsl }
Case 'Failed postcheck is not reboot' 'error' { PrepareWsl }
function Start-Sleep { param($Seconds) }
function Compose {
    param($Arguments)
    $script:pullCalls++
    if ($script:pullCalls -le $script:failCount) { throw 'simulated network failure' }
}
$script:pullCalls=0; $script:failCount=2
PullModel 'qwen3:4b'
if ($script:pullCalls -ne 3) { throw 'Retry recovery failed' }
Write-Host 'PASS model download recovers after transient failures'
$script:pullCalls=0; $script:failCount=3
$caught=$false
try { PullModel 'bge-m3' } catch {
    $caught=$true
    if ($_.Exception.Data['RestartRequired']) { throw 'Download failure incorrectly requests reboot' }
}
if (-not $caught -or $script:pullCalls -ne 3) { throw 'Retry limit failed' }
Write-Host 'PASS repeated download failure stops without reboot'
function Read-Host { param($Prompt); return $script:modelChoice }
$script:modelChoice='1'
if ((SelectChatModel) -ne 'qwen3:4b') { throw '4B model selection failed' }
if (($script:modelsToInstall -join ',') -ne 'qwen3:4b') { throw '4B download list failed' }
$script:modelChoice='2'
if ((SelectChatModel) -ne 'qwen3.5:9b') { throw '9B model selection failed' }
$script:modelChoice='3'
if ((SelectChatModel) -ne 'qwen3:4b') { throw 'Both-model default selection failed' }
if (($script:modelsToInstall -join ',') -ne 'qwen3:4b,qwen3.5:9b') { throw 'Both-model download list failed' }
Write-Host 'PASS interactive model selection'
Write-Host 'All simulated scenarios passed. No WSL/Docker installation or reboot executed.'
