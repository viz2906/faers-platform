#!/bin/bash
# download.sh — Download FAERS quarterly data files
# Usage: ./scripts/download.sh 2026q1
set -euo pipefail

QUARTER="${1:-2026q1}"
DATA_DIR="${FAERS_DATA_DIR:-./data/raw}"
BASE_URL="https://fis.fda.gov/content/Exports"

# Normalize quarter to URL format (some quarters use Q, some q)
# FDA uses mixed case: 2024Q4, 2025q1, etc. We normalize input.
QUARTER_LOWER=$(echo "$QUARTER" | tr '[:upper:]' '[:lower:]')

# Build URLs
ASCII_URL="${BASE_URL}/faers_ascii_${QUARTER_LOWER}.zip"
XML_URL="${BASE_URL}/faers_xml_${QUARTER_LOWER}.zip"

# Create directory
QUARTER_DIR="${DATA_DIR}/${QUARTER_LOWER}"
mkdir -p "${QUARTER_DIR}"

echo "======================================================"
echo "  FDA FAERS Data Downloader"
echo "  Quarter: ${QUARTER_LOWER}"
echo "  Destination: ${QUARTER_DIR}"
echo "======================================================"

# Download ASCII (primary — smaller, faster to parse)
python scripts/download_faers.py "${QUARTER_LOWER}"


# Unzip
ASCII_FILE="${QUARTER_DIR}/faers_ascii_${QUARTER_LOWER}.zip"
ASCII_EXTRACT="${QUARTER_DIR}/ascii"
if [ -d "${ASCII_EXTRACT}" ]; then
    echo "[SKIP] Already extracted: ${ASCII_EXTRACT}"
else
    echo "[UNZIP] Extracting ASCII files..."
    unzip -q "${ASCII_FILE}" -d "${QUARTER_DIR}/"
    
    # FDA ZIP structure varies — find the ascii folder
    # Sometimes it's ascii/, sometimes ASCII/, sometimes flat
    if [ ! -d "${ASCII_EXTRACT}" ]; then
        FOUND=$(find "${QUARTER_DIR}" -type d -iname "ascii" | head -1)
        if [ -n "$FOUND" ]; then
            mv "$FOUND" "${ASCII_EXTRACT}" 2>/dev/null || true
        fi
    fi
    echo "[OK] Extracted to: ${ASCII_EXTRACT}"
fi

# List extracted files
echo ""
echo "======================================================"
echo "  Extracted Files:"
find "${ASCII_EXTRACT}" -name "*.txt" | sort | while read f; do
    SIZE=$(du -sh "$f" | cut -f1)
    ROWS=$(wc -l < "$f")
    echo "  ${SIZE}  $(basename $f)  (${ROWS} rows)"
done
echo "======================================================"
echo ""
echo "[DONE] Quarter ${QUARTER_LOWER} ready for ingestion."
echo "Next: python ingestion/quarterly_pipeline.py --quarter ${QUARTER_LOWER}"
