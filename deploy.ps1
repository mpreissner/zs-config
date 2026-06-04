# deploy.ps1 - Pull, build, and deploy zs-config on a Windows Docker host.
#
# Works in two modes:
#   1. Standalone (fresh machine) - run the script directly; it will clone
#      the repo into .\zs-config next to the script, then deploy from there.
#   2. Inside the repo - run from an existing clone; it will pull and redeploy.
#
# Usage:
#   .\deploy.ps1 [branch]
#
# Single-command deploy on a fresh machine (run in PowerShell as Administrator):
#   Invoke-WebRequest -Uri https://raw.githubusercontent.com/mpreissner/zs-config/main/deploy.ps1 -OutFile deploy.ps1; .\deploy.ps1

param(
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/mpreissner/zs-config.git"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# -- Windows Server detection and Hyper-V provisioning -------------------------

function Test-IsWindowsServer {
    $caption = (Get-WmiObject Win32_OperatingSystem).Caption
    return ($caption -match "Windows Server")
}

function Ensure-AdminPrivileges {
    $id  = [Security.Principal.WindowsIdentity]::GetCurrent()
    $pri = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $pri.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Error "ERROR: This script must be run as Administrator."
        exit 1
    }
}

function Ensure-OpenSshClient {
    $cap = Get-WindowsCapability -Online -Name "OpenSSH.Client~~~~0.0.1.0" `
               -ErrorAction SilentlyContinue
    if ($cap -and $cap.State -ne "Installed") {
        Write-Host "Installing OpenSSH Client..."
        Add-WindowsCapability -Online -Name "OpenSSH.Client~~~~0.0.1.0" | Out-Null
    }
}

function Ensure-HyperV {
    $hv = Get-WindowsFeature -Name Hyper-V
    if ($hv.Installed -eq $true) { return }

    Write-Host "Installing Hyper-V (this may take a few minutes)..."
    $result = Install-WindowsFeature -Name Hyper-V -IncludeManagementTools -Restart:$false

    if ($result.ExitCode -eq "SuccessRestartRequired" -or $result.RestartNeeded -eq "Yes") {
        Write-Host ""
        Write-Host "Hyper-V has been installed. A system restart is required before provisioning"
        Write-Host "the Linux VM."
        Write-Host ""
        Write-Host "After restarting, re-run this script:"
        Write-Host "    .\deploy.ps1 $Branch"
        Write-Host ""
        Write-Host "The script will detect that Hyper-V is already installed and continue"
        Write-Host "automatically."
        exit 0
    }
}

function Ensure-SshKey {
    $KeyDir  = Join-Path $env:APPDATA "zs-config\vm"
    $KeyFile = Join-Path $KeyDir "id_ed25519"
    $PubFile = Join-Path $KeyDir "id_ed25519.pub"

    if (Test-Path $KeyFile) {
        return (Get-Content $PubFile -Raw).Trim()
    }

    New-Item -ItemType Directory -Force -Path $KeyDir | Out-Null
    & ssh-keygen -t ed25519 -N '""' -f $KeyFile -C "zs-config-deploy"
    if ($LASTEXITCODE -ne 0) {
        throw "ssh-keygen failed with exit code $LASTEXITCODE"
    }
    return (Get-Content $PubFile -Raw).Trim()
}

function New-SeedDisk {
    param([string]$SshPublicKey)
    # Use a FAT-VHD (SCSI disk) instead of a DVD-backed ISO.
    # Hyper-V presents SCSI disks reliably; DVD drives (/dev/sr0) have a
    # "Can't lookup blockdev" error at early boot on some Hyper-V setups
    # that prevents cloud-init from reading the cidata label off the ISO.

    $KeyDir  = Join-Path $env:APPDATA "zs-config\vm"
    $SeedVhd = Join-Path $KeyDir "seed.vhdx"

    $MetaData = "instance-id: zs-config-host-01`nlocal-hostname: zs-config-host"

    $UserData = "#cloud-config`n" +
        "users:`n" +
        "  - name: zsadmin`n" +
        "    groups: sudo`n" +
        "    shell: /bin/bash`n" +
        "    sudo: ALL=(ALL) NOPASSWD:ALL`n" +
        "    ssh_authorized_keys:`n" +
        "      - $SshPublicKey`n" +
        "`n" +
        "bootcmd:`n" +
        "  - systemctl enable --now ssh`n" +
        "`n" +
        "package_update: true`n" +
        "package_upgrade: false`n" +
        "packages:`n" +
        "  - docker.io`n" +
        "  - docker-compose-v2`n" +
        "  - openssh-server`n" +
        "  - curl`n" +
        "  - git`n" +
        "`n" +
        "runcmd:`n" +
        "  - systemctl enable --now docker`n" +
        "  - usermod -aG docker zsadmin`n" +
        "  - systemctl enable --now ssh"

    New-Item -ItemType Directory -Force -Path $KeyDir | Out-Null
    if (Test-Path $SeedVhd) { Remove-Item $SeedVhd -Force }
    New-VHD -Path $SeedVhd -SizeBytes 5MB -Fixed | Out-Null
    $disk = Mount-VHD -Path $SeedVhd -PassThru | Get-Disk
    Initialize-Disk -Number $disk.Number -PartitionStyle MBR
    $part = New-Partition -DiskNumber $disk.Number -UseMaximumSize -AssignDriveLetter
    Format-Volume -DriveLetter $part.DriveLetter -FileSystem FAT -NewFileSystemLabel "cidata" -Force | Out-Null
    $drive = "$($part.DriveLetter):"
    [System.IO.File]::WriteAllText("$drive\meta-data", $MetaData, [System.Text.Encoding]::ASCII)
    [System.IO.File]::WriteAllText("$drive\user-data", $UserData,  [System.Text.Encoding]::ASCII)
    Dismount-VHD -Path $SeedVhd
    Write-Host "Cloud-init seed disk created."
    return $SeedVhd
}

