# Synthetic dataset

> [!] **SYNTHETIC DATA — NOT REAL.** Every value is fabricated for
> demonstration only. Safe for external sharing; contains no CUI / ITAR
> content.

## What's here

- **`synthetic_data.py`** — the deterministic, pure-stdlib generator.
  Re-running with the same seed reproduces the dataset exactly. The
  seeder service calls this; don't rewrite it.
- **`classification.yml`** — per-table / per-column sensitivity labels
  (Routine / Sensitive / Confidential), applied at seed time and
  surfaced in the catalog — *classify before exposure*.
- **`sample/`** — a committed reference copy of the generated dataset
  (seed=42), so the shape is inspectable without running anything.

## Regenerate

```bash
python -c "from synthetic_data import generate_artemis_procurement as g; g('sample', seed=42)"
```
