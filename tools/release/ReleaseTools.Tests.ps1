#requires -Version 7.0
# Pester 5. Hermetic: no network, no real 7-Zip / NSIS, nothing executed. Synthetic tool trees and a synthetic lock
# live in private temp dirs (removed in AfterAll).

BeforeAll {
    Import-Module (Join-Path $PSScriptRoot 'lib\ReleaseTools.psm1') -Force -DisableNameChecking

    $script:Root = Join-Path ([IO.Path]::GetTempPath()) "ssh-reltools-test-$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Force -Path $script:Root | Out-Null

    function script:Sha([byte[]]$b) { ([BitConverter]::ToString([Security.Cryptography.SHA256]::HashData($b)).Replace('-', '').ToLowerInvariant()) }
    function script:Bytes([string]$s) { [Text.Encoding]::UTF8.GetBytes($s) }

    # A synthetic tools dir + a lock that pins it. Returns @{ Dir; Lock; Paths }.
    function script:New-FakeTools {
        $dir = Join-Path $script:Root ("tools-" + [guid]::NewGuid().ToString('N'))
        $lock = @{
            schemaVersion = 1
            sevenZip = @{
                version = '0.0'
                downloads = @{}
                binaries = @{ '7z.exe' = (Sha (Bytes 'fake-7z-exe')); '7z.dll' = (Sha (Bytes 'fake-7z-dll')) }; treeSha256 = ''; treeFileCount = 0
                bootstrapBinaries = @{}
            }
            nsis = @{ version = '0.0'; download = @{}; innerDir = 'nsis-0.0'; treeSha256 = ''; treeFileCount = 0; makensisSha256 = (Sha (Bytes 'fake-makensis')) }
            tauriUtilsDll = @{ fileName = 'x.dll'; sha256 = ('f' * 64) }
        }
        $p = Get-ReleaseToolPaths -ToolsDir $dir -Lock $lock
        New-Item -ItemType Directory -Force -Path $p.SevenZipDir, (Join-Path $p.NsisDir 'Bin'), (Join-Path $p.NsisDir 'Include') | Out-Null
        [IO.File]::WriteAllBytes($p.SevenZip, (Bytes 'fake-7z-exe'))
        [IO.File]::WriteAllBytes($p.SevenZipDll, (Bytes 'fake-7z-dll'))
        [IO.File]::WriteAllBytes($p.Makensis, (Bytes 'fake-makensis'))
        [IO.File]::WriteAllBytes((Join-Path $p.NsisDir 'Include\MUI2.nsh'), (Bytes 'fake-include'))
        $t = Get-DirectoryTreeSha256 -Path $p.NsisDir
        $lock.nsis.treeSha256 = $t.Sha256; $lock.nsis.treeFileCount = $t.FileCount
        $z = Get-DirectoryTreeSha256 -Path $p.SevenZipDir
        $lock.sevenZip.treeSha256 = $z.Sha256; $lock.sevenZip.treeFileCount = $z.FileCount
        @{ Dir = $dir; Lock = $lock; Paths = $p }
    }
}

AfterAll {
    if ($script:Root -and (Test-Path -LiteralPath $script:Root)) {
        # remove only junctions we created, then the private temp tree
        foreach ($d in Get-ChildItem -LiteralPath $script:Root -Recurse -Force -Directory -ErrorAction SilentlyContinue) {
            if ($d.Attributes -band [IO.FileAttributes]::ReparsePoint) { [IO.Directory]::Delete($d.FullName) }
        }
        Remove-Item -LiteralPath $script:Root -Recurse -Force
    }
}

Describe 'tools.lock.json' {
    It 'parses and pins every download and binary with a 64-hex sha256 and an https url' {
        $lock = Get-ToolsLock
        $lock.sevenZip.version | Should -Be '26.03'
        $lock.nsis.version | Should -Be '3.11'
        $lock.tauriUtilsDll.sha256 | Should -Be '5ba143b5db4a87d32d6e7802e033330aae56cbceabe0d1e3ba41948385ad4709'
        foreach ($d in @($lock.sevenZip.downloads.Values) + @($lock.nsis.download)) {
            $d.sha256 | Should -Match '^[0-9a-f]{64}$'
            $d.url | Should -Match '^https://'
            $d.checksumSource | Should -Not -BeNullOrEmpty
        }
        $lock.nsis.treeSha256 | Should -Match '^[0-9a-f]{64}$'
    }
    It 'rejects a lock with a malformed hash' {
        $bad = Join-Path $script:Root 'bad.lock.json'
        (Get-Content (Join-Path $PSScriptRoot 'tools.lock.json') -Raw) -replace 'ad4c82fadcbdf93c03b4fc440f300509c7d60c5c2f4d183e35d9d70d6957037d', 'XYZ' | Set-Content -LiteralPath $bad
        { Get-ToolsLock -Path $bad } | Should -Throw '*bad sha256*'
    }
}