function Ensure-VmSwitch {
    # Windows 10/11 creates this automatically; Windows Server does not.
    $sw = Get-VMSwitch -Name "Default Switch" -ErrorAction SilentlyContinue
    if ($sw) { return "Default Switch" }

    # Reuse any existing external switch.
    $sw = Get-VMSwitch -SwitchType External -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($sw) { Write-Host "Using existing VM switch: $($sw.Name)"; return $sw.Name }

    # Create an external switch on the first connected physical NIC.
    $nic = Get-NetAdapter | Where-Object { $_.Status -eq "Up" -and $_.Virtual -eq $false } |
           Select-Object -First 1
    if (-not $nic) { throw "No connected physical network adapter found to create a VM switch." }

    Write-Host "Creating external VM switch on adapter '$($nic.Name)'..."
    New-VMSwitch -Name "zs-config-external" -NetAdapterName $nic.Name -AllowManagementOS $true | Out-Null
    return "zs-config-external"
}

function Remove-StaleVm {
    $vm = Get-VM -Name "zs-config-host" -ErrorAction SilentlyContinue
    if (-not $vm) { return }
    Write-Host "Removing stale VM 'zs-config-host'..."
    if ($vm.State -eq "Running") { Stop-VM -Name "zs-config-host" -TurnOff -Force }
    Remove-VM -Name "zs-config-host" -Force
}

