# Start, stop, restart, or check the jim-p25 page.
# The USB id 1d50:6089 is the public HackRF product id, not this board's serial.
param(
    [switch]$Status,
    [switch]$Restart,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$Usbipd = "C:\Program Files\usbipd-win\usbipd.exe"
$Distro = "Ubuntu-24.04"
$HwId = "1d50:6089"
$Port = 8765

if (($Status -and $Restart) -or ($Status -and $Stop) -or ($Restart -and $Stop)) {
    throw "Use only one of -Status, -Restart, or -Stop."
}

function Get-WslText {
    return ((wsl -l -v | Out-String) -replace "`0", "")
}

function Get-WslState {
    foreach ($line in (Get-WslText -split "`r?`n")) {
        if ($line -notmatch [regex]::Escape($Distro)) { continue }
        if ($line -match "Running") { return "Running" }
        if ($line -match "Stopped") { return "Stopped" }
    }
    return "missing"
}

function Ensure-Distro {
    if ((Get-WslState) -eq "Running") { return }
    if ((Get-WslState) -eq "missing") { throw "WSL distro $Distro is not installed." }
    # usbipd can attach only while this distro is running.
    Start-Process -FilePath "wsl.exe" -ArgumentList @("-d", $Distro, "-u", "root", "--", "sleep", "infinity") -WindowStyle Hidden
    for ($i = 0; $i -lt 50; $i++) {
        if ((Get-WslState) -eq "Running") { return }
        Start-Sleep -Milliseconds 200
    }
    throw "Ubuntu 24.04 did not start."
}

function Test-PageUp {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $Port)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

function Get-HackRfState {
    $lines = & $Usbipd list
    foreach ($line in $lines) {
        if ($line -notmatch $HwId) { continue }
        if ($line -match "Not shared") { return "Not shared" }
        if ($line -match "Attached") { return "Attached" }
        if ($line -match "Shared") { return "Shared" }
    }
    return "missing"
}

function Invoke-UsbipdAdmin {
    param([string[]]$UsbArgs)
    $proc = Start-Process -FilePath $Usbipd -ArgumentList $UsbArgs -Verb RunAs -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "usbipd $($UsbArgs -join ' ') failed with exit $($proc.ExitCode)."
    }
}

function Stop-Page {
    if ((Get-WslState) -eq "Running") {
        @'
import os, signal
me = os.getpid()
needles = ("app/server.py", "repeater/apps/rx.py", "repeater/apps/tx/dv_tx.py")
for name in os.listdir("/proc"):
    if not name.isdigit():
        continue
    pid = int(name)
    if pid == me:
        continue
    try:
        cmd = open("/proc/%s/cmdline" % name, "rb").read().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        continue
    if any(needle in cmd for needle in needles):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
'@ | wsl -d $Distro -u root -- python3 -
    }
    for ($i = 0; $i -lt 20; $i++) {
        if (-not (Test-PageUp)) { return }
        Start-Sleep -Milliseconds 250
    }
}

function Show-Status {
    $wslState = Get-WslState
    $hack = "unknown"
    if (Test-Path $Usbipd) { $hack = Get-HackRfState }
    Write-Output "Ubuntu: $wslState"
    Write-Output "HackRF: $hack"
    if (Test-PageUp) {
        try {
            $page = Invoke-RestMethod "http://127.0.0.1:$Port/api/status" -TimeoutSec 3
            Write-Output "Page: running at http://127.0.0.1:$Port/ ($($page.mode), HackRF $($page.device))"
        } catch {
            Write-Output "Page: port $Port is open"
        }
    } else {
        Write-Output "Page: stopped"
    }
}

function Start-Page {
    if (-not (Test-Path $Usbipd)) { throw "usbipd is not installed." }
    Ensure-Distro
    $state = Get-HackRfState
    if ($state -eq "missing") { throw "Plug in the HackRF One." }
    if ($state -eq "Not shared") {
        Invoke-UsbipdAdmin @("bind", "--hardware-id", $HwId)
        $state = Get-HackRfState
    }
    if ($state -ne "Attached") {
        Ensure-Distro
        & $Usbipd attach --wsl $Distro --hardware-id $HwId
        if ($LASTEXITCODE -ne 0) {
            Invoke-UsbipdAdmin @("attach", "--wsl", $Distro, "--hardware-id", $HwId)
        }
    }

    $root = $PSScriptRoot
    $wslRoot = (wsl -d $Distro -u root -- wslpath -u $root).Trim()
    $launch = "export PULSE_SERVER=unix:/mnt/wslg/PulseServer; cd '$wslRoot' && exec python3 -u app/server.py"
    Start-Process -FilePath "wsl.exe" -ArgumentList @("-d", $Distro, "-u", "root", "--", "bash", "-lc", $launch) -WindowStyle Normal

    for ($i = 0; $i -lt 40; $i++) {
        if (Test-PageUp) {
            Start-Process "http://127.0.0.1:$Port/"
            Show-Status
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw "The page did not open on port $Port."
}

if ($Status) {
    Show-Status
    return
}
if ($Stop) {
    Stop-Page
    Show-Status
    return
}
if ($Restart) {
    Stop-Page
}
if ((Test-PageUp) -and -not $Restart) {
    Start-Process "http://127.0.0.1:$Port/"
    Show-Status
    return
}
Start-Page