Describe 'Get-DirectoryTreeSha256' {
    It 'is deterministic and changes when a single byte changes' {
        $d = Join-Path $script:Root 'tree1'; New-Item -ItemType Directory -Force -Path (Join-Path $d 'sub') | Out-Null
        [IO.File]::WriteAllBytes((Join-Path $d 'a.txt'), (Bytes 'a'))
        [IO.File]::WriteAllBytes((Join-Path $d 'sub\b.txt'), (Bytes 'b'))
        $h1 = Get-DirectoryTreeSha256 -Path $d
        (Get-DirectoryTreeSha256 -Path $d).Sha256 | Should -Be $h1.Sha256
        $h1.FileCount | Should -Be 2
        [IO.File]::WriteAllBytes((Join-Path $d 'sub\b.txt'), (Bytes 'c'))
        (Get-DirectoryTreeSha256 -Path $d).Sha256 | Should -Not -Be $h1.Sha256
    }
    It 'refuses a reparse point inside the tree' {
        $d = Join-Path $script:Root 'tree2'; $t = Join-Path $script:Root 'tree2-target'
        New-Item -ItemType Directory -Force -Path $d, $t | Out-Null
        New-Item -ItemType Junction -Path (Join-Path $d 'j') -Target $t | Out-Null
        { Get-DirectoryTreeSha256 -Path $d } | Should -Throw '*reparse point*'
    }
}