function Fix-CloudInitDatasource {
    param([string]$OsDisk)
    # The Ubuntu Azure cloud image ships with datasource_list: [Azure] only.
    # On non-Azure Hyper-V cloud-init never finds our seed disk.
    # Fix: patch the ESP's grub.cfg to pass ds=nocloud on the kernel command line,
    # which forces cloud-init to use NoCloud regardless of the image's datasource_list.
    Write-Host "Patching GRUB to force NoCloud datasource (ds=nocloud)..."

    $diskNum    = $null
    $espPartNum = $null
    $tmpLetter  = $null

    try {
        $vhdDisk = Mount-VHD -Path $OsDisk -PassThru
        $diskNum = $vhdDisk.DiskNumber
        Start-Sleep -Seconds 2

        $parts   = Get-Partition -DiskNumber $diskNum -ErrorAction Stop
        $EspGuid = "{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}"

        # Match by GPT type GUID or by the "System" type string (both are set on ESP).
        $espPart = $parts | Where-Object {
            $_.GptType -eq $EspGuid -or $_.Type -eq "System"
        } | Select-Object -First 1
        if (-not $espPart) {
            Write-Host "Warning: EFI System Partition not found; skipping GRUB patch."
            return
        }

        $used      = (Get-PSDrive -PSProvider FileSystem).Name
        $available = [char[]](70..90) | Where-Object { ([string]$_) -notin $used }
        if (-not $available) {
            Write-Host "Warning: No free drive letters; skipping GRUB patch."
            return
        }
        $tmpLetter  = [char]$available[0]
        $espPartNum = $espPart.PartitionNumber
        Set-Partition -DiskNumber $diskNum -PartitionNumber $espPartNum -NewDriveLetter $tmpLetter
        Start-Sleep -Seconds 1
        $espDrive = "${tmpLetter}:"

        $grubDir = Join-Path $espDrive "EFI\ubuntu"
        if (-not (Test-Path $grubDir)) {
            Write-Host "Warning: EFI\ubuntu not found on ESP; skipping GRUB patch."
            return
        }

        $grubCfgPath = Join-Path $grubDir "grub.cfg"

        # Read existing grub.cfg to extract the ext4 filesystem UUID so we can
        # continue to use search.fs_uuid (built into GRUB core, no insmod needed).
        $existing = Get-Content $grubCfgPath -Raw -ErrorAction SilentlyContinue
        $fsUuid   = $null
        if ($existing -match 'search\.fs_uuid\s+([0-9a-fA-F-]+)\s+root') {
            $fsUuid = $Matches[1].ToLower()
        }

        if ($fsUuid) {
            $searchLine = "search.fs_uuid $fsUuid root"
            $rootSpec   = "root=UUID=$fsUuid"
        } else {
            # Fallback: use GPT partition entry GUID (PARTUUID) of the largest non-system partition.
            $MsrGuid  = "{e3c9e316-0b5c-4db8-817d-f92df00215ae}"
            $rootPart = $parts |
                        Where-Object { $_.GptType -ne $EspGuid -and $_.GptType -ne $MsrGuid } |
                        Sort-Object Size -Descending | Select-Object -First 1
            if (-not $rootPart -or -not $rootPart.Guid) {
                Write-Host "Warning: Could not determine root partition identifier; skipping GRUB patch."
                return
            }
            $rootPartuuid = $rootPart.Guid.TrimStart('{').TrimEnd('}').ToLower()
            $searchLine   = "search --no-floppy --part-uuid --set=root $rootPartuuid"
            $rootSpec     = "root=PARTUUID=$rootPartuuid"
        }

        $grubCfg = "$searchLine`n" +
                   "linux (`$root)/boot/vmlinuz $rootSpec ro quiet ds=nocloud`n" +
                   "initrd (`$root)/boot/initrd.img`n" +
                   "boot"

        [System.IO.File]::WriteAllText($grubCfgPath, $grubCfg, [System.Text.Encoding]::ASCII)
        Write-Host "GRUB patched: kernel will boot with ds=nocloud."

    } catch {
        Write-Host "Warning: GRUB patch failed: $_"
    } finally {
        if ($null -ne $diskNum -and $null -ne $espPartNum -and $null -ne $tmpLetter) {
            Remove-PartitionAccessPath -DiskNumber $diskNum -PartitionNumber $espPartNum `
                -AccessPath "${tmpLetter}:\" -ErrorAction SilentlyContinue
        }
        Dismount-VHD -Path $OsDisk -ErrorAction SilentlyContinue
    }
}

function Ensure-VM {
    param([string]$SshPublicKey)

    $vm = Get-VM -Name "zs-config-host" -ErrorAction SilentlyContinue
    if ($vm) {
        if ($vm.State -eq "Running") {
            Write-Host "VM 'zs-config-host' is already running. Skipping provisioning."
            return
        }
        Write-Host "VM 'zs-config-host' exists but is not running (state: $($vm.State)). Re-provisioning..."
        Remove-StaleVm
    }

    $ImageUrl  = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64-azure.vhd.tar.gz"
    $ExtractDir = Join-Path $env:TEMP "ubuntu-2404-extract"
    $tgz        = Join-Path $env:TEMP "ubuntu-2404-cloud.tar.gz"
    $vhdx       = Join-Path $env:TEMP "ubuntu-2404-cloud.vhdx"

    New-Item -ItemType Directory -Force -Path $ExtractDir | Out-Null

    Write-Host "Downloading Ubuntu 24.04 cloud image (this may take several minutes)..."
    Invoke-WebRequest -Uri $ImageUrl -OutFile $tgz -UseBasicParsing

    Write-Host "Extracting VHD from archive..."
    & tar -xzf $tgz -C $ExtractDir
    if ($LASTEXITCODE -ne 0) { throw "Failed to extract cloud image archive." }

    $vhd = Get-ChildItem -Path $ExtractDir -Filter "*.vhd" -Recurse |
           Select-Object -First 1 -ExpandProperty FullName
    if (-not $vhd) { throw "Could not find .vhd file after extraction." }
    Write-Host "Found: $vhd"

    Write-Host "Clearing sparse flag on VHD (required for Convert-VHD)..."
    & fsutil sparse setflag $vhd 0

    Write-Host "Converting VHD to VHDX..."
    Convert-VHD -Path $vhd -DestinationPath $vhdx -VHDType Dynamic

    $VmDiskDir = "C:\HyperV\VMs\zs-config-host"
    New-Item -ItemType Directory -Force -Path $VmDiskDir | Out-Null
    $OsDisk = Join-Path $VmDiskDir "os.vhdx"
    Write-Host "Copying VHDX to $OsDisk..."
    Copy-Item $vhdx $OsDisk -Force
    Resize-VHD -Path $OsDisk -SizeBytes 42949672960
    Fix-CloudInitDatasource -OsDisk $OsDisk

    Remove-Item $tgz, $vhdx -ErrorAction SilentlyContinue
    Remove-Item $ExtractDir -Recurse -Force -ErrorAction SilentlyContinue

    Write-Host "Building cloud-init seed disk..."
    $SeedDisk = New-SeedDisk -SshPublicKey $SshPublicKey

    $SwitchName = Ensure-VmSwitch

    Write-Host "Creating VM 'zs-config-host'..."
    $vm = New-VM -Name "zs-config-host" `
                 -Generation 2 `
                 -MemoryStartupBytes 2GB `
                 -VHDPath $OsDisk `
                 -SwitchName $SwitchName

    Set-VMProcessor -VMName "zs-config-host" -Count 2
    Set-VMMemory    -VMName "zs-config-host" -DynamicMemoryEnabled $true `
                    -MinimumBytes 512MB -MaximumBytes 4GB

    Set-VMFirmware  -VMName "zs-config-host" -EnableSecureBoot Off

    Set-VM -VMName "zs-config-host" -CheckpointType Disabled

    # Attach seed disk as a SCSI hard disk (/dev/sdb inside the VM).
    # A DVD-backed ISO would appear on /dev/sr0 which fails with
    # "Can't lookup blockdev" on Hyper-V before cloud-init runs.
    Add-VMHardDiskDrive -VMName "zs-config-host" -Path $SeedDisk
    $osDrive = Get-VMHardDiskDrive -VMName "zs-config-host" |
               Where-Object { $_.Path -eq $OsDisk } | Select-Object -First 1
    Set-VMFirmware -VMName "zs-config-host" -BootOrder @($osDrive)

    Write-Host "VM 'zs-config-host' provisioned."
}

function Wait-ForVmIp {
    param([string]$VmName, [int]$TimeoutSeconds = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $ip = (Get-VM -Name $VmName |
               Get-VMNetworkAdapter |
               Select-Object -ExpandProperty IPAddresses |
               Where-Object { $_ -match "^\d+\.\d+\.\d+\.\d+$" -and
                              $_ -notmatch "^169\." } |
               Select-Object -First 1)
        if ($ip) {
            $KeyDir = Join-Path $env:APPDATA "zs-config\vm"
            [System.IO.File]::WriteAllText((Join-Path $KeyDir "vm-ip.txt"), $ip)
            return $ip
        }
        Start-Sleep -Seconds 3
    }
    throw "Timed out waiting for VM '$VmName' to get an IP address."
}

function Wait-ForSsh {
    param([string]$Ip, [int]$TimeoutSeconds = 600)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect($Ip, 22)
            $tcp.Close()
            return
        } catch {}
        Start-Sleep -Seconds 3
    }
    throw "Timed out waiting for SSH on $Ip."
}

