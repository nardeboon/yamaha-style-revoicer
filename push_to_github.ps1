# push_to_github.ps1 — Push OR-700 converter to GitHub
# Usage: .\push_to_github.ps1

$ErrorActionPreference = "Stop"

$REPO_URL = "https://github.com/nardeboon/yamaha-style-revoicer.git"
$BRANCH = "main"
$BASE_DIR = "C:\Coding\py\YamahaStyleV3"

Write-Host "OR-700 Yamaha Style Converter — GitHub Push Script" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Check if git is installed
try {
    git --version | Out-Null
} catch {
    Write-Host "ERROR: git is not installed or not in PATH" -ForegroundColor Red
    exit 1
}

# Create a temporary directory for the repo
$TEMP_DIR = New-Item -ItemType Directory -Path ([System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), [System.IO.Path]::GetRandomFileName())) -Force
Write-Host "Working directory: $TEMP_DIR" -ForegroundColor Yellow
Set-Location $TEMP_DIR

# Initialize git repo
git init
git config user.name "Yamaha Style Converter"
git config user.email "nardeboon.photography@gmail.com"

Write-Host ""
Write-Host "Copying converter files..." -ForegroundColor Yellow

# Copy core converter files
$files = @(
    "revoice.py",
    "inspect_style.py",
    "extract_tables.py",
    "OR700_VOICE_TABLE.json",
    "OR700_DRUMKIT_TABLE.json",
    "CVP805_VOICE_TABLE.json",
    "CVP805_DRUMKIT_TABLE.json",
    "KIT_NOTE_ASSIGNMENTS.json",
    "NOTE_MAPS.json",
    "MELODIC_VOICE_MAP.json",
    "README.md",
    "DATA_REFERENCE.md"
)

foreach ($file in $files) {
    $src = Join-Path $BASE_DIR $file
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination .
        Write-Host "  ✓ $file" -ForegroundColor Green
    } else {
        Write-Host "  ⚠ $file (not found)" -ForegroundColor Yellow
    }
}

# Create .gitignore
@"
*.pyc
__pycache__/
*.prs
*.sty
*.pdf
.DS_Store
*.egg-info/
dist/
build/
OR700-Preset-Styles/
OR700-Preset-Styles-CVP805/
Iranian-Combined-CVP805/
"@ | Out-File -FilePath .gitignore -Encoding UTF8

Write-Host ""
Write-Host "Files in repo:" -ForegroundColor Yellow
Get-ChildItem -File | ForEach-Object { Write-Host "  - $($_.Name)" }

Write-Host ""
Write-Host "Adding files to git..." -ForegroundColor Yellow
git add .

Write-Host "Creating commit..." -ForegroundColor Yellow
git commit -m @"
Initial commit: OR-700 to CVP-805 style converter engine

Core components:
- revoice.py: SFF1 format parser and MIDI bank/program remapper
- inspect_style.py: Debug tool to inspect style files
- extract_tables.py: Extract voice/kit tables from Yamaha Data List PDFs

Data files:
- Voice and drum-kit tables for OR-700 and CVP-805
- Note mapping tables for kit remapping
- Melodic voice overrides

This tool converts Yamaha OR-700 preset styles to play correctly on
CVP-805 and other Clavinovas. Adaptable to any Yamaha keyboard pair
by generating new data files from official Data List PDFs.
"@

Write-Host ""
Write-Host "Adding remote: $REPO_URL" -ForegroundColor Yellow
git remote add origin $REPO_URL

Write-Host "Pushing to $BRANCH branch..." -ForegroundColor Yellow
git push -u origin $BRANCH

Write-Host ""
Write-Host "✓ SUCCESS! Repository pushed to:" -ForegroundColor Green
Write-Host "  $REPO_URL" -ForegroundColor Cyan
Write-Host ""
Write-Host "Cleaning up temporary directory..." -ForegroundColor Yellow
Set-Location -Path $BASE_DIR
Remove-Item -Path $TEMP_DIR -Recurse -Force

Write-Host "Done!" -ForegroundColor Green
