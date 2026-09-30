# Single source of truth for harness identity constants (issue #55).
# Data-only file: loaded with Import-PowerShellDataFile. No absolute local
# paths, no usernames: every location is a name relative to a well-known
# folder that the consuming module resolves at run time.
#
# Policy (plan v2.3): workstation tooling installs ONLY the Acceptance
# identity. The Production block exists for DETECTION and REFUSAL only; no
# tool may install, uninstall, write or delete anything under it.
@{
    SchemaVersion = 1

    # Identity a rewrapped installer must carry (tools/release rewrap, task B).
    Acceptance = @{
        ProductName    = 'Snapmaker Studio Acceptance'
        Manufacturer   = 'SnapmakerStudio-Acceptance'
        BundleId       = 'com.snapmakerstudio.acceptance'
        MainBinaryName = 'snapmaker-studio-acceptance-desktop.exe'
        SidecarName    = 'snapstudio-api.exe'
        UninstallerName = 'uninstall.exe'
    }

    # DETECTION / REFUSAL ONLY. Never a write target.
    Production = @{
        ProductName    = 'Snapmaker Studio'
        Manufacturer   = 'DeadlyVirusIn / Snapmaker Studio'
        BundleId       = 'com.snapmakerstudio.desktop'
        MainBinaryName = 'snapmaker-studio-desktop.exe'
        ProcessName    = 'snapmaker-studio-desktop'
        # Tauri per-user default install folder name under %LOCALAPPDATA%.
        DefaultInstallDirName = 'Snapmaker Studio'
        # Engine data dir name under %LOCALAPPDATA% (prefix-neighbour of the harness root).
        EngineDataDirName = 'SnapmakerStudio'
        # Strings no acceptance-derived delete/write target may contain (see Test-RewrapAttestation).
        ForbiddenTargetPatterns = @(
            'Snapmaker Studio(?! Acceptance)'
            'com\.snapmakerstudio\.desktop'
            'DeadlyVirusIn'
            'snapmaker-studio-desktop'
            'SnapmakerStudio(?![-A-Za-z])'
        )
    }

    # Harness-owned tree: %LOCALAPPDATA%\<HarnessRootDirName>
    HarnessRootDirName = 'SnapmakerStudio-Harness'
    HarnessSubdirs = @{
        Journal      = 'journal'
        Install      = 'install'       # acceptance installs live ONLY here
        Staging      = 'staging'       # copy-then-hash installer copies
        Attestations = 'attestations'  # trusted rewrap attestations
        Lock         = 'lock'
        # Extraction / rewrap work trees. An uninstaller found here is never authorized (C1).
        WorkDirs     = @('work', 'extract', 'rewrap', 'staging')
    }

    # Registry layout (relative to the `Software` hive root; tests substitute a scratch root).
    Registry = @{
        UninstallKeyParent = 'Microsoft\Windows\CurrentVersion\Uninstall'
        RunKey             = 'Microsoft\Windows\CurrentVersion\Run'
        # Only registry roots accepted for overrides: the real HKCU Software root itself, or that root plus
        # this scratch parent plus one name (see Assert-SafeRegistryRoot for the exact pattern).
        ScratchParent      = 'SnapmakerStudioHarnessTest'
        # Remembered install-location key = <Manufacturer>\<ProductName>, default value = install dir.
    }

    # Machine-wide single-run lock (M5).
    LockMutexName = 'Global\SnapmakerStudio-Harness-Lock'
    LockFileName  = 'harness.lock.json'

    # FIXED recovery allow-list (M6/S8). Recovery touches these surfaces and
    # nothing else; paths are built from the Acceptance block only, never read
    # from a journal. {ProductName} / {Manufacturer} are substituted from Acceptance.
    RecoveryAllowList = @(
        @{ Id = 'UninstallKey';          Type = 'RegKey';   KeyTemplate = '{UninstallKeyParent}\{ProductName}'; ValueName = $null }
        @{ Id = 'RememberedLocationKey'; Type = 'RegKey';   KeyTemplate = '{Manufacturer}\{ProductName}';       ValueName = $null }
        @{ Id = 'RunValue';              Type = 'RegValue'; KeyTemplate = '{RunKey}';                           ValueName = '{ProductName}' }
        @{ Id = 'StartMenuShortcut';     Type = 'File';     Folder = 'StartMenu'; FileTemplate = '{ProductName}.lnk' }
        @{ Id = 'DesktopShortcut';       Type = 'File';     Folder = 'Desktop';   FileTemplate = '{ProductName}.lnk' }
    )

    # Trusted rewrap attestation schema (consumed here, produced by tools/release).
    Attestation = @{
        SchemaVersion = 1
        Kind          = 'snapmaker-studio-acceptance-rewrap-attestation'
        # sha256 (64 hex) of the vendored NSIS template (tauri-bundler 2.11.3). TASK B FILLS THIS SLOT
        # when it vendors the template. Empty = no attestation can validate (fail closed).
        PinnedTemplateSha256 = ''
    }

    # M8: the installed file set must be EXACTLY these (uninstall.exe is installer machinery, excluded).
    # Main binary is Acceptance.MainBinaryName; sidecar is Acceptance.SidecarName.
}