function Wait-ForDocker {
    param([string]$Ip, [int]$TimeoutSeconds = 180)
    $KeyDir  = Join-Path $env:APPDATA "zs-config\vm"
    $KeyFile = Join-Path $KeyDir "id_ed25519"
    $SshOpts = @(
        "-i", $KeyFile,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=NUL",
        "-o", "ConnectTimeout=10"
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $result = & ssh @SshOpts "zsadmin@$Ip" "docker info" 2>&1
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 5
    }
    throw "Timed out waiting for Docker Engine inside the VM."
}

function Invoke-Ssh {
    param([string]$Ip, [string[]]$Cmd)
    $KeyDir  = Join-Path $env:APPDATA "zs-config\vm"
    $KeyFile = Join-Path $KeyDir "id_ed25519"
    $SshOpts = @(
        "-i", $KeyFile,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=NUL",
        "-o", "ConnectTimeout=10"
    )
    & ssh @SshOpts "zsadmin@$Ip" @Cmd
    if ($LASTEXITCODE -ne 0) {
        throw "SSH command failed (exit $LASTEXITCODE): $Cmd"
    }
}

function Invoke-WindowsServerDeploy {
    param([string]$Branch)

    Write-Host "Windows Server detected. Using Hyper-V + Linux VM path."

    Ensure-AdminPrivileges
    Ensure-OpenSshClient
    Ensure-HyperV
    $PubKey = Ensure-SshKey

    Ensure-VM -SshPublicKey $PubKey

    $vm = Get-VM -Name "zs-config-host"
    if ($vm.State -ne "Running") {
        Start-VM -Name "zs-config-host"
        Write-Host "Starting VM 'zs-config-host'..."
    }

    $VmIp = Wait-ForVmIp -VmName "zs-config-host"
    Write-Host "VM IP: $VmIp"

    Wait-ForSsh    -Ip $VmIp
    Wait-ForDocker -Ip $VmIp

    $cloneCmd  = "git clone --branch $Branch $RepoUrl ~/zs-config 2>/dev/null || (cd ~/zs-config && git fetch origin && git checkout $Branch && git reset --hard origin/$Branch)"
    $deployCmd = "chmod +x ~/zs-config/deploy.sh && ~/zs-config/deploy.sh $Branch --non-interactive"
    Invoke-Ssh $VmIp $cloneCmd
    Invoke-Ssh $VmIp $deployCmd

    $KeyDir  = Join-Path $env:APPDATA "zs-config\vm"
    $KeyFile = Join-Path $KeyDir "id_ed25519"
    Write-Host ""
    Write-Host "Deployment complete. Access zs-config at:"
    Write-Host "  http://${VmIp}:8000"
    Write-Host ""
    Write-Host "To manage the VM:"
    Write-Host "  ssh -i $KeyFile zsadmin@$VmIp"
}

