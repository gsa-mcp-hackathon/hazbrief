#!/bin/sh
# HB-102 Part A: render PDF pages (pdftoppm, 300 dpi, greyscale) and OCR them (tesseract,
# --psm 6, one uniform block, which keeps table rows together).  The 1991 evaluation is a scan
# with no text layer, and the corpus parse's OCR drops runs of words on many lines, so every
# quotation and table value in evaluation_1991.md was read from these renderings.
# Usage: sh ocr_pages.sh PDF OUTDIR PAGE [PAGE ...]
set -u
PDF="$1"; OUT="$2"; shift 2
PDF=$(cd "$(dirname "$PDF")" && pwd)/$(basename "$PDF")
mkdir -p "$OUT"
# This tesseract build (5.5.0) fails to open an absolute /tmp path ("failed to open locally")
# and then reads the PNG bytes as a list of file names; it opens a relative path, so OCR runs
# from inside OUT.
cd "$OUT" || exit 2
for p in "$@"; do
  pdftoppm -r 300 -gray -f "$p" -l "$p" -png "$PDF" "p$p"
  img=$(ls p"$p"-*.png | head -1)
  tesseract "$img" "p$p" --psm 6 > /dev/null 2>&1
  echo "page $p: exit $? $(wc -c < "p$p.txt") chars"
done
