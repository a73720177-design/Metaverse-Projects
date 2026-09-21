param([string]$InstallRoot, [switch]$Stop, [switch]$CheckOnly, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$ProgressPreference = 'SilentlyContinue'
$payload = $PSScriptRoot
if (-not $InstallRoot) { $InstallRoot = Join-Path $env:LOCALAPPDATA 'MetaverseLocal' }
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$logDir = Join-Path $InstallRoot 'logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$logFile = Join-Path $logDir ('setup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
$dockerLog = Join-Path $logDir ('docker-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
Start-Transcript -LiteralPath $logFile | Out-Null
$exitCode = 0
function Status([string]$message) {
    $script:stage = $message
    Write-Host "`n$message" -ForegroundColor Cyan
}
$script:stage = '패키지 검사'
$script:modelsToInstall = @()
$rebootPath = Join-Path $InstallRoot 'restart-required.json'
function RequireRestart([string]$reason) {
    @{ boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o'); reason = $reason } |
        ConvertTo-Json | Set-Content -LiteralPath $rebootPath -Encoding UTF8
    $exception = New-Object System.Exception("$reason Windows의 다시 시작을 선택한 후 같은 EXE를 실행하세요.")
    $exception.Data['RestartRequired'] = $true
    throw $exception
}
function ProbeWsl {
    $wsl = Join-Path $env:WINDIR 'System32\wsl.exe'
    if (-not (Test-Path -LiteralPath $wsl)) { return $false }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $status = & $wsl --status 2>&1
        $statusCode = $LASTEXITCODE
        $versionText = ((& $wsl --version 2>&1) -join "`n").Replace([string][char]0, '')
        $versionCode = $LASTEXITCODE
        $match = [regex]::Match($versionText, '\d+\.\d+\.\d+')
        return ($statusCode -eq 0 -and $versionCode -eq 0 -and $match.Success -and [version]$match.Value -ge [version]'2.1.5')
    } finally { $ErrorActionPreference = $previous }
}
function PrepareWsl {
    Status '[0/7] WSL 2 및 Windows 가상화 준비'
    if (Test-Path -LiteralPath $rebootPath) {
        $pending = Get-Content -LiteralPath $rebootPath -Raw | ConvertFrom-Json
        $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
        if ($pending.boot -eq $boot) { RequireRestart $pending.reason }
        Remove-Item -LiteralPath $rebootPath
        Write-Host '재부팅 확인 완료. 현재 설치 상태를 다시 검사합니다.'
    }
    $system = Get-CimInstance Win32_ComputerSystem
    $processors = @(Get-CimInstance Win32_Processor)
    if (-not $system.HypervisorPresent -and ($processors | Where-Object { $_.VirtualizationFirmwareEnabled -eq $false })) {
        throw 'BIOS/UEFI의 Intel VT-x 또는 AMD SVM 가상화를 켜야 합니다. 가상 PC에서는 호스트의 중첩 가상화 설정이 필요합니다. WSL 설치만으로 BIOS 설정을 변경할 수 없습니다.'
    }
    if ((ProbeWsl) -and $system.HypervisorPresent) { Write-Host 'WSL 2 준비 확인 완료'; return }
    $wslLog = Join-Path $logDir ('wsl-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
    Write-Host 'WSL 설치 및 가상 머신 플랫폼 활성화를 위해 관리자 승인을 요청합니다.'
    $powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $payload 'prepare-wsl.ps1') + '" -LogPath "' + $wslLog + '"'
    try { $process = Start-Process -FilePath $powershell -ArgumentList $arguments -Verb RunAs -Wait -PassThru -WindowStyle Hidden }
    catch { throw "WSL 관리자 실행 실패 또는 승인 취소: $($_.Exception.Message)" }
    if ($process.ExitCode -in @(3010,1641)) { RequireRestart 'WSL/가상 머신 플랫폼 설치가 완료되어 재부팅이 필요합니다.' }
    if ($process.ExitCode -ne 0) { throw "WSL 준비 실패 (코드 $($process.ExitCode)). 상세 로그: $wslLog. 오류를 해결한 뒤 다시 실행하세요." }
    if (-not (ProbeWsl)) { throw "WSL 설치 후 상태 검사 실패. 상세 로그: $wslLog. 관리자 명령 프롬프트에서 wsl --status와 wsl --update 결과를 확인하세요." }
    if (-not (Get-CimInstance Win32_ComputerSystem).HypervisorPresent) {
        throw 'Windows 하이퍼바이저가 실행되지 않았습니다. BIOS 가상화 및 부팅 설정의 hypervisorlaunchtype을 확인하세요. 같은 오류가 반복되면 로그를 전달하세요.'
    }
}
function RandomHex([int]$count) {
    $bytes = New-Object byte[] $count
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
}
function FindDocker {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
        (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
    )
    $cmd = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    foreach ($candidate in $candidates) { if (Test-Path -LiteralPath $candidate) { return $candidate } }
    return $null
}
function DockerRun([string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        # Do not persist `docker inspect` output because it can contain secrets.
        # Other Docker output is mirrored to a dedicated log so native stderr is
        # available even when PowerShell transcript logging misses it.
        if ($Arguments.Count -gt 0 -and $Arguments[0] -eq 'inspect') {
            & $script:docker --context $script:dockerContext @Arguments
        } else {
            # Pass arguments directly: cmd.exe expands %NAME% in installation
            # paths and can reinterpret shell characters. Normalize stderr only.
            & $script:docker --context $script:dockerContext @Arguments 2>&1 |
                ForEach-Object { "$_" } |
                Tee-Object -FilePath $dockerLog -Append
        }
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw "Docker 작업 실패 (종료 코드 $code). 상세 로그: $dockerLog. 오류를 해결한 뒤 EXE를 다시 실행하세요." }
}
function Compose([string[]]$Arguments) { DockerRun ($script:composeArgs + $Arguments) | Out-Host }
function StopLocalProject([string]$project) {
    $ids = @(DockerRun @('ps','--quiet','--filter',"label=com.docker.compose.project=$project"))
    if ($ids.Count) { DockerRun (@('stop') + $ids) | Out-Host }
    Write-Host '이 앱의 서버를 종료했습니다. 계정, 문서, 모델과 설정은 유지됩니다.'
}
function ReadOptionalText([string]$path) {
    try { return [IO.File]::ReadAllText($path) }
    catch [IO.FileNotFoundException] { return $null }
    catch [IO.DirectoryNotFoundException] { return $null }
    catch { throw "설정 파일을 읽을 수 없습니다: $path. 파일 접근 권한을 확인하세요. 기존 설정을 덮어쓰지 않았습니다." }
}
function AssertLocalConfig($value, [string]$expectedProject) {
    if ($value.project -ne $expectedProject -or [string]$value.port -notmatch '^181[89][0-9]$' -or
        $value.dbPassword -notmatch '^[a-f0-9]{48}$' -or $value.jwtSecret -notmatch '^[a-f0-9]{64}$') {
        throw '기존 설치 설정의 형식 또는 프로젝트가 일치하지 않습니다. 기존 설정과 데이터를 유지했습니다.'
    }
}
function SaveLocalConfig($value, [string]$path) {
    $temporary = $path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    [IO.File]::WriteAllText($temporary, ($value | ConvertTo-Json), (New-Object Text.UTF8Encoding $true))
    # Only create a missing config; never overwrite a file that appeared during recovery.
    [IO.File]::Move($temporary, $path)
}
function RecoverLocalConfig([string]$project) {
    $backup = ReadOptionalText (Join-Path $InstallRoot 'config.backup.json')
    if ($null -ne $backup) {
        $value = $backup | ConvertFrom-Json
        AssertLocalConfig $value $project
        Write-Host '설정 백업에서 기존 설치 설정을 복구합니다.'
        return $value
    }
    $savedEnvironment = ReadOptionalText (Join-Path $InstallRoot 'compose.env')
    if ($null -ne $savedEnvironment) {
        $values = @{}
        foreach ($line in ($savedEnvironment -split '\r?\n')) {
            if ($line -match '^(DB_PASSWORD|JWT_SECRET_KEY|WEB_PORT)=(.*)$') { $values[$Matches[1]] = $Matches[2].Trim() }
        }
        $value = [pscustomobject]@{project=$project; port=$values.WEB_PORT; dbPassword=$values.DB_PASSWORD; jwtSecret=$values.JWT_SECRET_KEY}
        AssertLocalConfig $value $project
        Write-Host 'compose.env에서 기존 설치 설정을 복구합니다.'
        return $value
    }
    # Read only containers belonging to this exact installation. Never inspect another project.
    $ids = @(DockerRun @('ps','--all','--quiet','--filter',"label=com.docker.compose.project=$project"))
    if ($ids.Count -eq 0) { return $null }
    $containers = (DockerRun (@('inspect') + $ids)) -join "`n" | ConvertFrom-Json
    $dbPasswords = @(); $jwtSecrets = @(); $ports = @()
    foreach ($container in $containers) {
        if ($container.Config.Labels.'com.docker.compose.project' -ne $project) { throw '설정 복구 대상 프로젝트 불일치' }
        $service = $container.Config.Labels.'com.docker.compose.service'
        if ($service -eq 'db') {
            foreach ($entry in $container.Config.Env) {
                if ($entry -match '^POSTGRES_PASSWORD=([a-f0-9]{48})$') { $dbPasswords += $Matches[1] }
            }
        }
        if ($service -eq 'backend') {
            foreach ($entry in $container.Config.Env) {
                if ($entry -match '^JWT_SECRET_KEY=([a-f0-9]{64})$') { $jwtSecrets += $Matches[1] }
            }
        }
        if ($service -eq 'web') {
            foreach ($binding in $container.HostConfig.PortBindings.'80/tcp') { $ports += [string]$binding.HostPort }
        }
    }
    $dbPasswords = @($dbPasswords | Select-Object -Unique)
    $jwtSecrets = @($jwtSecrets | Select-Object -Unique)
    $ports = @($ports | Select-Object -Unique)
    if ($dbPasswords.Count -ne 1 -or $jwtSecrets.Count -ne 1 -or $ports.Count -ne 1) { return $null }
    $value = [pscustomobject]@{project=$project; port=$ports[0]; dbPassword=$dbPasswords[0]; jwtSecret=$jwtSecrets[0]}
    AssertLocalConfig $value $project
    Write-Host '이 설치의 기존 Docker 컨테이너에서 설정을 복구합니다.'
    return $value
}
function PullModel([string]$model) {
    for ($retry = 1; $retry -le 3; $retry++) {
        try { Compose @('exec','-T','ollama','ollama','pull',$model); return }
        catch {
            if ($retry -eq 3) { throw "모델 $model 다운로드가 3회 실패했습니다. 인터넷 연결과 Docker 저장 공간을 확인하세요. 재실행 시 다운로드된 데이터를 재사용합니다. $($_.Exception.Message)" }
            Write-Host "모델 $model 다운로드 재시도 $($retry + 1)/3 (5초 후)"
            Start-Sleep -Seconds 5
        }
    }
}
function SelectChatModel {
    Write-Host "`n사용할 LLM 모델을 선택하세요." -ForegroundColor Cyan
    Write-Host '  [1] qwen3:4b    - 빠른 실행, 낮은 메모리 사용 (권장)'
    Write-Host '  [2] qwen3.5:9b  - 더 높은 품질, 더 긴 다운로드와 높은 메모리 사용'
    Write-Host '  [3] 두 모델 모두 - 4B와 9B를 모두 다운로드하고 4B로 시작'
    while ($true) {
        $choice = (Read-Host '선택 [1/2/3, 기본값 1]').Trim()
        if (-not $choice -or $choice -eq '1' -or $choice -eq 'qwen3:4b') {
            $script:modelsToInstall = @('qwen3:4b')
            return 'qwen3:4b'
        }
        if ($choice -eq '2' -or $choice -eq 'qwen3.5:9b') {
            $script:modelsToInstall = @('qwen3.5:9b')
            Write-Host 'qwen3.5:9b는 최소 약 8GB 이상의 여유 메모리를 권장하며 최초 선택 시 모델을 다운로드합니다.' -ForegroundColor Yellow
            return 'qwen3.5:9b'
        }
        if ($choice -eq '3') {
            $script:modelsToInstall = @('qwen3:4b','qwen3.5:9b')
            Write-Host '두 모델을 모두 다운로드합니다. 설치 후 기본 모델은 qwen3:4b이며 화면에서 9B로 변경할 수 있습니다.' -ForegroundColor Yellow
            return 'qwen3:4b'
        }
        Write-Host '1, 2 또는 3을 입력하세요.' -ForegroundColor Yellow
    }
}
function SaveDiagnostics {
    if (-not $script:docker -or -not $script:composeArgs) { return }
    $diagnostic = Join-Path $logDir ('services-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $script:docker --context $script:dockerContext @script:composeArgs ps --all 2>&1 | Out-File -LiteralPath $diagnostic -Encoding UTF8
        & $script:docker --context $script:dockerContext @script:composeArgs logs --no-color --tail 80 2>&1 | Out-File -LiteralPath $diagnostic -Append -Encoding UTF8
        Write-Host "서비스 진단 로그: $diagnostic"
    } catch { Write-Host '서비스 진단 수집 실패. 설치 로그를 확인하세요.' }
    finally { $ErrorActionPreference = $previous }
}
function MakeShortcut([string]$name, [string]$arguments) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) ($name + '.lnk')))
    $link.TargetPath = Join-Path $InstallRoot 'Metaverse-Setup.exe'
    $link.Arguments = $arguments
    $link.WorkingDirectory = $InstallRoot
    $link.Save()
}
try {
    Status 'Metaverse Local - 설치 및 실행 준비'
    Write-Host '최초 실행: 인터넷 연결과 수 GB 이상의 다운로드가 필요합니다.'
    Write-Host 'Docker/WSL 최초 설치 시 Windows 승인, 약관 확인 또는 재부팅이 필요할 수 있습니다.'
    Write-Host 'NVIDIA GPU가 감지되면 vLLM GPU 생성 서버와 병렬 처리를 기본으로 사용합니다.'
    if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64' -and $env:PROCESSOR_ARCHITEW6432 -ne 'AMD64') {
        throw '이 설치 파일은 Windows x64 전용입니다.'
    }
    $required = @('compose.yaml','backend\Dockerfile','backend\app\main.py','llm-service\Dockerfile','web\index.html','examples\sample-presentation.pdf')
    foreach ($file in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $payload $file))) { throw "패키지 파일 누락: $file" }
    }
    $manifest = Get-Content -LiteralPath (Join-Path $payload 'manifest.json') -Raw | ConvertFrom-Json
    foreach ($entry in $manifest.files) {
        $path = [IO.Path]::GetFullPath((Join-Path $payload $entry.path))
        if (-not $path.StartsWith($payload + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw '패키지 검사 경로 오류' }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $entry.sha256) { throw "패키지 무결성 검사 실패: $($entry.path)" }
    }
    Write-Host "패키지 무결성 확인 완료: $($manifest.files.Count)개 파일, 브랜치 $($manifest.branch)"
    if ($CheckOnly) { Write-Host '검사 완료. Docker 설치, DB 생성, 모델 다운로드, 서버 시작은 실행하지 않았습니다.'; exit 0 }
    if (-not $Stop) { $env:OLLAMA_CHAT_MODEL = SelectChatModel }
    if (-not $env:OLLAMA_CHAT_MODEL) { $env:OLLAMA_CHAT_MODEL = 'qwen3:4b' }
    if (-not $script:modelsToInstall.Count) { $script:modelsToInstall = @($env:OLLAMA_CHAT_MODEL) }

    if (-not $Stop) { PrepareWsl }
    $script:docker = FindDocker
    if (-not $script:docker) {
        if ($Stop) { throw 'Docker가 설치되어 있지 않아 종료할 서버가 없습니다.' }
        Status '[1/7] Docker Desktop 다운로드 및 설치'
        $cache = Join-Path $InstallRoot 'downloads'
        New-Item -ItemType Directory -Force $cache | Out-Null
        $installer = Join-Path $cache 'DockerDesktopInstaller.exe'
        $url = 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe'
        & curl.exe --fail --location --retry 3 --output $installer $url
        if ($LASTEXITCODE -ne 0) { throw 'Docker 다운로드 실패. 인터넷 연결을 확인하세요.' }
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Docker') {
            throw 'Docker 설치 파일의 공식 전자서명을 확인하지 못했습니다.'
        }
        $installProcess = Start-Process -FilePath $installer -ArgumentList 'install','--user' -PassThru -Wait -WindowStyle Hidden
        if ($installProcess.ExitCode -in @(3010,1641)) { RequireRestart 'Docker 설치 프로그램이 재부팅을 요청했습니다.' }
        if ($installProcess.ExitCode -ne 0) { throw "Docker 설치 실패: $($installProcess.ExitCode). 설치 창의 안내를 확인하세요." }
        $script:docker = FindDocker
        if (-not $script:docker) { throw 'Docker 설치 완료 후 같은 EXE를 다시 실행하세요.' }
    }

    # Select a local named-pipe context explicitly; never use a remote Docker host.
    $script:dockerContext = $null
    foreach ($context in @('desktop-linux','default')) {
        $oldPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $endpoint = & $script:docker context inspect $context --format '{{.Endpoints.docker.Host}}' 2>$null
        $code = $LASTEXITCODE
        $ErrorActionPreference = $oldPreference
        if ($code -eq 0 -and "$endpoint" -like 'npipe://*') { $script:dockerContext = $context; break }
    }
    if (-not $script:dockerContext) { throw '로컬 Docker 연결을 찾지 못했습니다. Docker Desktop을 실행한 뒤 다시 시도하세요.' }
    Status '[1/7] 로컬 Docker 엔진 확인'
    $ready = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        $oldPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $infoOutput = @(& $script:docker --context $script:dockerContext info --format '{{.OSType}}' 2>&1)
        $code = $LASTEXITCODE
        $osType = ($infoOutput -join "`n").Trim()
        $ErrorActionPreference = $oldPreference
        if ($code -eq 0) {
            if ("$osType" -ne 'linux') { throw 'Docker Desktop을 Linux containers 모드로 전환해야 합니다.' }
            $ready = $true; break
        }
        if ($Stop) { throw 'Docker 엔진이 꺼져 있습니다. 앱 서버도 실행 중이 아닙니다.' }
        if ($attempt -eq 0) {
            foreach ($desktop in @((Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'),(Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'))) {
                if (Test-Path -LiteralPath $desktop) { Start-Process -FilePath $desktop -WindowStyle Hidden; break }
            }
            Write-Host 'Docker 시작을 기다립니다. 최초 실행 약관 창이 있으면 확인하세요.'
        }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        Write-Host "Docker 마지막 오류 (코드 $code): $osType"
        throw 'Docker 시작 대기 시간이 초과되었습니다. Docker Desktop을 열어 오류/업데이트/약관을 확인하세요. 이 오류 자체는 재부팅 요청이 아닙니다. 해결 후 EXE를 다시 실행하면 완료된 단계를 확인하고 계속합니다.'
    }
    Status '[1/7] 기존 설치 설정 읽기 및 복구'
    $configPath = Join-Path $InstallRoot 'config.json'
    $gpuFlagPath = Join-Path $InstallRoot 'gpu.enabled'
    if (-not $Stop -and -not (Test-Path -LiteralPath $configPath) -and -not (Test-Path -LiteralPath $gpuFlagPath)) {
        $nvidiaSmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
        if (-not $nvidiaSmi) {
            $systemNvidiaSmi = Join-Path $env:WINDIR 'System32\nvidia-smi.exe'
            if (Test-Path -LiteralPath $systemNvidiaSmi) { $nvidiaSmi = $systemNvidiaSmi }
        }
        if ($nvidiaSmi) {
            New-Item -ItemType File -Path $gpuFlagPath -Force | Out-Null
            Write-Host 'NVIDIA GPU가 감지되어 vLLM GPU 모드를 기본으로 활성화했습니다.' -ForegroundColor Green
        }
    }
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $suffix = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($sid + $InstallRoot)))).Replace('-','').Substring(0,10).ToLowerInvariant() } finally { $sha.Dispose() }
    $project = "metaverse-local-$suffix"
    # Stop by the installation's label before recovering or writing any config.
    # This also stops orphaned vLLM containers when GPU settings have changed.
    if ($Stop) { StopLocalProject $project; exit 0 }
    $configText = ReadOptionalText $configPath
    if ($null -ne $configText) {
        $config = $configText | ConvertFrom-Json
        AssertLocalConfig $config $project
    } else {
        $config = RecoverLocalConfig $project
        if ($null -ne $config) {
            SaveLocalConfig $config $configPath
        } else {
        $existing = DockerRun @('volume','ls','--filter',"label=com.docker.compose.project=$project",'--format','{{.Name}}')
        if ($existing) { throw "기존 데이터는 있지만 설정을 복구할 백업, compose.env 또는 컨테이너 정보가 부족합니다. 원래 config.json 또는 compose.env를 $InstallRoot 에 복원하세요. 기존 볼륨은 삭제하지 않았습니다." }
        if ($Stop) { throw '설치 설정이 없습니다.' }
        $port = 18180
        while ($port -lt 18200) {
            $listener = New-Object Net.Sockets.TcpListener ([Net.IPAddress]::Loopback), $port
            try { $listener.Start(); $listener.Stop(); break } catch { $port++ }
        }
        if ($port -eq 18200) { throw '18180~18199 포트가 모두 사용 중입니다.' }
        $config = [pscustomobject]@{ port=$port; project=$project; dbPassword=(RandomHex 24); jwtSecret=(RandomHex 32) }
        SaveLocalConfig $config $configPath
        }
    }
    AssertLocalConfig $config $project
    $backupPath = Join-Path $InstallRoot 'config.backup.json'
    if ($null -eq (ReadOptionalText $backupPath)) { SaveLocalConfig $config $backupPath }
    $env:DB_PASSWORD = $config.dbPassword
    $env:JWT_SECRET_KEY = $config.jwtSecret
    $env:WEB_PORT = [string]$config.port
    $generationConcurrency = '2'
    $vllmSourceModel = if ($env:OLLAMA_CHAT_MODEL -eq 'qwen3.5:9b') {
        'RedHatAI/Qwen3.5-9B-quantized.w4a16'
    } else {
        'RedHatAI/Qwen3.5-4B-quantized.w4a16'
    }
    $env:OLLAMA_NUM_PARALLEL = $generationConcurrency
    $env:LLM_MAX_CONCURRENT_GENERATIONS = $generationConcurrency
    $env:PRACTICE_MAX_CONCURRENT_PERSONAS = $generationConcurrency
    @(
        "OLLAMA_CHAT_MODEL=$($env:OLLAMA_CHAT_MODEL)",
        "OLLAMA_NUM_PARALLEL=$generationConcurrency",
        "LLM_MAX_CONCURRENT_GENERATIONS=$generationConcurrency",
        "PRACTICE_MAX_CONCURRENT_PERSONAS=$generationConcurrency",
        "VLLM_MODEL=$($env:OLLAMA_CHAT_MODEL)",
        "VLLM_SOURCE_MODEL=$vllmSourceModel"
    ) | Set-Content -LiteralPath (Join-Path $InstallRoot '.env') -Encoding ASCII
    $envFile = Join-Path $InstallRoot 'compose.env'
    @(
        "DB_PASSWORD=$($config.dbPassword)",
        "JWT_SECRET_KEY=$($config.jwtSecret)",
        "WEB_PORT=$($config.port)",
        "OLLAMA_CHAT_MODEL=$($env:OLLAMA_CHAT_MODEL)",
        "OLLAMA_NUM_PARALLEL=$generationConcurrency",
        "LLM_MAX_CONCURRENT_GENERATIONS=$generationConcurrency",
        "PRACTICE_MAX_CONCURRENT_PERSONAS=$generationConcurrency",
        "VLLM_MODEL=$($env:OLLAMA_CHAT_MODEL)",
        "VLLM_SOURCE_MODEL=$vllmSourceModel"
    ) | Set-Content -LiteralPath $envFile -Encoding ASCII
    $script:composeArgs = @('compose','--progress','plain','--project-name',$config.project,'--env-file',$envFile,'--file',(Join-Path $payload 'compose.yaml'))
    if (Test-Path -LiteralPath $gpuFlagPath) { $script:composeArgs += @('--file',(Join-Path $payload 'compose.gpu.yaml')); Write-Host 'NVIDIA GPU 모드가 선택되었습니다.' }
    if ($Stop) {
        Compose @('stop')
        Write-Host '이 앱의 서버를 종료했습니다. 계정, 문서, 모델은 유지됩니다.'
    } else {
        Status '[2/7] 앱 실행 환경 빌드 (최초 실행 시 다운로드)'
        $buildStamp = Join-Path $InstallRoot 'images-ready.txt'
        $packageHash = (Get-FileHash -LiteralPath (Join-Path $payload 'manifest.json') -Algorithm SHA256).Hash
        $needBuild = -not (Test-Path -LiteralPath $buildStamp)
        if (-not $needBuild) { $needBuild = (Get-Content -LiteralPath $buildStamp -Raw).Trim() -ne $packageHash }
        foreach ($service in @('backend','llm','web')) {
            $imageId = DockerRun @('image','ls','--quiet',"$($config.project)-$service")
            if (-not $imageId) { $needBuild = $true }
        }
        if ($needBuild) {
            $drive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($InstallRoot))
            if ($drive.AvailableFreeSpace -lt 20GB) { throw '설치 드라이브에 최소 20GB의 여유 공간을 확보한 뒤 다시 실행하세요.' }
            Compose @('build')
            Set-Content -LiteralPath $buildStamp -Value $packageHash -Encoding ASCII
        } else { Write-Host '기존 앱 실행 환경을 사용합니다.' }
        Status '[3/7] 전용 DB 및 AI 서버 시작'
        Compose @('up','-d','--wait','--wait-timeout','240','db','ollama')
        Status '[4/7] DB 마이그레이션 검사 및 적용'
        Compose @('run','--rm','--no-deps','backend','python','-m','scripts.apply_migrations','--dry-run')
        Compose @('run','--rm','--no-deps','backend','python','-m','scripts.apply_migrations','--apply','--confirm-database','metaverse_local')
        Status '[5/7] AI 모델 확인 및 다운로드'
        $availableModels = (DockerRun ($script:composeArgs + @('exec','-T','ollama','ollama','list'))) -join "`n"
        foreach ($model in @($script:modelsToInstall + @('bge-m3','qwen3-vl:4b-instruct')) | Select-Object -Unique) {
            $pattern = '(?m)^' + [regex]::Escape($model) + '(?::latest)?\s'
            Status "[5/7] AI 모델 확인 및 다운로드: $model"
            if ($availableModels -notmatch $pattern) { PullModel $model } else { Write-Host "$model 준비됨" }
        }
        Status '[6/7] 앱 서버 시작 및 상태 검사'
        Compose @('up','-d','--wait','--wait-timeout','1800')
        $url = "http://127.0.0.1:$($config.port)"
        $releaseToken = $packageHash.Substring(0, 12)
        $appUrl = $url + '/?model=' + [uri]::EscapeDataString($env:OLLAMA_CHAT_MODEL) + '&release=' + $releaseToken
        $health = Invoke-RestMethod -Uri "$url/api-backend/health/services" -TimeoutSec 30
        if ($health.status -ne 'ok') { throw '서비스 상태 검사 실패. 준비 완료로 처리하지 않습니다.' }
        Status '[6/7] AI 실제 응답 및 임베딩 검사 (CPU에서는 수 분 걸릴 수 있음)'
        Compose @('exec','-T','llm','python','-m','app.installer_check')
        Status '[7/7] 예시 파일 및 바로가기 준비'
        $examples = Join-Path $InstallRoot 'examples'
        New-Item -ItemType Directory -Force $examples | Out-Null
        Copy-Item -LiteralPath (Join-Path $payload 'examples\sample-presentation.pdf') -Destination $examples -Force
        MakeShortcut 'Metaverse 실행' ''
        MakeShortcut 'Metaverse 서버 종료' '--stop'
        Write-Host "준비 완료: $url" -ForegroundColor Green
        Write-Host "예시 파일: $examples\sample-presentation.pdf"
        Write-Host '화면에서 회원가입 후 예시 파일을 업로드하세요. 기존 PC 데이터는 포함하지 않았습니다.'
        Write-Host '창을 닫아도 앱 서버는 유지됩니다. 종료하려면 바탕화면의 Metaverse 서버 종료를 실행하세요.'
        if (-not $NoBrowser) { Start-Process $appUrl }
    }
} catch {
    if ($_.Exception.Data['RestartRequired']) {
        $exitCode = 3010
        Write-Host "`n재부팅 대기: $($_.Exception.Message)" -ForegroundColor Yellow
    } else {
        $exitCode = 1
        Write-Host "`n실패 단계: $script:stage" -ForegroundColor Red
        Write-Host "준비 중단: $($_.Exception.Message)" -ForegroundColor Red
        if ($script:stage -like '[[]5/7]*' -or $script:stage -like '[[]6/7]*') {
            Write-Host '이 단계의 실패 때문에 Windows를 재부팅할 필요는 없습니다. 다운로드 연결, Docker의 메모리/디스크 여유, 아래 서비스 로그를 확인하세요.'
        }
        SaveDiagnostics
    }
    Write-Host '완료된 설치와 저장 데이터는 유지됩니다. 문제 해결 후 같은 EXE를 다시 실행하세요.'
    Write-Host "진단 로그: $logFile"
} finally {
    Stop-Transcript | Out-Null
    if (-not $CheckOnly -and -not $NoBrowser) { Read-Host 'Enter 키를 누르면 창이 닫힙니다' | Out-Null }
}
exit $exitCode