if (Test-IsWindowsServer) {
    Invoke-WindowsServerDeploy -Branch $Branch
    exit $LASTEXITCODE
}

# -- Preflight ------------------------------------------------------------------

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "ERROR: docker is not installed or not in PATH."
    exit 1
}

try {
    docker compose version | Out-Null
} catch {
    Write-Error "ERROR: docker compose (v2) is required."
    exit 1
}

# -- docker-compose.yml diff check ----------------------------------------------

$script:DcBackup = $null

function Invoke-ComposeDiff {
    param([string]$Branch)
    $dcFile = Join-Path $RepoDir "docker-compose.yml"
    if (-not (Test-Path $dcFile)) { return }

    $tmpRemote = [System.IO.Path]::GetTempFileName()
    try {
        $content = & git show "origin/${Branch}:docker-compose.yml" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $content) {
            Remove-Item $tmpRemote -ErrorAction SilentlyContinue; return
        }
        [System.IO.File]::WriteAllLines($tmpRemote, $content)
    } catch {
        Remove-Item $tmpRemote -ErrorAction SilentlyContinue; return
    }

    $savedPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & git diff --no-index --quiet $dcFile $tmpRemote 2>$null
    $hasDiff = ($LASTEXITCODE -ne 0)
    $ErrorActionPreference = $savedPref

    if (-not $hasDiff) {
        Remove-Item $tmpRemote -ErrorAction SilentlyContinue; return
    }

    Write-Host ""
    Write-Host "docker-compose.yml differs from upstream (origin/$Branch):"
    Write-Host "------------------------------------------------------------"
    $ErrorActionPreference = "Continue"
    & git diff --no-index --src-prefix="local/" --dst-prefix="upstream/" $dcFile $tmpRemote
    $ErrorActionPreference = $savedPref
    Write-Host "------------------------------------------------------------"
    Write-Host ""
    Remove-Item $tmpRemote -ErrorAction SilentlyContinue

    if (-not [Console]::IsInputRedirected) {
        Write-Host "  [1] Use upstream version (recommended)"
        Write-Host "  [2] Keep my local version"
        $dcChoice = Read-Host "Choice [1/2, default 1]"
        if ($dcChoice -eq "2") {
            $script:DcBackup = [System.IO.Path]::GetTempFileName()
            Copy-Item $dcFile $script:DcBackup
            Write-Host "Local docker-compose.yml saved; will be restored after pull."
        }
    } else {
        Write-Host "Non-interactive - using upstream docker-compose.yml."
    }
    Write-Host ""
}

