param(
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$TestVersion = "",
    [string]$PythonPath = ".venv\Scripts\python.exe",
    [string]$InnoCompiler = "",
    [string]$BuildRoot = "",
    [switch]$InstallerOnly,
    [switch]$FastCompression,
    [switch]$Incremental
)

$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

if (!$InstallerOnly -and !(Test-Path $PythonPath)) {
    throw "Windows Python environment not found at $PythonPath"
}

if (!$InnoCompiler) {
    $InnoCandidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    $InnoCompiler = $InnoCandidates |
        Where-Object { $_ -and (Test-Path $_) } |
        Select-Object -First 1
    if (!$InnoCompiler) {
        $InnoCommand = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
        if ($InnoCommand) {
            $InnoCompiler = $InnoCommand.Source
        }
    }
}
if (!$InnoCompiler -or !(Test-Path $InnoCompiler)) {
    throw "Inno Setup 6 is not installed or its compiler could not be found."
}

if ($BuildRoot) {
    $BuildRoot = [System.IO.Path]::GetFullPath($BuildRoot)
    $DistPath = Join-Path $BuildRoot "dist"
    $WorkPath = Join-Path $BuildRoot "build"
} else {
    $DistPath = Join-Path (Get-Location) "dist"
    $WorkPath = Join-Path (Get-Location) "build"
}
New-Item -ItemType Directory -Force $DistPath | Out-Null
New-Item -ItemType Directory -Force $WorkPath | Out-Null

if (!$InstallerOnly) {
    & $PythonPath -m pip install -e ".[packaging-win]"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install the Windows packaging dependencies."
    }
}

$ProjectText = Get-Content "pyproject.toml" -Raw
Remove-Item Env:DTM_BUILD_VERSION_OVERRIDE -ErrorAction SilentlyContinue
if ($TestVersion) {
    $env:APP_VERSION = $TestVersion
    $env:DTM_BUILD_VERSION_OVERRIDE = $TestVersion
    Write-Host "Building local updater test version $TestVersion (pyproject.toml is unchanged)."
} elseif ($ProjectText -match '(?m)^version\s*=\s*"([^"]+)"') {
    $env:APP_VERSION = $Matches[1]
} else {
    throw "Could not read project version from pyproject.toml"
}

function Set-PackagedVersion {
    param(
        [string]$AppDirectory,
        [string]$Version
    )

    $Utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)

    # PyInstaller normally omits distribution metadata because the frozen app
    # uses the explicit build-version marker below. If metadata is present in a
    # future layout, keep it consistent, but its absence is not a build error.
    $MetadataFiles = @(
        Get-ChildItem (Join-Path $AppDirectory "_internal") -Directory -Filter "dtm_buildsheet-*.dist-info" |
            ForEach-Object { Join-Path $_.FullName "METADATA" } |
            Where-Object { Test-Path $_ }
    )
    foreach ($MetadataFile in $MetadataFiles) {
        $Metadata = Get-Content $MetadataFile -Raw
        $VersionPattern = [regex]'(?m)^Version:\s*.*$'
        $UpdatedMetadata = $VersionPattern.Replace($Metadata, "Version: $Version", 1)
        if ($UpdatedMetadata -eq $Metadata -and $Metadata -notmatch "(?m)^Version:\s*$([regex]::Escape($Version))$") {
            throw "Could not update packaged DTM version metadata at $MetadataFile."
        }
        [System.IO.File]::WriteAllText($MetadataFile, $UpdatedMetadata, $Utf8WithoutBom)
    }

    $BuildVersionFile = Join-Path $AppDirectory "_internal\dtm_buildsheet\_build_version.txt"
    if (!(Test-Path $BuildVersionFile)) {
        throw "Could not locate the packaged DTM build-version marker."
    }
    [System.IO.File]::WriteAllText($BuildVersionFile, $Version, $Utf8WithoutBom)
}

