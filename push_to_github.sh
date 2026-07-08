#!/bin/bash
# push_to_github.sh — Push OR-700 converter to GitHub
# Usage: bash push_to_github.sh

set -e

REPO_URL="https://github.com/nardeboon/yamaha-style-revoicer.git"
BRANCH="main"

echo "OR-700 Yamaha Style Converter — GitHub Push Script"
echo "=================================================="
echo ""

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo "ERROR: git is not installed"
    exit 1
fi

# Create a temporary directory for the repo
TEMP_DIR=$(mktemp -d)
echo "Working directory: $TEMP_DIR"
cd "$TEMP_DIR"

# Initialize git repo
git init
git config user.name "Yamaha Style Converter"
git config user.email "nardeboon.photography@gmail.com"

echo ""
echo "Copying converter files..."

# Copy only OR-700 converter files (exclude PDFs, styles, PSR-specific work)
BASE_DIR="/c/Coding/py/YamahaStyleV3"

# Core converter files
cp "$BASE_DIR/revoice.py" .
cp "$BASE_DIR/inspect_style.py" .
cp "$BASE_DIR/extract_tables.py" .

# Data files (generated, not copyrighted)
cp "$BASE_DIR/OR700_VOICE_TABLE.json" .
cp "$BASE_DIR/OR700_DRUMKIT_TABLE.json" .
cp "$BASE_DIR/CVP805_VOICE_TABLE.json" .
cp "$BASE_DIR/CVP805_DRUMKIT_TABLE.json" .
cp "$BASE_DIR/KIT_NOTE_ASSIGNMENTS.json" .
cp "$BASE_DIR/NOTE_MAPS.json" .
cp "$BASE_DIR/MELODIC_VOICE_MAP.json" .

# Documentation
cp "$BASE_DIR/README.md" .
cp "$BASE_DIR/DATA_REFERENCE.md" .

# Create .gitignore
cat > .gitignore << 'EOF'
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
EOF

echo "Files included:"
ls -1
echo ""

# Add all files
git add .

# Create initial commit
git commit -m "Initial commit: OR-700 to CVP-805 style converter engine

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
by generating new data files from official Data List PDFs."

# Add remote and push
echo ""
echo "Adding remote: $REPO_URL"
git remote add origin "$REPO_URL"

echo "Pushing to $BRANCH branch..."
git push -u origin "$BRANCH"

echo ""
echo "SUCCESS! Repository pushed to:"
echo "  $REPO_URL"
echo ""
echo "Cleaning up temporary directory: $TEMP_DIR"
cd /
rm -rf "$TEMP_DIR"

echo "Done!"