function Restore-Compose {
    if ($script:DcBackup -and (Test-Path $script:DcBackup)) {
        Copy-Item $script:DcBackup (Join-Path $RepoDir "docker-compose.yml") -Force
        Remove-Item $script:DcBackup -ErrorAction SilentlyContinue
        $script:DcBackup = $null
        Write-Host "Restored local docker-compose.yml."
    }
}

# -- Clone if not already inside the repo --------------------------------------

$IsRepo = $false
try {
    $null = git -C $ScriptDir rev-parse --git-dir 2>$null
    $IsRepo = $true
} catch {}

if ($IsRepo) {
    $RepoDir = git -C $ScriptDir rev-parse --show-toplevel
    Set-Location $RepoDir
    Write-Host "Fetching latest code..."
    git fetch origin
    Invoke-ComposeDiff $Branch
    git checkout $Branch
    git pull origin $Branch
    Restore-Compose
} else {
    $RepoDir = Join-Path $ScriptDir "zs-config"
    if (Test-Path $RepoDir) {
        Write-Host "Found existing clone at $RepoDir, pulling latest..."
        Set-Location $RepoDir
        git fetch origin
        Invoke-ComposeDiff $Branch
        git checkout $Branch
        git pull origin $Branch
        Restore-Compose
    } else {
        Write-Host "Cloning $RepoUrl into $RepoDir..."
        git clone --branch $Branch $RepoUrl $RepoDir
        Set-Location $RepoDir
    }
}

# -- Ensure JWT_SECRET is set ---------------------------------------------------

$EnvFile = Join-Path $RepoDir ".env"
$JwtSecret = $null
$BindAddr  = $null
$SslDomain = $null

if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match "^JWT_SECRET=(.+)$")    { $JwtSecret = $Matches[1] }
        if ($line -match "^BIND_ADDR=(.+)$")     { $BindAddr  = $Matches[1] }
        if ($line -match "^ZS_SSL_DOMAIN=(.+)$") { $SslDomain = $Matches[1] }
    }
}

if (-not $JwtSecret) {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $JwtSecret = ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
    Add-Content -Path $EnvFile -Value "JWT_SECRET=$JwtSecret"
    Write-Host "Generated JWT_SECRET and saved to $EnvFile - keep this file safe."
}

$env:JWT_SECRET = $JwtSecret

# -- Network binding ------------------------------------------------------------

if (-not $BindAddr) {
    Write-Host ""
    Write-Host "Network binding:"
    Write-Host "  [1] Localhost only - 127.0.0.1 (default, single machine)"
    Write-Host "  [2] All interfaces - 0.0.0.0   (server / remote access)"
    $bindChoice = Read-Host "Choice [1/2, default 1]"
    if ($bindChoice -eq "2") { $BindAddr = "0.0.0.0" } else { $BindAddr = "127.0.0.1" }
    Add-Content -Path $EnvFile -Value "BIND_ADDR=$BindAddr"
    Write-Host "Network binding set to $BindAddr - saved to .env."
    Write-Host ""
}

$env:BIND_ADDR = $BindAddr

# -- SSL certificate (optional) -------------------------------------------------

