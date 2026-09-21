$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'payload\setup.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @('DockerRun','StopLocalProject')) {
    $node = $ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name}, $true)
    Invoke-Expression $node.Extent.Text
}
$testRoot = Join-Path $env:TEMP ('metaverse-exe-regression-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$script:docker = Join-Path $testRoot 'argument-echo.exe'
Add-Type -TypeDefinition @'
using System;
public class ArgumentEcho {
    public static int Main(string[] args) {
        foreach (string arg in args) Console.WriteLine(arg);
        Console.Error.WriteLine("stderr marker");
        return Array.IndexOf(args, "fail") >= 0 ? 7 : 0;
    }
}
'@ -OutputAssembly $script:docker -OutputType ConsoleApplication
$script:dockerContext = 'desktop-linux'
$dockerLog = Join-Path $testRoot 'docker.log'
$literalPath = 'C:\한글 경로\%PATH% & safe\compose.yaml'
$output = @(DockerRun @('compose','--file',$literalPath))
if ($output -notcontains $literalPath) { throw 'Native argument was expanded or split' }
if ($output -notcontains 'stderr marker') { throw 'stderr was lost' }
Write-Host 'PASS literal percent, shell characters, Korean and spaces; stderr logging'
$failed = $false
try { DockerRun @('fail') | Out-Null } catch { $failed = $true }
if (-not $failed) { throw 'Native failure was hidden' }
Write-Host 'PASS nonzero exit code preserved'
function DockerRun([string[]]$Arguments) {
    if ($Arguments[0] -eq 'ps') {
        if ($Arguments -notcontains 'label=com.docker.compose.project=metaverse-local-test') { throw 'Wrong project filter' }
        return @('container-one','container-two')
    }
    if (($Arguments -join ',') -ne 'stop,container-one,container-two') { throw 'Unexpected stop targets' }
    $script:stopped = $true
}
$script:stopped = $false
StopLocalProject 'metaverse-local-test'
if (-not $script:stopped) { throw 'Project was not stopped' }
Write-Host 'PASS stop selects only this installation, without config writes'
