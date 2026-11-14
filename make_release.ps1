<#
  Build a new Wanderpin version.

    .\make_release.ps1 -Version 1.0.1 -Notes "Fixed route speed"

  Sets VERSION in app.py, builds dist\Wanderpin-Setup.zip and its .sha256.
  If the GitHub CLI (gh) is installed and signed in, it can publish the release
  for you; otherwise it prints the two files to upload by hand.
  Installed copies see the new version the next time they open.
#>
param(
  [Parameter(Mandatory = $true)][string]$Version,
  [string]$Notes = ""
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$Version = $Version.TrimStart('v', 'V')
if ($Version -notmatch '^\d+(\.\d+){1,3}$') { throw "Version must look like 1.2.3" }

# ---- read settings from app.py
$appPy = Join-Path $root 'app.py'
$src = [IO.File]::ReadAllText($appPy)
$repo = [regex]::Match($src, 'UPDATE_REPO\s*=\s*"([^"]+)"').Groups[1].Value
$old = [regex]::Match($src, 'VERSION\s*=\s*"([^"]+)"').Groups[1].Value
if (-not $repo -or $repo -like 'YOUR-GITHUB-NAME*') {
  throw "Set UPDATE_REPO in app.py to your GitHub repo (like yourname/wanderpin) first."
}
function VerKey($v) { ($v.Split('.') | ForEach-Object { '{0:D6}' -f [int]$_ }) -join '.' }
if ((VerKey $Version) -le (VerKey $old)) { throw "New version $Version must be higher than the current $old." }

# ---- bump version
$src = [regex]::Replace($src, '(VERSION\s*=\s*")[^"]+(")', "`${1}$Version`${2}")
[IO.File]::WriteAllText($appPy, $src, (New-Object Text.UTF8Encoding $false))
Write-Host "Version $old -> $Version"

# ---- build the zip
$stageRoot = Join-Path $env:TEMP "wanderpin-release-$([guid]::NewGuid().ToString('N'))"
$stage = Join-Path $stageRoot 'Wanderpin-Setup'
New-Item -ItemType Directory -Force (Join-Path $stage 'static') | Out-Null
Get-ChildItem -LiteralPath $root -Filter *.py | Copy-Item -Destination $stage
Copy-Item -LiteralPath (Join-Path $root 'static\index.html') -Destination (Join-Path $stage 'static')
Copy-Item -LiteralPath (Join-Path $root 'README.md') -Destination $stage
Copy-Item -LiteralPath (Join-Path $root 'installer\install.bat'), (Join-Path $root 'installer\uninstall.bat') -Destination $stage
if (Test-Path -LiteralPath (Join-Path $root 'requirements.txt')) {
  Copy-Item -LiteralPath (Join-Path $root 'requirements.txt') -Destination $stage
}

$dist = Join-Path $root 'dist'
New-Item -ItemType Directory -Force $dist | Out-Null
$zip = Join-Path $dist 'Wanderpin-Setup.zip'
Remove-Item -LiteralPath $zip, "$zip.sha256" -ErrorAction SilentlyContinue
Compress-Archive -Path $stage -DestinationPath $zip
Remove-Item -LiteralPath $stageRoot -Recurse -Force
$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$zip.sha256", "$hash  Wanderpin-Setup.zip`n")
Write-Host "Built $zip"
Write-Host "SHA-256 $hash"

# ---- publish
$tag = "v$Version"
if (Get-Command gh -ErrorAction SilentlyContinue) {
  $answer = Read-Host "Publish $tag to github.com/$repo now? (y/n)"
  if ($answer -eq 'y') {
    if (-not $Notes) { $Notes = "Wanderpin $Version" }
    gh release create $tag $zip "$zip.sha256" --repo $repo --title "Wanderpin $Version" --notes $Notes
    if ($LASTEXITCODE -eq 0) { Write-Host "Published. Installed copies will offer the update next time they open." }
    exit $LASTEXITCODE
  }
}
Write-Host ""
Write-Host "To publish by hand:"
Write-Host "  1. Open https://github.com/$repo/releases/new"
Write-Host "  2. Tag: $tag     Title: Wanderpin $Version"
Write-Host "  3. Write what changed in the description (users see it in the app)"
Write-Host "  4. Attach BOTH files from $($dist):"
Write-Host "       Wanderpin-Setup.zip"
Write-Host "       Wanderpin-Setup.zip.sha256"
Write-Host "  5. Click Publish release"