if (-not $SslDomain) {
    Write-Host ""
    Write-Host "SSL certificate (optional):"
    Write-Host "  Skip to use HTTP on port 8000, or provide a cert to enable HTTPS on port 8443."
    $sslChoice = Read-Host "Configure SSL now? [y/N]"
    if ($sslChoice -match "^[Yy]$") {
        $SslDomain = Read-Host "Domain (CN/SAN on the cert, e.g. myapp.company.com)"
        $certSrc   = Read-Host "Path to certificate file (PEM - leaf + CA chain)"
        $keySrc    = Read-Host "Path to private key file (PEM)"

        if (-not (Test-Path $certSrc)) { Write-Error "Certificate file not found: $certSrc"; exit 1 }
        if (-not (Test-Path $keySrc))  { Write-Error "Key file not found: $keySrc"; exit 1 }

        $certsDir = Join-Path $RepoDir "certs"
        New-Item -ItemType Directory -Path $certsDir -Force | Out-Null
        Copy-Item $certSrc (Join-Path $certsDir "cert.pem") -Force
        Copy-Item $keySrc  (Join-Path $certsDir "key.pem")  -Force

        Add-Content -Path $EnvFile -Value "ZS_SSL_DOMAIN=$SslDomain"
        Write-Host "SSL configured for domain $SslDomain - cert files copied to $certsDir"
        Write-Host ""
    }
}

if ($SslDomain) { $env:ZS_SSL_DOMAIN = $SslDomain }

# Always ensure certs/ exists so the bind mount never fails on a fresh clone.
New-Item -ItemType Directory -Path (Join-Path $RepoDir "certs") -Force | Out-Null

# -- Ensure persistent Docker volumes exist -------------------------------------

foreach ($vol in @("zs-config_zs-db", "zs-config_zs-plugins")) {
    $exists = docker volume inspect $vol 2>$null
    if (-not $exists) {
        Write-Host "Creating Docker volume: $vol"
        docker volume create $vol
    }
}

# -- Inject host trust store ----------------------------------------------------
# Exports trusted root certs into docker/ca-bundle.pem so the image includes
# any corporate SSL-inspection CAs present on this machine.  Cleared in the
# finally block so the file is never committed with real cert content.

$Bundle = Join-Path $RepoDir "docker\ca-bundle.pem"
Set-Content -Path $Bundle -Value ""

try {
    Write-Host "Exporting Windows certificate store -> docker\ca-bundle.pem"
    foreach ($storePath in @("Cert:\LocalMachine\Root", "Cert:\CurrentUser\Root")) {
        foreach ($cert in (Get-ChildItem $storePath -ErrorAction SilentlyContinue)) {
            $pem = "-----BEGIN CERTIFICATE-----`n" +
                   [Convert]::ToBase64String($cert.RawData, 'InsertLineBreaks') +
                   "`n-----END CERTIFICATE-----`n"
            Add-Content -Path $Bundle -Value $pem
        }
    }
    $certCount = (Select-String -Path $Bundle -Pattern "BEGIN CERTIFICATE" -ErrorAction SilentlyContinue).Count
    Write-Host "  Exported $certCount certificates"

    # -- Build -------------------------------------------------------------------

    Write-Host "Building image..."
    docker compose build

    # -- Deploy ------------------------------------------------------------------

    Write-Host "Stopping existing container..."
    docker compose down

    Write-Host "Starting container..."
    docker compose up -d

    # -- Health check ------------------------------------------------------------

    Write-Host "Waiting for health check..."
    $ready = $false
    for ($i = 1; $i -le 15; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {}
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 1
    }

    Write-Host ""
    if ($ready) {
        Write-Host ""
        if ($SslDomain) {
            Write-Host "zs-config is running at https://${SslDomain}:8443"
            Write-Host "(HTTP on port 8000 redirects to HTTPS)"
        } else {
            Write-Host "zs-config is running at http://localhost:8000"
        }
        Write-Host ""
        docker compose logs --tail=5
    } else {
        Write-Warning "Health check did not pass within 15 seconds. Check logs:"
        Write-Host "  docker compose logs"
        exit 1
    }
} finally {
    Set-Content -Path $Bundle -Value ""
    if ($script:DcBackup -and (Test-Path $script:DcBackup)) {
        Remove-Item $script:DcBackup -ErrorAction SilentlyContinue
    }
}
