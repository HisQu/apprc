<#
One-line install script (OLIS) for a private GitHub release.
Expected one-line install command template:
  irm <PUBLIC_SCRIPT_URL> | iex
Requirements: Windows x86-64, Windows PowerShell 5.1 or PowerShell 7, and gh authenticated with gh auth login.
1. Download the latest native setup executable and SHA256SUMS.
2. Verify the matching checksum before executing any downloaded file.
3. Run the native setup executable, which performs the installation.
4. Remove temporary downloads and preserve the native setup exit status.
When evaluated interactively, failure throws and sets LASTEXITCODE without
closing the PowerShell session. Running this OLIS as a file returns that code.
#>

& {
    param([bool]$RunAsFile, [object[]]$SetupArgs)
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $false
    $temporary = $null
    $result = 1
    $failure = $null
    try {
        if ($env:OS -ne 'Windows_NT' -or
            ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64' -and $env:PROCESSOR_ARCHITEW6432 -ne 'AMD64')) {
            throw 'This OLIS requires Windows x86-64.'
        }
        $repository = '@@REPOSITORY@@'
        $setup = '@@SETUP@@'
        $path = Join-Path ([IO.Path]::GetTempPath()) ('apprc-olis-' + [guid]::NewGuid().ToString('N'))
        $temporary = (New-Item -ItemType Directory -Path $path).FullName
        if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
            throw 'OLIS requires gh authenticated with gh auth login.'
        }
        gh release download -R $repository -p $setup -p SHA256SUMS -D $temporary
        if ($LASTEXITCODE -ne 0) { throw 'GitHub release download failed. Check gh auth login and release assets.' }
        $name = [regex]::Escape($setup)
        $entries = @(Get-Content -LiteralPath (Join-Path $temporary 'SHA256SUMS') |
            Where-Object { $_ -cmatch ('^\S+\s+' + $name + '(\s|$)') })
        if ($entries.Count -ne 1 -or $entries[0] -cnotmatch ('^[0-9a-fA-F]{64}  ' + $name + '$')) {
            throw 'The native setup has no unique valid checksum entry.'
        }
        $expected = $entries[0].Substring(0, 64)
        $executable = Join-Path $temporary $setup
        if ((Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash -ne $expected) {
            throw 'Native setup checksum verification failed. Rerun the one-line install command.'
        }
        # > Forward setup options only after verifying the downloaded executable.
        & $executable @SetupArgs
        $result = $LASTEXITCODE
        if ($result -ne 0) { $failure = "Native setup failed with exit code $result." }
    } catch {
        $failure = $_
    } finally {
        if ($temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue }
    }
    $global:LASTEXITCODE = $result
    if ($RunAsFile) {
        if ($failure) { Write-Error $failure -ErrorAction Continue }
        exit $result
    }
    if ($failure) { throw $failure }
} ($MyInvocation.MyCommand.CommandType -eq 'ExternalScript') $args
