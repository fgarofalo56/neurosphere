"""Synthetic Artemis supply-chain / procurement dataset (SAP-shaped).

The NASA customer call asked for a worked Artemis supply-chain example but no
public Artemis procurement data exists, so deliverables must be grounded in
*synthetic* data. This generates a realistic, **clearly-synthetic** SAP-style
procurement dataset as CSVs (SAP field names: EBELN/EBELP/MATNR/LIFNR/…) so the
white paper / demo can show real federated-query and supply-risk scenarios
without touching any controlled data.

Deterministic (seeded) → reproducible and content-verifiable. Pure stdlib (csv
+ random + datetime); no pandas dependency. ITAR/CUI-safe: every vendor name is
fictitious and flagged ``SYNTHETIC``.
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

import logging

logger = logging.getLogger("synthetic_data")

# Artemis "Ignition Day" programs called out on the NASA call.
_PROGRAMS = ["SR1-Freedom", "Moon-Base", "Artemis-3", "Gateway", "EGS-Ground"]

# Material families for a launch/space-flight supply chain (synthetic).
_FAMILIES = [
    ("Avionics", ("Flight computer module", "Inertial measurement unit", "RAD-hard FPGA board")),
    ("Propulsion", ("Turbopump impeller", "Combustion chamber liner", "Cryo valve assembly")),
    ("Structures", ("Composite interstage panel", "Titanium thrust bracket", "Al-Li dome gore")),
    ("Thermal", ("Ablative TPS tile", "MLI blanket set", "Heat-pipe radiator panel")),
    ("Power", ("Li-ion battery module", "Solar array wing", "Power distribution unit")),
    ("EEE", ("Space-grade DC-DC converter", "Rad-hard memory array", "Connector backshell")),
    ("Software", ("Flight software license", "Ground command toolkit", "Telemetry decoder")),
    ("GSE", ("Mobile launcher umbilical", "Cryo transfer line", "Pad water deluge nozzle")),
]

# Fictitious supplier names (clearly synthetic).
_VENDOR_STEMS = [
    "Apex",
    "Northwind",
    "Helios",
    "Vertex",
    "Sterling",
    "Cascade",
    "Orbital",
    "Granite",
    "Meridian",
    "Cobalt",
    "Summit",
    "Ironwood",
    "Beacon",
    "Polaris",
    "Redstone",
    "Lattice",
    "Sentinel",
    "Forge",
    "Tessera",
    "Aurora",
    "Keystone",
    "Vanguard",
    "Quartz",
    "Atlas",
]
_VENDOR_KINDS = ["Aerospace", "Systems", "Composites", "Microelectronics", "Propulsion", "Labs"]
_STATES = ["AL", "TX", "FL", "CA", "OH", "CO", "VA", "MD", "WA", "UT"]


def _seeded(seed: int) -> random.Random:
    return random.Random(seed)


def generate_artemis_procurement(
    out_dir: str | Path,
    *,
    seed: int = 42,
    n_vendors: int = 26,
    n_materials: int = 60,
    n_pos: int = 240,
) -> dict:
    """Write vendors/materials/purchase_orders/supply_risk CSVs + a data dictionary.

    Returns ``{paths, counts, out_dir}``. Deterministic for a given ``seed``.
    """
    rng = _seeded(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ── vendors (LFA1-ish) ──
    vendors = []
    for i in range(n_vendors):
        vid = 100000 + i
        name = f"{rng.choice(_VENDOR_STEMS)} {rng.choice(_VENDOR_KINDS)} (SYNTHETIC)"
        sole = rng.random() < 0.22  # ~22% sole-source — a key supply risk
        vendors.append(
            {
                "LIFNR": vid,  # SAP vendor number
                "NAME1": name,
                "CAGE_CODE": f"{rng.randint(10000, 99999)}",
                "REGIO": rng.choice(_STATES),
                "LAND1": "US",
                "SOLE_SOURCE": "X" if sole else "",
                "PAST_PERF_SCORE": round(rng.uniform(2.6, 5.0), 1),  # 1-5
                "SMALL_BUSINESS": "X" if rng.random() < 0.45 else "",
            }
        )

    # ── materials (MARA-ish) ──
    materials = []
    for i in range(n_materials):
        fam, parts = rng.choice(_FAMILIES)
        matnr = f"NSN-{rng.randint(1000, 9999)}-{rng.randint(100000, 999999)}"
        crit = rng.choices(["Critical", "Essential", "Routine"], weights=[0.25, 0.4, 0.35])[0]
        lead = {
            "Critical": rng.randint(120, 420),
            "Essential": rng.randint(45, 180),
            "Routine": rng.randint(7, 60),
        }[crit]
        materials.append(
            {
                "MATNR": matnr,
                "MAKTX": f"{rng.choice(parts)}",
                "MATKL": fam,  # material group
                "PROGRAM": rng.choice(_PROGRAMS),
                "CRITICALITY": crit,
                "STD_LEAD_TIME_DAYS": lead,
                "STD_UNIT_COST_USD": round(
                    rng.uniform(150, 2_500_000)
                    * (3.0 if crit == "Critical" else 1.0 if crit == "Essential" else 0.3),
                    2,
                ),
                "UOM": rng.choice(["EA", "EA", "EA", "SET", "LOT"]),
            }
        )

    vend_ids = [v["LIFNR"] for v in vendors]
    sole_by_mat = {m["MATNR"]: rng.choice(vend_ids) for m in materials if rng.random() < 0.3}

    # ── purchase orders (EKKO/EKPO-ish, one line each for simplicity) ──
    base = date(2025, 10, 1)
    pos = []
    for i in range(n_pos):
        mat = rng.choice(materials)
        matnr = mat["MATNR"]
        lifnr = sole_by_mat.get(matnr) or rng.choice(vend_ids)
        qty = rng.randint(1, 40)
        order_dt = base + timedelta(days=rng.randint(0, 240))
        std_lead = int(mat["STD_LEAD_TIME_DAYS"])
        promised = order_dt + timedelta(days=std_lead)
        # delay model: criticality + sole-source raise slip probability
        slip_p = 0.18 + (0.22 if mat["CRITICALITY"] == "Critical" else 0.0)
        slip_p += 0.15 if matnr in sole_by_mat else 0.0
        delay = 0
        if rng.random() < slip_p:
            delay = rng.randint(5, 130)
        # occasional "pad anomaly" shock the customer mentioned ("when pads blow up")
        anomaly = rng.random() < 0.03
        if anomaly:
            delay += rng.randint(60, 240)
        actual = promised + timedelta(days=delay) if delay else promised
        status = (
            "Delivered"
            if actual <= base + timedelta(days=250)
            else ("Open-Late" if delay else "Open")
        )
        unit_cost = float(mat["STD_UNIT_COST_USD"]) * rng.uniform(0.9, 1.25)
        pos.append(
            {
                "EBELN": f"45{100000 + i}",  # PO number
                "EBELP": "00010",  # line item
                "MATNR": matnr,
                "MAKTX": mat["MAKTX"],
                "LIFNR": lifnr,
                "PROGRAM": mat["PROGRAM"],
                "CRITICALITY": mat["CRITICALITY"],
                "MENGE": qty,  # quantity
                "MEINS": mat["UOM"],
                "NETPR": round(unit_cost, 2),  # net price / unit
                "NETWR": round(unit_cost * qty, 2),  # net value
                "WAERS": "USD",
                "EINDT": promised.isoformat(),  # delivery date (promised)
                "BEDAT": order_dt.isoformat(),  # PO date
                "ACTUAL_DELIVERY": actual.isoformat(),
                "DELAY_DAYS": delay,
                "PAD_ANOMALY": "X" if anomaly else "",
                "STATUS": status,
            }
        )

    # ── derived supply-risk per material (the supply-chain story) ──
    risk_rows = []
    for m in materials:
        matnr = m["MATNR"]
        mat_pos = [p for p in pos if p["MATNR"] == matnr]
        if not mat_pos:
            continue
        delays = [p["DELAY_DAYS"] for p in mat_pos]
        late = sum(1 for d in delays if d > 0)
        avg_delay = round(sum(delays) / len(delays), 1)
        sole = matnr in sole_by_mat
        score = min(
            100,
            int(
                (40 if m["CRITICALITY"] == "Critical" else 15)
                + (25 if sole else 0)
                + min(35, avg_delay)
            ),
        )
        risk_rows.append(
            {
                "MATNR": matnr,
                "MAKTX": m["MAKTX"],
                "PROGRAM": m["PROGRAM"],
                "CRITICALITY": m["CRITICALITY"],
                "SOLE_SOURCE": "X" if sole else "",
                "PO_COUNT": len(mat_pos),
                "LATE_PO_COUNT": late,
                "AVG_DELAY_DAYS": avg_delay,
                "RISK_SCORE": score,
                "RISK_TIER": "High" if score >= 70 else "Medium" if score >= 40 else "Low",
            }
        )
    risk_rows.sort(key=lambda r: r["RISK_SCORE"], reverse=True)

    def _write(name: str, rows: list[dict]) -> str:
        path = out / name
        with open(path, "w", newline="", encoding="utf-8") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
        return str(path)

    paths = {
        "vendors": _write("artemis_vendors.csv", vendors),
        "materials": _write("artemis_materials.csv", materials),
        "purchase_orders": _write("artemis_purchase_orders.csv", pos),
        "supply_risk": _write("artemis_supply_risk.csv", risk_rows),
    }

    # ── data dictionary (Markdown) ──
    dd = out / "artemis_procurement_DATA_DICTIONARY.md"
    dd.write_text(_data_dictionary(len(vendors), len(materials), len(pos), len(risk_rows)), "utf-8")
    paths["data_dictionary"] = str(dd)

    counts = {
        "vendors": len(vendors),
        "materials": len(materials),
        "purchase_orders": len(pos),
        "supply_risk": len(risk_rows),
        "high_risk_materials": sum(1 for r in risk_rows if r["RISK_TIER"] == "High"),
        "sole_source_materials": len(sole_by_mat),
    }
    logger.info(
        "synthetic.artemis_procurement.generated out_dir=%s %s", out, counts
    )
    return {"paths": paths, "counts": counts, "out_dir": str(out)}


def _data_dictionary(n_v: int, n_m: int, n_po: int, n_r: int) -> str:
    return f"""# Artemis Supply-Chain Procurement — Synthetic Dataset

