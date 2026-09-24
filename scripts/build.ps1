[CmdletBinding()]
param(
    [string]$PythonExe = 'python',
    [switch]$StopRunning
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$ExePath = Join-Path $Root 'TokenWatcher.exe'
$RuntimePath = Join-Path $Root 'TokenWatcher.runtime'
$DistPath = Join-Path $Root 'dist\TokenWatcher'
$WorkPath = Join-Path $Root 'build\TokenWatcher'
$SpecPath = Join-Path $Root 'build\spec'
$LauncherSource = Join-Path $Root 'launcher\TokenWatcherLauncher.cs'
$ArchivePath = Join-Path $Root 'TokenWatcher-windows.zip'
$ChecksumPath = "$ArchivePath.sha256"
$SmokePath = Join-Path $Root 'build\TokenWatcher\packaged-smoke.json'

function Assert-WorkspaceChildPath([string]$Path) {
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar)
    $pathFull = [IO.Path]::GetFullPath($Path)
    $prefix = $rootFull + [IO.Path]::DirectorySeparatorChar
    if (-not $pathFull.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify path outside the repository: $pathFull"
    }
}

function Remove-WorkspaceOutput([string]$Path) {
    Assert-WorkspaceChildPath $Path
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Sign-ExecutableIfConfigured([string]$Path) {
    $thumbprint = $env:TOKENWATCHER_SIGN_CERT_SHA1
    if (-not $thumbprint) {
        return
    }
    $signTool = Get-Command signtool.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $signTool) {
        $signTool = Get-ChildItem `
            (Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin') `
            -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
    }
    if (-not $signTool) {
        throw 'TOKENWATCHER_SIGN_CERT_SHA1 is set but signtool.exe was not found.'
    }
    $signToolPath = if ($signTool.Source) { $signTool.Source } else { $signTool.FullName }
    & $signToolPath sign /sha1 $thumbprint /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $Path
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode signing failed for $Path."
    }
}

if ($StopRunning) {
    Get-Process TokenWatcher -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 300
}

foreach ($output in @($ExePath, $RuntimePath, $DistPath, $WorkPath, $SpecPath, $ArchivePath, $ChecksumPath)) {
    Remove-WorkspaceOutput $output
}
New-Item -ItemType Directory -Path $SpecPath -Force | Out-Null

Push-Location $Root
try {
    & $PythonExe -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --windowed `
        --exclude-module numpy `
        --name TokenWatcher `
        --distpath (Join-Path $Root 'dist') `
        --workpath $WorkPath `
        --specpath $SpecPath `
        (Join-Path $Root 'src\token_watcher.py')

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

    Assert-WorkspaceChildPath $RuntimePath
    if (Test-Path -LiteralPath $RuntimePath) {
        Remove-Item -LiteralPath $RuntimePath -Recurse -Force
    }
    Copy-Item -LiteralPath $DistPath -Destination $RuntimePath -Recurse

    $cscCandidates = @(
        (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
        (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
    )
    $CscExe = $cscCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $CscExe) {
        $CscExe = (Get-Command csc.exe -ErrorAction SilentlyContinue | Select-Object -First 1).Source
    }
    if (-not $CscExe) {
        throw 'The Windows C# compiler was not found. Install .NET Framework build tools or a .NET SDK exposing csc.exe.'
    }

    & $CscExe `
        '/nologo' `
        '/target:winexe' `
        '/optimize+' `
        '/reference:System.Windows.Forms.dll' `
        "/out:$ExePath" `
        $LauncherSource
    if ($LASTEXITCODE -ne 0) {
        throw "Launcher compilation failed with exit code $LASTEXITCODE."
    }

    $RuntimeExe = Join-Path $RuntimePath 'TokenWatcher.exe'
    Sign-ExecutableIfConfigured $RuntimeExe
    Sign-ExecutableIfConfigured $ExePath

    $smokeProcess = Start-Process `
        -FilePath $ExePath `
        -ArgumentList @('--snapshot-json', $SmokePath) `
        -Wait `
        -PassThru
    if ($smokeProcess.ExitCode -ne 0) {
        throw "Packaged snapshot smoke failed with exit code $($smokeProcess.ExitCode)."
    }
    $smoke = Get-Content -LiteralPath $SmokePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $smoke.updated_at_shanghai -or -not $smoke.call_counts) {
        throw 'Packaged snapshot smoke produced an invalid JSON payload.'
    }
    Remove-WorkspaceOutput $SmokePath

    Compress-Archive -LiteralPath @($ExePath, $RuntimePath) -DestinationPath $ArchivePath -CompressionLevel Optimal
    $hash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath $ChecksumPath -Value "$hash  $(Split-Path -Leaf $ArchivePath)" -Encoding ascii

    Write-Output "Built launcher: $ExePath"
    Write-Output "Built runtime:  $RuntimePath"
    Write-Output "Built archive:  $ArchivePath"
    Write-Output "SHA-256:        $hash"
}
finally {
    Pop-Location
}