function Build-StartupLauncher {
    param([string]$AppDirectory)

    $CompilerCandidates = @(
        "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
        "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe"
    )
    $Compiler = $CompilerCandidates |
        Where-Object { Test-Path $_ } |
        Select-Object -First 1
    if (!$Compiler) {
        throw "The Windows C# compiler required for the startup launcher was not found."
    }

    $LauncherSource = Join-Path (Get-Location) "packaging\windows\startup_launcher.cs"
    $SplashImage = Join-Path (Get-Location) "packaging\icons\splash.png"
    $LauncherIcon = Join-Path (Get-Location) "packaging\icons\app.ico"
    $LauncherOutput = Join-Path $AppDirectory "DTM Vehicle Builder Launcher.exe"
    & $Compiler @(
        "/nologo",
        "/target:winexe",
        "/optimize+",
        "/platform:anycpu",
        "/reference:System.Drawing.dll",
        "/reference:System.Windows.Forms.dll",
        "/win32icon:$LauncherIcon",
        "/resource:$SplashImage,DTMStartupSplash",
        "/out:$LauncherOutput",
        $LauncherSource
    )
    if ($LASTEXITCODE -ne 0 -or !(Test-Path $LauncherOutput)) {
        throw "Could not build the Windows startup launcher."
    }
}

try {
    $env:DTM_BUILD_WORK_DIR = $WorkPath
    $env:DTM_BUILD_APP_DIR = Join-Path $DistPath "DTM Vehicle Builder"
    $env:DTM_BUILD_OUTPUT_DIR = $DistPath
    if ($FastCompression) {
        $env:DTM_BUILD_FAST_COMPRESSION = "1"
    }

    if (!$InstallerOnly) {
        $PyInstallerArguments = @("-m", "PyInstaller", "--noconfirm")
        if (!$Incremental) {
            $PyInstallerArguments += "--clean"
        }
        $PyInstallerArguments += @(
            "--distpath", $DistPath,
            "--workpath", $WorkPath,
            "packaging/pyinstaller/DTM_VehicleBuilder.spec"
        )
        & $PythonPath @PyInstallerArguments
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller could not build the Windows application."
        }
        Build-StartupLauncher -AppDirectory $env:DTM_BUILD_APP_DIR
    } elseif (
        !(Test-Path (Join-Path $env:DTM_BUILD_APP_DIR "DTM Vehicle Builder.exe")) -or
        !(Test-Path (Join-Path $env:DTM_BUILD_APP_DIR "DTM Vehicle Builder Launcher.exe"))
    ) {
        throw "The packaged Windows application or startup launcher is missing; a full build is required first."
    }

    if ($TestVersion) {
        Set-PackagedVersion -AppDirectory $env:DTM_BUILD_APP_DIR -Version $TestVersion
    }

    & $InnoCompiler "packaging\windows\installer.iss"
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup could not build the Windows installer."
    }

    if ($TestVersion) {
        $VersionedInstaller = Join-Path $DistPath "DTM_Vehicle_Builder_Setup-$TestVersion.exe"
        Copy-Item (Join-Path $DistPath "DTM_Vehicle_Builder_Setup.exe") $VersionedInstaller -Force
    }
} finally {
    Remove-Item Env:DTM_BUILD_VERSION_OVERRIDE -ErrorAction SilentlyContinue
    Remove-Item Env:DTM_BUILD_WORK_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:DTM_BUILD_APP_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:DTM_BUILD_OUTPUT_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:DTM_BUILD_FAST_COMPRESSION -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Build complete."
Write-Host "App output:"
Write-Host "  $(Join-Path $DistPath 'DTM Vehicle Builder')"
Write-Host "Installer:"
Write-Host "  $(Join-Path $DistPath 'DTM_Vehicle_Builder_Setup.exe')"
if ($TestVersion) {
    Write-Host "Updater test copy:"
    Write-Host "  $VersionedInstaller"
}