Describe 'Assert-PinnedTools (full verification of the unpacked tools)' {
    It 'accepts an untouched tool tree' {
        $f = New-FakeTools
        $r = Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock
        $r.Makensis | Should -Be $f.Paths.Makensis
    }
    It 'refuses a tampered 7z.exe (hash mismatch)' {
        $f = New-FakeTools
        [IO.File]::WriteAllBytes($f.Paths.SevenZip, (Bytes 'evil-7z-exe'))
        { Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock } | Should -Throw '*7z.exe sha256 mismatch*'
    }
    It 'refuses a tampered 7z.dll' {
        $f = New-FakeTools
        [IO.File]::WriteAllBytes($f.Paths.SevenZipDll, (Bytes 'evil'))
        { Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock } | Should -Throw '*7z.dll sha256 mismatch*'
    }
    It 'refuses a tampered makensis (tree hash mismatch)' {
        $f = New-FakeTools
        [IO.File]::WriteAllBytes($f.Paths.Makensis, (Bytes 'evil-makensis'))
        { Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock } | Should -Throw '*NSIS tree hash mismatch*'
    }
    It 'refuses an extra file planted in the NSIS tree' {
        $f = New-FakeTools
        [IO.File]::WriteAllBytes((Join-Path $f.Paths.NsisDir 'Include\planted.nsh'), (Bytes '!system "x"'))
        { Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock } | Should -Throw '*NSIS tree hash mismatch*'
    }
    It 'refuses a missing 7-Zip' {
        $f = New-FakeTools
        Remove-Item -LiteralPath $f.Paths.SevenZip
        { Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock } | Should -Throw '*7z.exe is missing*'
    }
    It 'refuses a reparse point inside the NSIS tree' {
        $f = New-FakeTools
        $t = Join-Path $script:Root ("jt-" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $t | Out-Null
        New-Item -ItemType Junction -Path (Join-Path $f.Paths.NsisDir 'Include\j') -Target $t | Out-Null
        { Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock } | Should -Throw '*reparse point*'
    }
}

Describe 'Save-VerifiedDownload / Install-PinnedTools download pinning' {
    It 'refuses a download whose bytes do not match the pinned sha256 and leaves nothing behind' {
        $dl = Join-Path $script:Root ("dl-" + [guid]::NewGuid().ToString('N'))
        $entry = @{ fileName = 'tool.bin'; url = 'https://example.invalid/tool.bin'; sha256 = (Sha (Bytes 'good')) }
        { Save-VerifiedDownload -Entry $entry -DownloadsDir $dl -Downloader { param($u, $d) [IO.File]::WriteAllBytes($d, [Text.Encoding]::UTF8.GetBytes('bad')) } } | Should -Throw '*pinned*'
        @(Get-ChildItem -LiteralPath $dl -Force).Count | Should -Be 0
    }
    It 'accepts matching bytes and re-uses a verified cached file without downloading' {
        $dl = Join-Path $script:Root ("dl-" + [guid]::NewGuid().ToString('N'))
        $entry = @{ fileName = 'tool.bin'; url = 'https://example.invalid/tool.bin'; sha256 = (Sha (Bytes 'good')) }
        $p = Save-VerifiedDownload -Entry $entry -DownloadsDir $dl -Downloader { param($u, $d) [IO.File]::WriteAllBytes($d, [Text.Encoding]::UTF8.GetBytes('good')) }
        Test-Path -LiteralPath $p | Should -BeTrue
        { Save-VerifiedDownload -Entry $entry -DownloadsDir $dl -Downloader { throw 'must not download again' } } | Should -Not -Throw
    }
    It 'Install-PinnedTools refuses (and unpacks nothing) when the first download is wrong' {
        $f = New-FakeTools
        $lock = $f.Lock
        $lock.sevenZip.downloads = @{ bootstrap = @{ fileName = '7zr.exe'; url = 'https://example.invalid/7zr.exe'; sha256 = (Sha (Bytes 'real-7zr')) } }
        $dir = Join-Path $script:Root ("empty-" + [guid]::NewGuid().ToString('N'))
        { Install-PinnedTools -ToolsDir $dir -Lock $lock -Downloader { param($u, $d) [IO.File]::WriteAllBytes($d, [Text.Encoding]::UTF8.GetBytes('evil')) } } | Should -Throw '*pinned*'
        Test-Path -LiteralPath (Join-Path $dir '7zip-0.0\7zr.exe') | Should -BeFalse
    }
}

Describe 'Get-ReleaseToolsDir overrides' {
    It 'refuses an override outside temp / the harness root' {
        { Get-ReleaseToolsDir -ToolsDir 'C:\Windows\System32\tools' } | Should -Throw '*not an allowed location*'
    }
    It 'refuses a relative override' {
        { Get-ReleaseToolsDir -ToolsDir '.\tools' } | Should -Throw '*not an allowed location*'
    }
    It 'accepts an override strictly inside temp' {
        $p = Join-Path ([IO.Path]::GetTempPath()) 'ssh-reltools-override-ok'
        Get-ReleaseToolsDir -ToolsDir $p | Should -Be $p
    }
    It 'refuses an override that is a junction' {
        $t = Join-Path $script:Root 'jt'; New-Item -ItemType Directory -Force -Path $t | Out-Null
        $j = Join-Path ([IO.Path]::GetTempPath()) "ssh-reltools-junction-$([guid]::NewGuid().ToString('N'))"
        New-Item -ItemType Junction -Path $j -Target $t | Out-Null
        try { { Get-ReleaseToolsDir -ToolsDir $j } | Should -Throw '*reparse point*' } finally { [IO.Directory]::Delete($j) }
    }
}

Describe 'Invoke-PinnedTool re-verifies the executable AT EXECUTION TIME' {
    It 'refuses when no verified tools directory is registered' {
        $f = New-FakeTools
        InModuleScope ReleaseTools { $script:ToolContexts = [System.Collections.Generic.List[object]]::new() }
        { Invoke-PinnedTool -Exe $f.Paths.SevenZip -Arguments @('x') } | Should -Throw '*no verified tools directory*'
    }
    It 'refuses a same-named exe outside the verified tools directory (even with a matching hash)' {
        $f = New-FakeTools; [void](Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock)
        $other = Join-Path $script:Root ("other-" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $other | Out-Null
        Copy-Item $f.Paths.SevenZip (Join-Path $other '7z.exe')
        { Invoke-PinnedTool -Exe (Join-Path $other '7z.exe') -Arguments @('x') } | Should -Throw '*not the tool inside the verified tools directory*'
    }
    It 'refuses a 7z.exe tampered AFTER the verification pass' {
        $f = New-FakeTools; [void](Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock)
        [IO.File]::WriteAllBytes($f.Paths.SevenZip, (Bytes 'swapped'))
        { Invoke-PinnedTool -Exe $f.Paths.SevenZip -Arguments @('x') } | Should -Throw '*7z.exe (at execution) sha256 mismatch*'
    }
    It 'refuses a 7z.dll tampered AFTER the verification pass' {
        $f = New-FakeTools; [void](Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock)
        [IO.File]::WriteAllBytes($f.Paths.SevenZipDll, (Bytes 'swapped'))
        { Invoke-PinnedTool -Exe $f.Paths.SevenZip -Arguments @('x') } | Should -Throw '*7z.dll (at execution) sha256 mismatch*'
    }
    It 'refuses a makensis.exe tampered AFTER the verification pass' {
        $f = New-FakeTools; [void](Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock)
        [IO.File]::WriteAllBytes($f.Paths.Makensis, (Bytes 'swapped'))
        { Invoke-PinnedTool -Exe $f.Paths.Makensis -Arguments @('x') } | Should -Throw '*makensis.exe (at execution) sha256 mismatch*'
    }
    It 'refuses an NSIS include tampered AFTER the verification pass (full tree hash right before compile)' {
        $f = New-FakeTools; [void](Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock)
        [IO.File]::WriteAllBytes((Join-Path $f.Paths.NsisDir 'Include\MUI2.nsh'), (Bytes '!system "x"'))
        { Invoke-PinnedTool -Exe $f.Paths.Makensis -Arguments @('x') } | Should -Throw '*NSIS tree (at execution) hash mismatch*'
    }
}

Describe '7-Zip folder tree and the verify / launch split' {
    It 'Assert-PinnedTools refuses a file planted beside 7z.exe (Codecs, Formats, extra dll)' {
        $f = New-FakeTools
        New-Item -ItemType Directory -Force -Path (Join-Path $f.Paths.SevenZipDir 'Codecs') | Out-Null
        [IO.File]::WriteAllBytes((Join-Path $f.Paths.SevenZipDir 'Codecs\evil.dll'), (Bytes 'evil'))
        { Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock } | Should -Throw '*7-Zip folder hash mismatch*'
    }
    It 'Assert-ToolVerified refuses a planted file beside 7z.exe even though 7z.exe and 7z.dll are intact' {
        $f = New-FakeTools; [void](Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock)
        [IO.File]::WriteAllBytes((Join-Path $f.Paths.SevenZipDir 'planted.dll'), (Bytes 'evil'))
        { Assert-ToolVerified -Exe $f.Paths.SevenZip } | Should -Throw '*7-Zip folder (at execution) hash mismatch*'
    }
    It 'Assert-ToolVerified passes for an untouched tool tree (both tools)' {
        $f = New-FakeTools; [void](Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock)
        { Assert-ToolVerified -Exe $f.Paths.SevenZip } | Should -Not -Throw
        { Assert-ToolVerified -Exe $f.Paths.Makensis } | Should -Not -Throw
    }
    It 'Start-PinnedTool re-checks the EXE hash at launch (and refuses before launching)' {
        $f = New-FakeTools; [void](Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock)
        [IO.File]::WriteAllBytes($f.Paths.Makensis, (Bytes 'swapped'))
        { Start-PinnedTool -Exe $f.Paths.Makensis -Arguments @('x') } | Should -Throw '*makensis.exe (at launch) sha256 mismatch*'
    }
    It 'Start-PinnedTool refuses an exe that is not the registered tool path' {
        $f = New-FakeTools; [void](Assert-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock)
        $other = Join-Path $script:Root ("o-" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $other | Out-Null
        Copy-Item $f.Paths.Makensis (Join-Path $other 'makensis.exe')
        { Start-PinnedTool -Exe (Join-Path $other 'makensis.exe') -Arguments @('x') } | Should -Throw '*not the tool inside the verified tools directory*'
    }
}

Describe 'New-ToolSnapshot: a private and verified copy that is what actually runs' {
    BeforeAll {
        function script:New-Snap([hashtable]$F, [scriptblock]$AfterFile) {
            $dest = Join-Path $script:Root ("snap-" + [guid]::NewGuid().ToString('N'))
            $a = @{ Source = $F.Paths; Destination = $dest; Lock = $F.Lock }
            if ($AfterFile) { $a.AfterFile = $AfterFile }
            @{ Dest = $dest; Paths = (New-ToolSnapshot @a) }
        }
        function script:New-FakeToolsWithTree {
            $f = New-FakeTools
            New-Item -ItemType Directory -Force -Path (Join-Path $f.Paths.NsisDir 'Plugins\x86-unicode') | Out-Null
            [IO.File]::WriteAllBytes((Join-Path $f.Paths.NsisDir 'Plugins\x86-unicode\System.dll'), (Bytes 'fake-system'))
            $t = Get-DirectoryTreeSha256 -Path $f.Paths.NsisDir
            $f.Lock.nsis.treeSha256 = $t.Sha256; $f.Lock.nsis.treeFileCount = $t.FileCount
            $f
        }
    }
    It 'copies the WHOLE 7-Zip folder and the WHOLE NSIS tree (layout preserved) and verifies the copy against the lock' {
        $f = New-FakeToolsWithTree
        $s = New-Snap $f
        (Get-DirectoryTreeSha256 -Path $s.Paths.NsisDir).Sha256 | Should -Be $f.Lock.nsis.treeSha256
        (Get-DirectoryTreeSha256 -Path $s.Paths.SevenZipDir).Sha256 | Should -Be $f.Lock.sevenZip.treeSha256
        Test-Path (Join-Path $s.Paths.NsisDir 'Plugins\x86-unicode\System.dll') | Should -BeTrue
        $s.Paths.Makensis | Should -BeLike "$($s.Dest)*"
    }
    It 'the snapshot exe is accepted by Assert-ToolVerified (registered), and an unregistered copy elsewhere is still refused' {
        $f = New-FakeToolsWithTree; $s = New-Snap $f
        { Assert-ToolVerified -Exe $s.Paths.Makensis } | Should -Not -Throw
        { Assert-ToolVerified -Exe $s.Paths.SevenZip } | Should -Not -Throw
        $other = Join-Path $script:Root ("o-" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $other | Out-Null
        Copy-Item $s.Paths.Makensis (Join-Path $other 'makensis.exe')
        { Assert-ToolVerified -Exe (Join-Path $other 'makensis.exe') } | Should -Throw '*not the tool inside the verified tools directory*'
    }
    It 'refuses a reparse point (junction directory) in the source tree' {
        $f = New-FakeToolsWithTree
        $t = Join-Path $script:Root ("jt-" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $t | Out-Null
        New-Item -ItemType Junction -Path (Join-Path $f.Paths.NsisDir 'Include\jx') -Target $t | Out-Null
        { New-Snap $f } | Should -Throw '*reparse point in the tool source tree*'
    }
    It 'refuses an existing destination (the snapshot dir is fresh and exclusive)' {
        $f = New-FakeToolsWithTree
        $dest = Join-Path $script:Root ("snap-" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $dest | Out-Null
        { New-ToolSnapshot -Source $f.Paths -Destination $dest -Lock $f.Lock } | Should -Throw '*already exists*'
    }
    It 'hashes the COPY against the lock: a tampered cache cannot be snapshotted' {
        $f = New-FakeToolsWithTree
        [IO.File]::WriteAllBytes((Join-Path $f.Paths.NsisDir 'Include\MUI2.nsh'), (Bytes '!system "calc"'))
        { New-Snap $f } | Should -Throw '*NSIS snapshot hash mismatch*'
    }
    It 'a file planted in the cache 7-Zip folder (7z.exe / 7z.dll intact) cannot be snapshotted: the whole copied folder is hashed' {
        $f = New-FakeToolsWithTree
        New-Item -ItemType Directory -Force -Path (Join-Path $f.Paths.SevenZipDir 'Codecs') | Out-Null
        [IO.File]::WriteAllBytes((Join-Path $f.Paths.SevenZipDir 'Codecs\planted.dll'), (Bytes 'evil'))
        { New-Snap $f } | Should -Throw '*7-Zip snapshot hash mismatch*'
    }
    It 'detects a mutation DURING copying (the copy is what is hashed)' {
        $f = New-FakeToolsWithTree
        $hook = { param($src, $dst) if ($dst -like '*MUI2.nsh') { [IO.File]::WriteAllBytes($dst, [byte[]](9, 9, 9)) } }
        { New-Snap $f $hook } | Should -Throw '*NSIS snapshot hash mismatch*'
    }
    It 'a 7z.dll swapped in the ORIGINAL cache after the snapshot does not affect the snapshot; one swapped IN the snapshot is refused' {
        $f = New-FakeToolsWithTree; $s = New-Snap $f
        [IO.File]::WriteAllBytes($f.Paths.SevenZipDll, (Bytes 'swapped-in-cache'))
        { Assert-ToolVerified -Exe $s.Paths.SevenZip } | Should -Not -Throw
        [IO.File]::WriteAllBytes($s.Paths.SevenZipDll, (Bytes 'swapped-in-snapshot'))
        { Assert-ToolVerified -Exe $s.Paths.SevenZip } | Should -Throw '*7z.dll (at execution) sha256 mismatch*'
    }
    It 'the snapshot makensis.exe swapped after its tree hash is refused at launch; a swapped include is refused by Assert-ToolVerified' {
        $f = New-FakeToolsWithTree; $s = New-Snap $f
        [IO.File]::WriteAllBytes((Join-Path $s.Paths.NsisDir 'Include\MUI2.nsh'), (Bytes 'swapped'))
        { Assert-ToolVerified -Exe $s.Paths.Makensis } | Should -Throw '*NSIS tree (at execution) hash mismatch*'
        $s2 = New-Snap $f
        [IO.File]::WriteAllBytes($s2.Paths.Makensis, (Bytes 'swapped-exe'))
        { Start-PinnedTool -Exe $s2.Paths.Makensis -Arguments @('x') } | Should -Throw '*makensis.exe (at launch) sha256 mismatch*'
    }
    It 'the original NSIS tree can disappear after the snapshot without affecting verification of the snapshot' {
        $f = New-FakeToolsWithTree; $s = New-Snap $f
        Rename-Item -LiteralPath $f.Paths.NsisDir -NewName 'nsis-gone'
        { Assert-ToolVerified -Exe $s.Paths.Makensis } | Should -Not -Throw
    }
}

Describe 'tool-cache serialization' {
    It 'snapshotting waits for the cache lock and refuses after the timeout while another run holds it' {
        $f = New-FakeTools
        $name = Get-ToolCacheLockName -Dir $f.Paths.Root
        $ready = [Threading.ManualResetEvent]::new($false); $release = [Threading.ManualResetEvent]::new($false)
        $ps = [powershell]::Create()
        [void]$ps.AddScript({ param($n, $ready, $release) $m = [Threading.Mutex]::new($false, $n); [void]$m.WaitOne(); $ready.Set(); [void]$release.WaitOne(30000); $m.ReleaseMutex() }).AddArgument($name).AddArgument($ready).AddArgument($release)
        $h = $ps.BeginInvoke()
        try {
            $ready.WaitOne(10000) | Should -BeTrue
            $dest = Join-Path $script:Root ("snap-" + [guid]::NewGuid().ToString('N'))
            { New-ToolSnapshot -Source $f.Paths -Destination $dest -Lock $f.Lock -LockTimeoutSeconds 1 } | Should -Throw '*could not acquire the tool-cache lock*'
            { Install-PinnedTools -ToolsDir $f.Dir -Lock $f.Lock -LockTimeoutSeconds 1 } | Should -Throw '*could not acquire the tool-cache lock*'
        } finally { [void]$release.Set(); [void]$ps.EndInvoke($h); $ps.Dispose() }
        # once released, the same call succeeds
        $dest2 = Join-Path $script:Root ("snap-" + [guid]::NewGuid().ToString('N'))
        { New-ToolSnapshot -Source $f.Paths -Destination $dest2 -Lock $f.Lock -LockTimeoutSeconds 5 } | Should -Not -Throw
    }
}

Describe 'Invoke-PinnedTool (the single launch site)' {
    It 'refuses a non-allow-listed executable' {
        { Invoke-PinnedTool -Exe (Join-Path $env:SystemRoot 'System32\whoami.exe') -Arguments @('x') } | Should -Throw '*not an allowed pinned tool*'
    }
    It 'refuses a relative executable path' {
        { Invoke-PinnedTool -Exe '7z.exe' -Arguments @('x') } | Should -Throw '*absolute*'
    }
}

Describe 'Expand-ZipSafely' {
    It 'refuses a zip entry that escapes the destination' {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zp = Join-Path $script:Root 'evil.zip'
        $fs = [IO.File]::Open($zp, 'Create'); $z = [IO.Compression.ZipArchive]::new($fs, 'Create')
        $e = $z.CreateEntry('top/../../evil.txt'); $w = [IO.StreamWriter]::new($e.Open()); $w.Write('x'); $w.Dispose(); $z.Dispose(); $fs.Dispose()
        $dest = Join-Path $script:Root 'zipdest'
        { Expand-ZipSafely -ZipPath $zp -Destination $dest } | Should -Throw '*unsafe zip entry*'
        Test-Path -LiteralPath (Join-Path $script:Root 'evil.txt') | Should -BeFalse
    }
}
