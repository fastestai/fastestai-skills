---
name: extracting-excel-images
description: "Extracts embedded images from Excel (.xlsx) files and maps them to cells. Produces a pure-text CSV + images folder. Use when asked to extract/export/separate images from Excel, or to map Excel images to cells."
---

# Extracting Excel Images

Extracts embedded images from `.xlsx` files, maps each image to its anchor cell, and outputs a CSV (with filenames in image cells) + an `images/` folder.

## Key Insight: Why Not openpyxl

openpyxl has poor support for reading embedded images. The reliable approach is to **parse the xlsx as a zip** and read the underlying XML directly:

- `xl/drawings/drawingN.xml` — contains anchor positions (`oneCellAnchor`/`twoCellAnchor`) with `<xdr:from>` specifying `(row, col)` and `<a:blip r:embed="rIdN"/>` referencing the image.
- `xl/drawings/_rels/drawingN.xml.rels` — maps `rIdN` → `../media/imageX.ext` (the actual image file path in the zip).
- `xl/media/` — contains the actual image files.
- `xl/worksheets/sheetN.xml` + `xl/sharedStrings.xml` — contain cell text values.

## Workflow

### Step 1: Inspect the Excel structure

Before writing any extraction code, unzip the xlsx and inspect the XML to understand:

```bash
mkdir -p /tmp/xlsx_inspect && cp INPUT.xlsx /tmp/xlsx_inspect/test.xlsx
cd /tmp/xlsx_inspect && unzip -o test.xlsx -d extracted > /dev/null 2>&1

# Check which sheets have drawings
ls extracted/xl/drawings/

# Inspect anchor structure (oneCellAnchor vs twoCellAnchor, which cols/rows have images)
head -100 extracted/xl/drawings/drawing1.xml

# Inspect rels to see image file mappings
cat extracted/xl/drawings/_rels/drawing1.xml.rels

# Inspect cell values and column headers
cat extracted/xl/sharedStrings.xml   # shared string table
cat extracted/xl/worksheets/sheet1.xml  # cell references
```

Key things to identify:
1. **Which columns contain images** (from `<xdr:col>` values in anchors)
2. **Which column has the row identifier** (e.g., SKU, product ID) for naming images
3. **Header row structure** to map column indices to meaningful names
4. **Anchor type**: `oneCellAnchor` (image pinned to one cell) vs `twoCellAnchor` (image spanning two cells) — both use `<xdr:from>` for the top-left cell

### Step 2: Write the extraction script

Build a Python script with these components (no external dependencies needed — stdlib only):

1. **Parse shared strings** from `xl/sharedStrings.xml`
2. **Parse cell values** from `xl/worksheets/sheetN.xml` using shared strings
3. **Parse image anchors** from `xl/drawings/drawingN.xml` + its `.rels` file
4. **Extract images** to `output/images/` with ASCII-only filenames: `{row_identifier}_{col_name}.{ext}`
5. **Write CSV** (UTF-8 BOM for Excel compatibility) with image filenames in place of images

### Step 3: Adapt naming to the specific table

The naming convention must be adapted per table:

- **Identify the ID column**: find the column that uniquely identifies each row (e.g., SKU, order number, product code). This becomes the filename prefix.
- **Map image columns to English names**: create a `COL_NAMES` dict mapping 0-indexed column numbers to short ASCII names (e.g., `{3: "style1", 8: "ref1"}`).
- **Image filename format**: `{row_id}_{col_name}.{ext}` — must be pure ASCII (no Chinese/Unicode in filenames).
- **Handle duplicates**: append `_1`, `_2` etc. if the same `(row_id, col_name)` appears multiple times.

## Code Template

The core XML namespaces needed:

```python
NS = {
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
}
```

Parsing image anchors (handles both anchor types):

```python
for anchor_tag in ["xdr:oneCellAnchor", "xdr:twoCellAnchor"]:
    for anchor in drawing_root.findall(anchor_tag, NS):
        frm = anchor.find("xdr:from", NS)
        col = int(frm.findtext("xdr:col", "0", NS))  # 0-indexed
        row = int(frm.findtext("xdr:row", "0", NS))  # 0-indexed
        blip = anchor.find(".//a:blip", NS)
        rid = blip.get(f'{{{NS["r"]}}}embed', "")
        # look up rid in the rels file to get image path
```

CSV output must use `encoding="utf-8-sig"` (BOM) so Excel opens it correctly with Chinese/Unicode content.

## Gotchas

- `r:link` attributes on `<a:blip>` are external URL references (e.g., to Pinterest), not local images. Only use `r:embed`.
- Some rels have `TargetMode="External"` — skip these, they point to URLs not local files.
- Row/col in anchors are **0-indexed**, but Excel cell references (like "C4") are 1-indexed (row) and letter-based (col).
- An image may be **reused** across multiple cells (same `rId` appearing in multiple anchors) — the same image bytes get written to different filenames.
- Multiple sheets may each have their own `drawingN.xml` — check `xl/worksheets/_rels/sheetN.xml.rels` to find which drawing belongs to which sheet.
