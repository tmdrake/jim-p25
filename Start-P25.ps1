# Attach the HackRF to Ubuntu and open the jim-p25 page.
# The USB id 1d50:6089 is the public HackRF product id, not this board's serial.
$ErrorActionPreference = "Stop"
$Usbipd = "C:\Program Files\usbipd-win\usbipd.exe"
$Distro = "Ubuntu-24.04"
$HwId = "1d50:6089"
$Port = 8765

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

if (-not (Test-Path $Usbipd)) {
    throw "usbipd is not installed."
}
if (-not (wsl -l -q | Where-Object { $_ -replace "`0","" -eq $Distro })) {
    throw "WSL distro $Distro is not installed."
}

$state = Get-HackRfState
if ($state -eq "missing") {
    throw "Plug in the HackRF One."
}
if ($state -eq "Not shared") {
    Invoke-UsbipdAdmin @("bind", "--hardware-id", $HwId)
    $state = Get-HackRfState
}
if ($state -ne "Attached") {
    try {
        & $Usbipd attach --wsl $Distro --hardware-id $HwId
        if ($LASTEXITCODE -ne 0) { throw "attach exit $LASTEXITCODE" }
    } catch {
        Invoke-UsbipdAdmin @("attach", "--wsl", $Distro, "--hardware-id", $HwId)
    }
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$wslRoot = (wsl -d $Distro -u root -- wslpath -u $root).Trim()
$launch = "export PULSE_SERVER=unix:/mnt/wslg/PulseServer; cd '$wslRoot' && exec python3 -u app/server.py"
Start-Process -FilePath "wsl.exe" -ArgumentList @("-d", $Distro, "-u", "root", "--", "bash", "-lc", $launch) -WindowStyle Normal

$up = $false
for ($i = 0; $i -lt 40; $i++) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $Port)
        $client.Close()
        $up = $true
        break
    } catch {
        Start-Sleep -Milliseconds 250
    }
}
if (-not $up) {
    throw "The page did not open on port $Port."
}
Start-Process "http://127.0.0.1:$Port/"