> **SYNTHETIC DATA — NOT REAL NASA PROCUREMENT.** Every vendor, material, price,
> and date is fabricated for demonstration only (the NASA call confirmed no
> public Artemis procurement data exists). Vendor names carry a `(SYNTHETIC)`
> suffix. Safe for external sharing; contains no CUI/ITAR content.

Generated for the API-first data-marketplace worked example: shows how a
zero-copy API/metadata layer over an SAP procurement source surfaces
supply-chain risk (sole-source exposure, lead-time slips, launch-pad anomalies)
for the Artemis "Ignition Day" programs.

## Files
| File | Rows | SAP analogue | Purpose |
|------|------|--------------|---------|
| `artemis_vendors.csv` | {n_v} | LFA1 (vendor master) | Suppliers, CAGE codes, sole-source + small-business flags, past performance |
| `artemis_materials.csv` | {n_m} | MARA (material master) | Parts by family/program/criticality, standard lead time + unit cost |
| `artemis_purchase_orders.csv` | {n_po} | EKKO/EKPO (PO header/line) | Orders with promised vs actual delivery, delay days, pad-anomaly flag |
| `artemis_supply_risk.csv` | {n_r} | derived | Per-material risk score/tier from sole-source + criticality + delay history |

## Key fields (SAP names)
- **EBELN / EBELP** — purchase order number / line item
- **MATNR / MAKTX** — material number / description
- **LIFNR / NAME1** — vendor number / name
- **MATKL / PROGRAM / CRITICALITY** — material group / Artemis program / criticality
- **MENGE / MEINS / NETPR / NETWR / WAERS** — qty / UoM / unit price / net value / currency
- **BEDAT / EINDT / ACTUAL_DELIVERY / DELAY_DAYS** — PO date / promised date / actual / slip
- **SOLE_SOURCE / PAD_ANOMALY** — single-supplier exposure / launch-pad shock event
- **RISK_SCORE / RISK_TIER** — derived supply-chain risk (High ≥70, Medium ≥40, Low)

## Suggested API / marketplace scenarios
1. *Federated query:* "Which Critical, sole-source materials on Artemis-3 have an
   average delay > 30 days?" — joins materials × supply_risk without copying SAP.
2. *Real-time streaming:* PO status changes pushed through an APIM endpoint.
3. *Lineage / governance:* classify confidential vs routine procurement records
   (the call's data-quality concern) before exposing them in the catalog.
"""
