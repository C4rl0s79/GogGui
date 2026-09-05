# Buduje paczkę źródłową GOG Library Managera dla Linuksa:
# dist\GOGManager-<wersja>-linux.zip
#
# W ZIP-ie nie ma binarki — są źródła, install.sh (venv + zależności),
# run.sh i DEPS.md z pakietami systemowymi per dystrybucja.
#
#   .\build_linux.ps1
#   .\build_linux.ps1 -OutDir D:\wydania
#
# Skrypty .sh zapisujemy z końcami linii LF i bitem wykonywalnym (0755) —
# inaczej po rozpakowaniu trzeba by robić `chmod +x` i `dos2unix`.
[CmdletBinding()]
param(
    [string]$OutDir = "dist"
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

# --- wersja z app.py --------------------------------------------------------

$appPath = Join-Path $PSScriptRoot "app.py"
$versionLine = Select-String -LiteralPath $appPath -Pattern '^APP_VERSION\s*=\s*"([^"]+)"'
if (-not $versionLine) { throw "Nie znalazłem APP_VERSION w $appPath" }
$version = $versionLine.Matches[0].Groups[1].Value
$name = "GOGManager-$version"
Write-Host "GOG Library Manager $version -> paczka linuksowa" -ForegroundColor Cyan

# --- co pakujemy ------------------------------------------------------------

$sourceDirs  = @("assets")
$excludeDirs = @("__pycache__", ".venv", "build", "dist", "_gog_cache", "json")
# Stan użytkownika (settings.json, logi, pobrane pliki) NIE trafia do paczki.
$rootFiles   = @("app.py", "README.md", "CHANGELOG.md")
$linuxDir    = Join-Path $PSScriptRoot "packaging\linux"

foreach ($d in $sourceDirs) {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $d))) {
        throw "Brak katalogu $d"
    }
}
if (-not (Test-Path -LiteralPath $linuxDir)) { throw "Brak packaging\linux" }

# --- lista wpisów: ścieżka w archiwum -> plik źródłowy -----------------------

$entries = [ordered]@{}

function Add-Tree([string]$dirName) {
    $root = Join-Path $PSScriptRoot $dirName
    Get-ChildItem -LiteralPath $root -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($PSScriptRoot.Length).TrimStart('\')
        foreach ($part in ($rel -split '\\')) {
            if ($excludeDirs -contains $part) { return }
        }
        if ($_.Extension -in @(".pyc", ".pyo", ".log", ".bak")) { return }
        $entries[($rel -replace '\\', '/')] = $_.FullName
    }
}

foreach ($d in $sourceDirs) { Add-Tree $d }

foreach ($f in $rootFiles) {
    $p = Join-Path $PSScriptRoot $f
    if (Test-Path -LiteralPath $p) { $entries[$f] = $p }
    else { Write-Warning "pomijam brakujący $f" }
}

Get-ChildItem -LiteralPath $linuxDir -File | ForEach-Object {
    $entries[$_.Name] = $_.FullName
}

Write-Host ("plików: {0}" -f $entries.Count)

# --- zapis ZIP-a ------------------------------------------------------------

if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir | Out-Null
}
$zipPath = Join-Path (Resolve-Path -LiteralPath $OutDir) "$name-linux.zip"
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

# Uprawnienia unixowe siedzą w górnych 16 bitach ExternalAttributes.
$modeExec = [Convert]::ToInt32("100755", 8) -shl 16
$modeFile = [Convert]::ToInt32("100644", 8) -shl 16

$zip = [System.IO.Compression.ZipFile]::Open(
    $zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($rel in $entries.Keys) {
        $src = $entries[$rel]
        $entry = $zip.CreateEntry(
            "$name/$rel", [System.IO.Compression.CompressionLevel]::Optimal)
        $isShell = $rel -like "*.sh"
        $entry.ExternalAttributes = if ($isShell) { $modeExec } else { $modeFile }
        $out = $entry.Open()
        try {
            if ($isShell) {
                # LF: sh nie strawi `\r` na końcu shebanga ani warunków
                $text = [IO.File]::ReadAllText($src) -replace "`r`n", "`n"
                $bytes = [Text.UTF8Encoding]::new($false).GetBytes($text)
            } else {
                $bytes = [IO.File]::ReadAllBytes($src)
            }
            $out.Write($bytes, 0, $bytes.Length)
        } finally { $out.Dispose() }
    }
} finally { $zip.Dispose() }

$sizeMb = [Math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB, 2)
Write-Host "`nGotowe: $zipPath ($sizeMb MB)" -ForegroundColor Green
Write-Host "Na Linuksie:  unzip $name-linux.zip && cd $name && ./install.sh" -ForegroundColor DarkGray
