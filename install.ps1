# FlowlyStack installer for Windows (Windows PowerShell 5.1 or newer). Mirrors install.sh step for step.
# It installs nothing on your computer except Docker containers and one folder.
#
#   Run it in two steps (you can read the file in between):
#       irm https://raw.githubusercontent.com/cent822/flowlystack/main/install.ps1 -OutFile install.ps1
#       powershell -ExecutionPolicy Bypass -File .\install.ps1
#   or in one line (add options after the closing bracket, for example -Port 8373):
#       & ([scriptblock]::Create((irm https://raw.githubusercontent.com/cent822/flowlystack/main/install.ps1)))
#
# What it does: checks that Docker works, makes an install folder (default %USERPROFILE%\flowlystack) with your prompts folder
# inside, writes a small .env (port, time zone, the Claude Code / Codex folders it finds), fetches docker-compose.yml, starts the
# app and prints the address. It never asks questions, never needs administrator rights, never deletes anything, and is safe to
# run again. It only checks that your Claude Code and Codex folders exist; it never opens what is inside them.
#
# Optional, only when you ask: -SetupCapture adds the prompt-capture hook to ~\.claude\settings.json after showing you the exact
# change and asking for a typed "yes" (a backup is made first); -UndoCapture takes that hook out again.
#
# Windows has had limited testing so far (see the FlowlyStack docs). Needs Docker Desktop (WSL 2 backend).

[CmdletBinding()]
param(
    [string]$Dir = '',
    [string]$Port = '8372',
    [string]$Version = 'latest',
    [switch]$NoStart,
    [switch]$DryRun,
    [switch]$SetupCapture,
    [switch]$UndoCapture,
    [switch]$Yes,
    [switch]$Help
)

