<#
One-line install script (OLIS) for a private GitHub release.
Expected one-line install command template:
  Stable: irm <PUBLIC_SCRIPT_URL> | iex
  Beta:   & ([scriptblock]::Create((irm <PUBLIC_SCRIPT_URL>))) --beta
  RC:     & ([scriptblock]::Create((irm <PUBLIC_SCRIPT_URL>))) --release-candidate
Requirements: Windows x86-64, Windows PowerShell 5.1 or PowerShell 7, and gh authenticated with gh auth login.
1. Download the selected native setup executable and SHA256SUMS.
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
        # == Select the release and prepare setup arguments
        # > Consume one installer channel flag and forward the other arguments in order.
        $channel = ''
        $regularRequested = $false
        $readOptions = $true
        $forwardedArgs = @(foreach ($argument in $SetupArgs) {
            if (-not $readOptions -or $argument -ceq '--') {
                $readOptions = $false
                $argument
                continue
            }
            $requested = switch -CaseSensitive -Regex ($argument) {
                '^(-b|--beta)$' { 'b' }
                '^(-rc|--release-candidate)$' { 'rc' }
            }
            if ($requested) {
                if ($channel) {
                    throw 'Choose one release channel: --beta or --release-candidate.'
                }
                $channel = $requested
                continue
            }
            if ($argument -ceq '--regular') { $regularRequested = $true }
            $argument
        })
        $SetupArgs = $forwardedArgs

        $releaseTagArgs = @()
        if ($channel) {
            if ($regularRequested) {
                throw 'A beta or RC install uses Preview and cannot be combined with --regular.'
            }

            # > GitHub marks both channels as prereleases. The tag distinguishes them.
            $releaseFields = '.[] | [.tag_name, .prerelease, .draft] | @tsv'
            $releaseRows = gh api --paginate "repos/$repository/releases?per_page=100" --jq $releaseFields
            if ($LASTEXITCODE -ne 0) {
                throw 'GitHub release lookup failed. Check gh auth login and repository access.'
            }
            $number = '(0|[1-9][0-9]*)'
            $tagPattern = '^v{0}\.{0}\.{0}{1}{0}$' -f $number, $channel

            # > Compare the numeric components so b10 sorts after b2.
            $selected = $releaseRows | ForEach-Object {
                $tag, $prerelease, $draft = $_ -split "`t", 3
                if ($prerelease -ceq 'true' -and $draft -ceq 'false' -and
                    $tag -cmatch $tagPattern) {
                    [pscustomobject]@{
                        Tag = $tag
                        Major = [bigint]$Matches[1]
                        Minor = [bigint]$Matches[2]
                        Patch = [bigint]$Matches[3]
                        Sequence = [bigint]$Matches[4]
                    }
                }
            } | Sort-Object -Property Major, Minor, Patch, Sequence -Descending |
                Select-Object -First 1

            if (-not $selected) {
                throw "No published prerelease with a vX.Y.Z${channel}N tag was found in $repository."
            }
            $releaseTagArgs = @($selected.Tag)
            $SetupArgs = @('--preview') + $SetupArgs
        }

        # > Fetch both assets from the same release. With no tag, gh selects latest stable.
        gh release download @releaseTagArgs -R $repository -p $setup -p SHA256SUMS -D $temporary
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