# Everything runs from Main, called on the last line, so a download cut short can never run half a script.
function Main {
    $ErrorActionPreference = 'Continue'   # native programs (docker) write progress to stderr; PowerShell 5.1 would stop on that with 'Stop'
    $ProgressPreference = 'SilentlyContinue'
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

    $Repo = 'cent822/flowlystack'
    $script:ExitCode = 0
    $script:WorkDir = ''
    $versionGiven = $script:VersionGiven
    # Hidden settings, for tests and second installs: FLOWLYSTACK_RAW_BASE, FLOWLYSTACK_IMAGE, FLOWLYSTACK_PROJECT,
    # FLOWLYSTACK_CONTAINER, FLOWLYSTACK_NO_PULL=1, FLOWLYSTACK_TTY, CLAUDE_SETTINGS.
    $project = $env:FLOWLYSTACK_PROJECT
    $name = 'flowlystack-app'
    if ($env:FLOWLYSTACK_CONTAINER) { $name = $env:FLOWLYSTACK_CONTAINER }
    $settings = Join-Path (Join-Path $HOME '.claude') 'settings.json'
    if ($env:CLAUDE_SETTINGS) { $settings = $env:CLAUDE_SETTINGS }
    $utf8 = New-Object System.Text.UTF8Encoding($false)   # .env and compose must not start with a byte-order mark

    function Say([string]$m) { Write-Host $m }
    function Note([string]$m) { Write-Host "  $m" }
    function Warn([string]$m) { Write-Host "Note: $m" -ForegroundColor Yellow }
    function Stop-Install([string]$m) { Write-Host "Error: $m" -ForegroundColor Red; $script:ExitCode = 1; throw 'FLOWLYSTACK_STOP' }

    function Show-Usage {
        Say 'FlowlyStack installer (Windows)'
        Say ''
        Say '  .\install.ps1 [options]'
        Say ''
        Say '  -Dir <path>      install folder (default: %USERPROFILE%\flowlystack)'
        Say '  -Port <number>   port on this computer (default: 8372)'
        Say '  -Version <tag>   FlowlyStack version, for example 0.1.0 (default: latest)'
        Say '  -NoStart         write the files but do not pull or start anything'
        Say '  -DryRun          show what would happen and write nothing'
        Say '  -SetupCapture    add the prompt-capture hook to ~\.claude\settings.json (shows the change, asks for "yes", makes a backup)'
        Say '  -UndoCapture     take that hook out of ~\.claude\settings.json again'
        Say '  -Yes             answer "yes" to the one capture question (for scripts)'
        Say '  -Help            this text'
        Say ''
        Say 'Needs Docker Desktop (WSL 2 backend) with the compose plugin.'
    }

    # Runs a program, returns its exit code and output (stderr merged), without PowerShell 5.1 turning stderr into errors.
    function Invoke-Native([string]$Exe, [string[]]$CmdArgs) {
        $r = @{ Code = 1; Out = @() }
        try {
            $r.Out = @(& $Exe @CmdArgs 2>&1 | ForEach-Object { "$_" })
            $r.Code = $LASTEXITCODE
        } catch { $r.Out = @("$_"); $r.Code = 1 }
        return $r
    }

    function Write-Utf8([string]$Path, [string]$Text) { [System.IO.File]::WriteAllText($Path, $Text, $utf8) }

    function Test-Name { if ($name -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]*$') { Stop-Install "the container name '$name' is not valid (letters, digits, _ . - only, starting with a letter or digit)." } }

    function Compose([string[]]$More) {
        $a = @('compose', '--project-directory', $Dir)
        if ($project) { $a += @('-p', $project) }
        $a += $More
        & docker @a | Out-Host   # Out-Host keeps docker's own output out of the function's return value
        $code = $LASTEXITCODE
        return $code
    }

    function Get-EnvValue([string]$Key) {
        $f = Join-Path $Dir '.env'
        if (-not (Test-Path $f)) { return '' }
        $v = ''
        foreach ($l in (Get-Content $f)) { if ($l -match ('^' + [regex]::Escape($Key) + '=(.*)$')) { $v = $Matches[1].Trim('"') } }
        return $v
    }

    function EnvQuote([string]$v) { if ($v -match '^[A-Za-z0-9._/:@+=,-]*$') { return $v } else { return '"' + $v + '"' } }
    function ToSlash([string]$p) { return ($p -replace '\\', '/') }

    function Remove-Work { if ($script:WorkDir -and (Test-Path $script:WorkDir)) { Remove-Item -Recurse -Force $script:WorkDir -ErrorAction SilentlyContinue }; $script:WorkDir = '' }

    function Get-Fetch([string]$Url, [string]$Dest) {   # to a temp name first, so a failed download never leaves a broken file
        $tmp = "$Dest.part"
        try {
            if ($Url.StartsWith('file://')) { Copy-Item ([System.Uri]$Url).LocalPath $tmp -Force -ErrorAction Stop }
            else { Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $tmp -ErrorAction Stop }
            Move-Item -Force $tmp $Dest
            return $true
        } catch { if (Test-Path $tmp) { Remove-Item -Force $tmp -ErrorAction SilentlyContinue }; return $false }
    }

    function Get-TimeZoneName {
        if ($env:TZ) { return $env:TZ }
        $id = ''
        try { $id = [System.TimeZoneInfo]::Local.Id } catch { }
        if ($id -match '/' -or $id -eq 'UTC') { return $id }   # already an IANA name (PowerShell on Linux or Mac)
        $map = @{
            'Pacific Standard Time' = 'America/Los_Angeles'; 'Mountain Standard Time' = 'America/Denver'; 'US Mountain Standard Time' = 'America/Phoenix'
            'Central Standard Time' = 'America/Chicago'; 'Eastern Standard Time' = 'America/New_York'; 'Atlantic Standard Time' = 'America/Halifax'
            'Alaskan Standard Time' = 'America/Anchorage'; 'Hawaiian Standard Time' = 'Pacific/Honolulu'; 'Canada Central Standard Time' = 'America/Regina'
            'Central Standard Time (Mexico)' = 'America/Mexico_City'; 'E. South America Standard Time' = 'America/Sao_Paulo'
            'Argentina Standard Time' = 'America/Argentina/Buenos_Aires'; 'GMT Standard Time' = 'Europe/London'; 'Greenwich Standard Time' = 'Atlantic/Reykjavik'
            'W. Europe Standard Time' = 'Europe/Berlin'; 'Central Europe Standard Time' = 'Europe/Budapest'; 'Romance Standard Time' = 'Europe/Paris'
            'Central European Standard Time' = 'Europe/Warsaw'; 'GTB Standard Time' = 'Europe/Bucharest'; 'FLE Standard Time' = 'Europe/Kiev'
            'E. Europe Standard Time' = 'Europe/Chisinau'; 'Russian Standard Time' = 'Europe/Moscow'; 'Turkey Standard Time' = 'Europe/Istanbul'
            'Israel Standard Time' = 'Asia/Jerusalem'; 'Egypt Standard Time' = 'Africa/Cairo'; 'South Africa Standard Time' = 'Africa/Johannesburg'
            'W. Central Africa Standard Time' = 'Africa/Lagos'; 'Arab Standard Time' = 'Asia/Riyadh'; 'Arabian Standard Time' = 'Asia/Dubai'
            'Iran Standard Time' = 'Asia/Tehran'; 'Pakistan Standard Time' = 'Asia/Karachi'; 'India Standard Time' = 'Asia/Kolkata'
            'Bangladesh Standard Time' = 'Asia/Dhaka'; 'Myanmar Standard Time' = 'Asia/Yangon'; 'SE Asia Standard Time' = 'Asia/Bangkok'
            'China Standard Time' = 'Asia/Shanghai'; 'Taipei Standard Time' = 'Asia/Taipei'; 'Singapore Standard Time' = 'Asia/Singapore'
            'Malay Peninsula Standard Time' = 'Asia/Kuala_Lumpur'; 'W. Australia Standard Time' = 'Australia/Perth'; 'Tokyo Standard Time' = 'Asia/Tokyo'
            'Korea Standard Time' = 'Asia/Seoul'; 'AUS Eastern Standard Time' = 'Australia/Sydney'; 'E. Australia Standard Time' = 'Australia/Brisbane'
            'New Zealand Standard Time' = 'Pacific/Auckland'; 'UTC' = 'UTC'
        }
        if ($id -and $map.ContainsKey($id)) { return $map[$id] }
        return ''
    }

    function Get-RealPath([string]$p) { try { return [System.IO.Path]::GetFullPath($p).TrimEnd('\', '/') } catch { return $p } }

    function Get-HookCommand([string]$Script) {
        # the same command as on Mac and Linux: Claude Code on Windows runs hooks in Git Bash (not tested here)
        return "docker exec -i $name /usr/local/bin/entrypoint.sh python hooks/$Script >/dev/null 2>&1 || true"
    }

    function Confirm-Yes([string]$Question) {   # a typed "yes"; works also when started with the one-line form
        if ($Yes) { return $true }
        $ans = ''
        if ($env:FLOWLYSTACK_TTY) {
            if (Test-Path $env:FLOWLYSTACK_TTY) { $ans = [string](Get-Content $env:FLOWLYSTACK_TTY -TotalCount 1) }
            else { Say 'No terminal to ask on. Run it again from a terminal, or add -Yes.'; return $false }
        } elseif ([Console]::IsInputRedirected) {
            Say 'No terminal to ask on. Run it again from a terminal, or add -Yes.'; return $false
        } else { $ans = Read-Host $Question }
        return ($ans -eq 'yes')
    }

    function Invoke-MergeHook([string]$Action, [string]$Work) {   # runs the merge helper from the app's image on a copy of the settings file
        $i = Invoke-Native 'docker' @('inspect', '-f', '{{.Config.Image}}', $name)
        $img = ''
        if ($i.Code -eq 0 -and $i.Out.Count -gt 0) { $img = $i.Out[0].Trim() }
        if (-not $img) { Stop-Install "the FlowlyStack container ($name) is not running. Start it first (run this installer without -SetupCapture)." }
        $r = Invoke-Native 'docker' @('run', '--rm', '--entrypoint', 'python', '-v', "${Work}:/w", $img, '/app/docker/merge_hooks.py', $Action, '/w/settings.json', (Get-HookCommand 'capture_prompt.py'))
        if ($r.Code -ne 0) { return $null }
        return ($r.Out | Where-Object { $_ } | Select-Object -Last 1).Trim()
    }

    function Invoke-Capture([string]$Action) {
        if ($DryRun) {
            if ($Action -eq 'add') { Say "Would add the capture hook to $settings (after showing the change, asking for ""yes"" and making a backup)." }
            else { Say "Would take the capture hook out of $settings (after showing the change and asking for ""yes"")." }
            return
        }
        $script:WorkDir = Join-Path ([System.IO.Path]::GetTempPath()) ('flowlystack.' + [guid]::NewGuid().ToString('N').Substring(0, 8))
        New-Item -ItemType Directory -Force $script:WorkDir | Out-Null
        $work = $script:WorkDir
        $copy = Join-Path $work 'settings.json'
        $exists = Test-Path $settings
        if ($exists) { Copy-Item $settings $copy }
        $status = Invoke-MergeHook $Action $work
        if (-not $status) { Remove-Work; Stop-Install "could not prepare the change (is $settings valid JSON? nothing was changed)." }
        if ($status -eq 'already') { Say "The capture hook is already in $settings. Nothing to do."; Remove-Work; return }
        if ($status -eq 'absent') { Say "The capture hook is not in $settings. Nothing to do."; Remove-Work; return }
        Say "This is the change to ${settings}:"
        if ($exists) {
            $old = @(Get-Content $settings); $new = @(Get-Content $copy)
            foreach ($d in (Compare-Object $old $new)) {
                if ($d.SideIndicator -eq '<=') { Say "- $($d.InputObject)" } else { Say "+ $($d.InputObject)" }
            }
        } else {
            Say '(the file does not exist yet; it would be created with this content)'
            Say (Get-Content $copy -Raw)
        }
        Say ''
        if (-not (Confirm-Yes 'Type yes to apply it (anything else cancels):')) { Say 'Cancelled. Nothing was changed.'; Remove-Work; return }
        if ($exists) {
            $backup = "$settings.flowlystack-backup-" + (Get-Date -Format 'yyyyMMdd-HHmmss')
            Copy-Item $settings $backup
            Say "Backup saved: $backup"
        } else {
            New-Item -ItemType Directory -Force (Split-Path -Parent $settings) | Out-Null
        }
        Copy-Item $copy "$settings.flowlystack-tmp" -Force
        Move-Item -Force "$settings.flowlystack-tmp" $settings
        Remove-Work
        if ($Action -eq 'add') {
            Say "Done. Claude Code now saves each prompt you send into $Dir\prompts (while FlowlyStack is running)."
            Note "Undo: powershell -ExecutionPolicy Bypass -File ""$Dir\install.ps1"" -UndoCapture   (it removes exactly this hook and leaves your other settings alone)"
            Note 'This assumes Claude Code runs hooks in Git Bash, as it does by default on Windows. If no prompts show up, tell us on the project page.'
        } else {
            Say 'Done. The capture hook is removed.'
        }
    }

    try {
        if ($Help) { Show-Usage; return }
        if ($Port -notmatch '^[0-9]+$') { Stop-Install '-Port must be a number' }
        if ($Version -notmatch '^[A-Za-z0-9._-]+$') { Stop-Install '-Version must be a tag such as 0.1.0 or latest' }
        if ($SetupCapture -and $UndoCapture) { Stop-Install 'use -SetupCapture or -UndoCapture, not both' }
        if (-not $Dir) { $Dir = Join-Path $HOME 'flowlystack' }
        if ($Dir -eq '~' -or $Dir.StartsWith('~\') -or $Dir.StartsWith('~/')) { $Dir = $HOME + $Dir.Substring(1) }
        $realDir = Get-RealPath $Dir
        $rootOfDir = ''
        try { $rootOfDir = [System.IO.Path]::GetPathRoot($realDir).TrimEnd('\', '/') } catch { }
        if (($realDir -ieq (Get-RealPath $HOME)) -or ($realDir -ieq $rootOfDir) -or (-not $realDir)) {
            Stop-Install '-Dir must be a folder of its own (for example %USERPROFILE%\flowlystack), not your home folder or a drive root: the installer writes .env and docker-compose.yml into it.'
        }
        $Dir = $realDir
        Test-Name

        # ---- 1. docker ----
        $dockerOk = $true
        if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
            Say 'Docker is not installed.'
            Note 'Install Docker Desktop from https://www.docker.com/products/docker-desktop/ , then run this again.'
            $dockerOk = $false
        } elseif ((Invoke-Native 'docker' @('compose', 'version')).Code -ne 0) {
            Say "Docker is installed but the compose plugin is missing (the 'docker compose' command)."
            Note 'Docker Desktop includes it. Update Docker Desktop, then run this again.'
            $dockerOk = $false
        } elseif ((Invoke-Native 'docker' @('info')).Code -ne 0) {
            Say 'Docker is installed but not answering.'
            Note 'Start Docker Desktop and wait until it says it is running.'
            $dockerOk = $false
        }
        if (-not $dockerOk) {
            if ($DryRun) { Warn 'Docker is not ready; a real run would stop here.' } else { $script:ExitCode = 1; return }
        }

        if (-not $env:FLOWLYSTACK_CONTAINER) { $fromEnv = Get-EnvValue 'FLOWLYSTACK_CONTAINER'; if ($fromEnv) { $name = $fromEnv; Test-Name } }

        if ($UndoCapture) { Invoke-Capture 'remove'; return }

        # ---- what to install ----
        $ref = 'main'
        if ($Version -ne 'latest') { $ref = 'v' + $Version.TrimStart('v') }
        $rawBase = "https://raw.githubusercontent.com/$Repo/$ref"
        if ($env:FLOWLYSTACK_RAW_BASE) { $rawBase = $env:FLOWLYSTACK_RAW_BASE }
        $image = "ghcr.io/${Repo}:" + $Version.TrimStart('v')
        if ($env:FLOWLYSTACK_IMAGE) { $image = $env:FLOWLYSTACK_IMAGE }

        $claudeDir = Join-Path (Join-Path $HOME '.claude') 'projects'
        $codexBase = Join-Path $HOME '.codex'
        if ($env:CODEX_HOME) { $codexBase = $env:CODEX_HOME }
        $foundClaude = Test-Path $claudeDir -PathType Container
        $foundCodex = Test-Path (Join-Path $codexBase 'sessions') -PathType Container

        if ($SetupCapture -and -not $DryRun) {
            $run = Invoke-Native 'docker' @('inspect', '-f', '{{.State.Running}}', $name)
            if ($run.Code -eq 0 -and $run.Out.Count -gt 0 -and $run.Out[0].Trim() -eq 'true') { Invoke-Capture 'add'; return }
        }

        Say 'FlowlyStack installer'
        Note "install folder: $Dir"
        Note "address:        http://127.0.0.1:$Port"
        Note "version:        $Version"
        if ($DryRun) { Note '(dry run: nothing will be written or started)' }

        # ---- 2. folders ----
        if ($DryRun) { Note "would create: $Dir, $Dir\prompts, $Dir\empty" }
        else {
            New-Item -ItemType Directory -Force (Join-Path $Dir 'prompts') | Out-Null
            New-Item -ItemType Directory -Force (Join-Path $Dir 'empty') | Out-Null
        }

        # ---- 3. .env ----
        $tz = Get-TimeZoneName
        $tzNote = ''
        if (-not $tz) { $tz = 'UTC'; $tzNote = "time zone not detected, using UTC: set TZ in $Dir\.env (for example Europe/London)" }

        $envLines = @(
            '# Written by the FlowlyStack installer. Edit freely; the installer never overwrites this file.',
            "FLOWLYSTACK_IMAGE=$(EnvQuote $image)",
            "FLOWLYSTACK_PORT=$Port",
            "TZ=$(EnvQuote $tz)"
        )
        if ($name -ne 'flowlystack-app') { $envLines += "FLOWLYSTACK_CONTAINER=$(EnvQuote $name)" }
        if ($foundCodex) { $envLines += 'FLOWLYSTACK_SOURCES=claude,codex' } else { $envLines += 'FLOWLYSTACK_SOURCES=claude' }
        if ($foundClaude) { $envLines += "CLAUDE_PROJECTS_DIR=$(EnvQuote (ToSlash $claudeDir))" }
        if ($foundCodex) {
            $envLines += "CODEX_SESSIONS_DIR=$(EnvQuote (ToSlash (Join-Path $codexBase 'sessions')))"
            $archived = Join-Path $codexBase 'archived_sessions'
            if (Test-Path $archived -PathType Container) { $envLines += "CODEX_ARCHIVED_DIR=$(EnvQuote (ToSlash $archived))" }
        }

        $envFile = Join-Path $Dir '.env'
        if (Test-Path $envFile) {
            Say "Kept your existing $envFile (the installer never overwrites it)."
            $p = Get-EnvValue 'FLOWLYSTACK_PORT'; if ($p) { $Port = $p } else { $Port = '8372' }
            $c = Get-EnvValue 'FLOWLYSTACK_CONTAINER'; if ($c) { $name = $c; Test-Name }
            $oldImage = Get-EnvValue 'FLOWLYSTACK_IMAGE'
            if ($versionGiven -and $oldImage -and $oldImage -ne $image) {
                Note "Your .env uses the image $oldImage, but -Version asks for $image. The installer never edits your .env: change FLOWLYSTACK_IMAGE there to switch."
            }
        } elseif ($DryRun) {
            Say "Would write ${envFile}:"
            foreach ($l in $envLines) { Say "    $l" }
        } else {
            Write-Utf8 $envFile (($envLines -join "`n") + "`n")
            Say "Wrote $envFile"
        }
        if ($tzNote) { Warn $tzNote }

        # ---- 4. compose file ----
        $composeFile = Join-Path $Dir 'docker-compose.yml'
        if ($DryRun) { Note "would fetch: $rawBase/docker-compose.yml" }
        else {
            $new = "$composeFile.new"
            if (-not (Get-Fetch "$rawBase/docker-compose.yml" $new)) { Stop-Install "could not download $rawBase/docker-compose.yml (check your internet connection and the version)." }
            # the repository file also has a 'build: .' line for developers; an install has no source to build from
            $kept = @(Get-Content $new | Where-Object { $_ -ne '    build: .' })
            Write-Utf8 $new (($kept -join "`n") + "`n")
            if ((Test-Path $composeFile) -and ((Get-Content $composeFile -Raw) -ne (Get-Content $new -Raw))) {
                Copy-Item $composeFile "$composeFile.previous" -Force
                Note 'the compose file changed; the old one is saved as docker-compose.yml.previous'
            }
            Move-Item -Force $new $composeFile
            Say "Wrote $composeFile"
            # a copy of this installer (same version) next to it, so -SetupCapture and -UndoCapture work later
            if (Get-Fetch "$rawBase/install.ps1" (Join-Path $Dir 'install.ps1')) { Note "saved the installer as $Dir\install.ps1" }
            else { Warn 'could not save a copy of the installer (not needed to run FlowlyStack).' }
        }

        # ---- 5. start ----
        if ($DryRun) {
            Note "would also save the installer as $Dir\install.ps1"
            Note 'would run: docker compose pull, then docker compose up -d, then wait for the app to answer'
        } elseif (-not $NoStart) {
            $run = Invoke-Native 'docker' @('inspect', '-f', '{{.State.Running}}', $name)
            $running = ($run.Code -eq 0 -and $run.Out.Count -gt 0 -and $run.Out[0].Trim() -eq 'true')
            if (-not $running) {
                $busy = $false
                try {
                    $tcp = New-Object System.Net.Sockets.TcpClient
                    $iar = $tcp.BeginConnect('127.0.0.1', [int]$Port, $null, $null)
                    if ($iar.AsyncWaitHandle.WaitOne(500) -and $tcp.Connected) { $busy = $true }
                    $tcp.Close()
                } catch { }
                if ($busy) { Stop-Install "port $Port on this computer is already in use. Run again with another port, for example:  .\install.ps1 -Port 8373" }
            }
            if ($env:FLOWLYSTACK_NO_PULL -ne '1') {
                Say 'Downloading the FlowlyStack image (the first time takes a minute or two)...'
                if ((Compose @('pull')) -ne 0) { Stop-Install "could not download the image $image. Check your internet connection. If this version is not published yet, nothing was started." }
            }
            Say 'Starting FlowlyStack...'
            if ((Compose @('up', '-d')) -ne 0) { Stop-Install 'docker compose could not start it (see the message above).' }
            $waited = 0; $state = ''
            while ($waited -lt 90) {
                $s = Invoke-Native 'docker' @('inspect', '-f', '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}', $name)
                if ($s.Code -eq 0 -and $s.Out.Count -gt 0) { $state = $s.Out[0].Trim() }
                if ($state -eq 'healthy' -or $state -eq 'running') { break }
                Start-Sleep -Seconds 2; $waited += 2
            }
            if ($state -ne 'healthy' -and $state -ne 'running') {
                $st = $state; if (-not $st) { $st = 'unknown' }
                Stop-Install "FlowlyStack did not become ready in 90 seconds (state: $st). Look at the log with:  cd ""$Dir""; docker compose logs"
            }
            if ($running) { Note '(it was already running; it has been updated and restarted if a newer image was found)' }
        }

        # ---- 6. summary ----
        $cl = 'not found'; $cx = 'not found'
        if ($foundClaude) { $cl = 'found' }
        if ($foundCodex) { $cx = 'found' }
        Say ''
        Say "Claude Code: $cl. Codex: $cx."
        if ((-not $DryRun) -and (-not $NoStart)) { Say "FlowlyStack is running: open http://127.0.0.1:$Port and create your account (the first visit asks for a username and password)." }
        Note "Your prompts and documents: $Dir\prompts (plain files). Login, settings and caches: a Docker volume."
        Note "Stop:   cd ""$Dir""; docker compose down"
        Note "Update: run this installer again, or  cd ""$Dir""; docker compose pull; docker compose up -d"
        if (-not $foundClaude) { Note "Claude Code folder not found at $claudeDir : the Dashboard starts empty until it exists." }
        if (-not $SetupCapture) { Note "Save every prompt you send in Claude Code: powershell -ExecutionPolicy Bypass -File ""$Dir\install.ps1"" -SetupCapture" }

        # ---- 7. capture (opt-in) ----
        if ($SetupCapture) {
            Say ''
            if ($NoStart) { Warn "capture setup needs the app running; start it, then run:  powershell -ExecutionPolicy Bypass -File ""$Dir\install.ps1"" -SetupCapture" }
            else { Invoke-Capture 'add' }
        }
        if ($foundCodex) {
            Say ''
            Say 'Codex prompts: the installer does not edit Codex files. To capture them, add this to ~\.codex\hooks.json (merge it with any hooks'
            Say 'already there), then run /hooks inside Codex and review and enable it:'
            Say ''
            $cmd = (Get-HookCommand 'capture_codex_prompt.py') -replace '"', '\"'
            Say "  {""hooks"": {""UserPromptSubmit"": [{""hooks"": [{""type"": ""command"", ""command"": ""$cmd""}]}]}}"
        }
    }
    catch {
        if ("$_" -ne 'FLOWLYSTACK_STOP') { Write-Host "Error: $_" -ForegroundColor Red; $script:ExitCode = 1 }
    }
    finally { Remove-Work }
}

$script:VersionGiven = $PSBoundParameters.ContainsKey('Version')
Main
# Run as a file (powershell -File), report the result as the exit code; in the one-line form never close the user's window.
if ($PSCommandPath -and $script:ExitCode -ne 0) { exit $script:ExitCode }
