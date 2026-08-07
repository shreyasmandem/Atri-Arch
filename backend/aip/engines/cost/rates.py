"""Rate schedule for residential construction.

Rates are indicative composite rates for Indian residential work, expressed in
INR and benchmarked against CPWD Delhi Schedule of Rates conventions and current
market tender levels. They cover material, labour, wastage and plant, but not
contractor overhead, profit, professional fees or tax, which are applied
separately in the estimator so each is visible and adjustable.

Every rate carries an explicit uncertainty band. That band is not decoration: it
is what the Monte Carlo simulation samples to produce the P10/P50/P90 spread, and
it is the honest expression of the fact that a steel quotation in March is not a
steel quotation in September.

A firm should replace these with its own tendered rates. `RateSchedule` is
therefore data, loadable from JSON, rather than constants in code - and once a
firm has priced a few real projects, the residual learner corrects whatever bias
remains.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Trade(str, Enum):
    """Work packages, matching how an Indian contractor actually bills."""

    SUBSTRUCTURE = "substructure"
    STRUCTURE = "structure"
    MASONRY = "masonry"
    PLASTER = "plaster"
    FLOORING = "flooring"
    JOINERY = "joinery"
    PAINTING = "painting"
    WATERPROOFING = "waterproofing"
    ELECTRICAL = "electrical"
    PLUMBING = "plumbing"
    SANITARY = "sanitary"
    FALSE_CEILING = "false_ceiling"
    KITCHEN = "kitchen"
    EXTERNAL = "external"
    PRELIMINARIES = "preliminaries"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class FinishTier(str, Enum):
    """Specification level. Multiplies finish trades only, never structure."""

    ECONOMY = "economy"
    STANDARD = "standard"
    PREMIUM = "premium"
    LUXURY = "luxury"

    @property
    def multiplier(self) -> float:
        return {
            FinishTier.ECONOMY: 0.76,
            FinishTier.STANDARD: 1.0,
            FinishTier.PREMIUM: 1.45,
            FinishTier.LUXURY: 2.15,
        }[self]

    @property
    def label(self) -> str:
        return self.value.title()


#: Trades whose cost genuinely scales with specification. Structural concrete
#: does not get more expensive because the client chose Italian marble.
FINISH_SENSITIVE: frozenset[Trade] = frozenset(
    {
        Trade.FLOORING, Trade.JOINERY, Trade.PAINTING, Trade.SANITARY,
        Trade.FALSE_CEILING, Trade.KITCHEN, Trade.ELECTRICAL,
    }
)


@dataclass(frozen=True, slots=True)
class Rate:
    """One priced item of work."""

    code: str
    description: str
    unit: str                  # m3 | m2 | m | nos | kg | ls
    rate: float                # INR per unit, base region
    trade: Trade
    #: Symmetric relative uncertainty, e.g. 0.12 => +/-12% at one sigma.
    volatility: float = 0.10
    notes: str = ""

    def sample_rate(self, factor: float) -> float:
        return self.rate * factor


#: Regional cost indices relative to the Tamil Nadu / Chennai baseline.
REGION_MULTIPLIERS: dict[str, float] = {
    "IN-TN": 1.00,   # Chennai and Tamil Nadu - baseline
    "IN-KA": 1.08,   # Bengaluru
    "IN-KL": 1.05,   # Kerala
    "IN-AP": 0.97,
    "IN-TG": 1.04,   # Hyderabad
    "IN-MH": 1.20,   # Mumbai / Pune
    "IN-DL": 1.14,   # Delhi NCR
    "IN-HR": 1.10,
    "IN-UP": 0.92,
    "IN-GJ": 0.99,
    "IN-RJ": 0.94,
    "IN-MP": 0.91,
    "IN-WB": 0.96,   # Kolkata
    "IN-PB": 0.98,
    "IN-OD": 0.93,
    "IN-AS": 1.02,
    "IN-GA": 1.12,
    "IN-JK": 1.15,
}


def region_multiplier(region: str) -> float:
    return REGION_MULTIPLIERS.get(region.upper(), 1.0)


# ---------------------------------------------------------------------------
# Base schedule
# ---------------------------------------------------------------------------

BASE_RATES: tuple[Rate, ...] = (
    # -------------------------------------------------------- substructure --
    Rate("EXC.01", "Earthwork excavation in ordinary soil for foundations", "m3", 265, Trade.SUBSTRUCTURE, 0.16),
    Rate("PCC.01", "Plain cement concrete 1:4:8 levelling course", "m3", 5_400, Trade.SUBSTRUCTURE, 0.09),
    Rate("RCC.FTG", "RCC M25 in isolated footings, incl. formwork and placing", "m3", 9_900, Trade.SUBSTRUCTURE, 0.11),
    Rate("STL.FTG", "HYSD reinforcement Fe500 in footings, cut bent and placed", "kg", 88, Trade.SUBSTRUCTURE, 0.18,
         notes="Steel is the single most volatile input in Indian construction."),
    Rate("BKF.01", "Backfilling and compaction in layers", "m3", 190, Trade.SUBSTRUCTURE, 0.14),
    Rate("APR.01", "Anti-termite treatment to plinth and surroundings", "m2", 145, Trade.SUBSTRUCTURE, 0.12),
    # ------------------------------------------------------------ structure --
    Rate("RCC.COL", "RCC M25 in columns, incl. formwork", "m3", 11_200, Trade.STRUCTURE, 0.11),
    Rate("RCC.BM", "RCC M25 in beams, incl. formwork", "m3", 10_600, Trade.STRUCTURE, 0.11),
    Rate("RCC.SLB", "RCC M25 in suspended slabs, incl. formwork and propping", "m3", 10_100, Trade.STRUCTURE, 0.11),
    Rate("STL.SUP", "HYSD reinforcement Fe500 in superstructure", "kg", 88, Trade.STRUCTURE, 0.18),
    Rate("RCC.STR", "RCC staircase incl. formwork, waist slab and steps", "m3", 12_400, Trade.STRUCTURE, 0.12),
    Rate("RCC.LNT", "RCC lintels and sunshades over openings", "m3", 11_800, Trade.STRUCTURE, 0.12),
    # -------------------------------------------------------------- masonry --
    Rate("BRK.230", "Burnt clay brick masonry in CM 1:6, 230 mm thick", "m2", 1_580, Trade.MASONRY, 0.10),
    Rate("BRK.115", "Brick or AAC block masonry, 115 mm thick partitions", "m2", 940, Trade.MASONRY, 0.10),
    Rate("PAR.01", "Parapet wall, 115 mm with coping", "m", 1_450, Trade.MASONRY, 0.11),
    # -------------------------------------------------------------- plaster --
    Rate("PLS.INT", "Internal cement plaster 12 mm in CM 1:4", "m2", 285, Trade.PLASTER, 0.09),
    Rate("PLS.EXT", "External cement plaster 20 mm in two coats, CM 1:4", "m2", 375, Trade.PLASTER, 0.09),
    Rate("PLS.CEL", "Ceiling plaster 10 mm", "m2", 265, Trade.PLASTER, 0.09),
    # ------------------------------------------------------------- flooring --
    Rate("FLR.VIT", "Vitrified tile flooring 600x600 incl. bedding and grouting", "m2", 1_390, Trade.FLOORING, 0.13),
    Rate("FLR.GRN", "Granite flooring 18 mm, mirror polished", "m2", 2_950, Trade.FLOORING, 0.15),
    Rate("FLR.MRB", "Imported marble flooring incl. polishing", "m2", 4_600, Trade.FLOORING, 0.19),
    Rate("FLR.WDN", "Engineered wooden flooring on ply base", "m2", 2_450, Trade.FLOORING, 0.16),
    Rate("FLR.CER", "Anti-skid ceramic flooring for wet areas", "m2", 980, Trade.FLOORING, 0.12),
    Rate("FLR.KOT", "Kota / Tandur stone flooring, honed", "m2", 1_180, Trade.FLOORING, 0.13),
    Rate("FLR.IPS", "IPS / cement oxide flooring", "m2", 640, Trade.FLOORING, 0.11),
    Rate("WAL.TIL", "Glazed wall tiling to wet areas up to 2.1 m", "m2", 1_120, Trade.FLOORING, 0.12),
    Rate("SKT.01", "Skirting to match flooring, 100 mm", "m", 310, Trade.FLOORING, 0.12),
    # -------------------------------------------------------------- joinery --
    Rate("DOR.FLS", "Flush door shutter 35 mm with hardwood frame and hardware", "nos", 9_800, Trade.JOINERY, 0.14),
    Rate("DOR.MAIN", "Main entrance door in teak with carving and hardware", "nos", 41_000, Trade.JOINERY, 0.22),
    Rate("DOR.WPC", "WPC / PVC door for wet areas with frame", "nos", 6_400, Trade.JOINERY, 0.13),
    Rate("WIN.UPV", "UPVC glazed window with mesh and hardware", "m2", 6_700, Trade.JOINERY, 0.15),
    Rate("WIN.ALU", "Powder-coated aluminium glazed window", "m2", 5_400, Trade.JOINERY, 0.14),
    Rate("WIN.VNT", "Ventilator with louvre and glass", "m2", 4_100, Trade.JOINERY, 0.13),
    Rate("WDR.01", "Built-in wardrobe, laminated finish", "m2", 8_900, Trade.JOINERY, 0.18),
    # ------------------------------------------------------------- painting --
    Rate("PNT.INT", "Interior acrylic emulsion over putty and primer, 2 coats", "m2", 205, Trade.PAINTING, 0.11),
    Rate("PNT.EXT", "Exterior weatherproof emulsion over primer, 2 coats", "m2", 275, Trade.PAINTING, 0.12),
    Rate("PNT.CEL", "Ceiling paint, 2 coats", "m2", 175, Trade.PAINTING, 0.11),
    # -------------------------------------------------------- waterproofing --
    Rate("WPF.WET", "Waterproofing to wet area floors and skirting", "m2", 480, Trade.WATERPROOFING, 0.14),
    Rate("WPF.ROF", "Terrace waterproofing with brickbat coba and weathering course", "m2", 880, Trade.WATERPROOFING, 0.14),
    Rate("WPF.SMP", "Sump and overhead tank waterproofing", "m2", 620, Trade.WATERPROOFING, 0.14),
    # ----------------------------------------------------------- electrical --
    Rate("ELE.PNT", "Wiring point with modular switch, concealed conduit", "nos", 1_150, Trade.ELECTRICAL, 0.13),
    Rate("ELE.DBD", "Distribution board, MCBs and earthing", "nos", 22_000, Trade.ELECTRICAL, 0.15),
    Rate("ELE.LIT", "Light fittings allowance", "m2", 420, Trade.ELECTRICAL, 0.24,
         notes="Highly specification-dependent; wide band is intentional."),
    # ------------------------------------------------------------- plumbing --
    Rate("PLB.INT", "Internal CPVC water supply and PVC drainage per wet area", "nos", 27_500, Trade.PLUMBING, 0.14),
    Rate("PLB.EXT", "External drainage, chamber and connection to municipal line", "ls", 68_000, Trade.PLUMBING, 0.20),
    Rate("PLB.TNK", "Overhead tank, sump, pump and distribution", "ls", 96_000, Trade.PLUMBING, 0.17),
    # ------------------------------------------------------------- sanitary --
    Rate("SAN.BTH", "Sanitary fixtures and CP fittings per full bathroom", "nos", 44_000, Trade.SANITARY, 0.22),
    Rate("SAN.WC", "Sanitary fixtures for WC / powder room", "nos", 19_500, Trade.SANITARY, 0.20),
    # -------------------------------------------------------- false ceiling --
    Rate("FCL.GYP", "Gypsum false ceiling with GI framing and finish", "m2", 1_290, Trade.FALSE_CEILING, 0.13),
    Rate("FCL.PVC", "PVC / grid ceiling to service areas", "m2", 720, Trade.FALSE_CEILING, 0.12),
    # -------------------------------------------------------------- kitchen --
    Rate("KIT.CTR", "Granite kitchen counter with sink cut-out and edge", "m2", 4_300, Trade.KITCHEN, 0.15),
    Rate("KIT.MOD", "Modular kitchen base and wall units", "m2", 21_000, Trade.KITCHEN, 0.24,
         notes="Priced per square metre of kitchen floor area."),
    # ------------------------------------------------------------- external --
    Rate("EXT.CMP", "Compound wall 1.5 m high with plaster and paint", "m", 2_350, Trade.EXTERNAL, 0.14),
    Rate("EXT.GAT", "MS gate with fabrication and finish", "nos", 46_000, Trade.EXTERNAL, 0.18),
    Rate("EXT.PAV", "Paver block driveway and pathway on sand bed", "m2", 890, Trade.EXTERNAL, 0.13),
    Rate("EXT.LND", "Soft landscaping, soil and planting", "m2", 520, Trade.EXTERNAL, 0.22),
    Rate("RLG.SS", "Stainless steel and glass railing to stair and balcony", "m", 4_700, Trade.EXTERNAL, 0.17),
    Rate("RLG.MS", "MS railing with enamel paint", "m", 2_300, Trade.EXTERNAL, 0.14),
    # -------------------------------------------------------- preliminaries --
    Rate("PRE.SIT", "Site establishment, hoarding, water and power", "ls", 145_000, Trade.PRELIMINARIES, 0.20),
    Rate("PRE.SCF", "Scaffolding and access", "m2", 165, Trade.PRELIMINARIES, 0.15),
    Rate("PRE.CLN", "Debris removal and final cleaning", "m2", 95, Trade.PRELIMINARIES, 0.16),
)


@dataclass(slots=True)
class RateSchedule:
    """A priced schedule, regionally adjusted and specification-adjusted."""

    region: str = "IN-TN"
    currency: str = "INR"
    finish_tier: FinishTier = FinishTier.STANDARD
    rates: dict[str, Rate] = field(default_factory=dict)
    #: Applied on top of the regional index, e.g. for market escalation.
    escalation: float = 1.0
    source: str = "AIP indicative schedule, CPWD DSR conventions"

    def __post_init__(self) -> None:
        if not self.rates:
            self.rates = {rate.code: rate for rate in BASE_RATES}

    def factor_for(self, trade: Trade) -> float:
        """Total multiplier applied to a trade's base rate."""
        factor = region_multiplier(self.region) * self.escalation
        if trade in FINISH_SENSITIVE:
            factor *= self.finish_tier.multiplier
        return factor

    def rate_for(self, code: str) -> Rate | None:
        return self.rates.get(code)

    def price(self, code: str, quantity: float) -> tuple[float, Rate | None]:
        rate = self.rates.get(code)
        if rate is None:
            return 0.0, None
        return quantity * rate.rate * self.factor_for(rate.trade), rate

    def to_dict(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "currency": self.currency,
            "finish_tier": self.finish_tier.value,
            "escalation": self.escalation,
            "source": self.source,
            "region_multiplier": region_multiplier(self.region),
            "rates": [
                {
                    "code": r.code,
                    "description": r.description,
                    "unit": r.unit,
                    "base_rate": r.rate,
                    "applied_rate": round(r.rate * self.factor_for(r.trade), 2),
                    "trade": r.trade.value,
                    "volatility": r.volatility,
                }
                for r in self.rates.values()
            ],
        }

    @classmethod
    def from_file(cls, path: str | Path) -> RateSchedule:
        """Load a firm's own tendered rates, overriding the indicative schedule."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        rates = {rate.code: rate for rate in BASE_RATES}
        for item in data.get("rates", []):
            code = item["code"]
            existing = rates.get(code)
            rates[code] = Rate(
                code=code,
                description=item.get("description", existing.description if existing else code),
                unit=item.get("unit", existing.unit if existing else "nos"),
                rate=float(item["rate"]),
                trade=Trade(item.get("trade", existing.trade.value if existing else "preliminaries")),
                volatility=float(item.get("volatility", existing.volatility if existing else 0.12)),
                notes=item.get("notes", ""),
            )
        return cls(
            region=data.get("region", "IN-TN"),
            currency=data.get("currency", "INR"),
            finish_tier=FinishTier(data.get("finish_tier", "standard")),
            rates=rates,
            escalation=float(data.get("escalation", 1.0)),
            source=data.get("source", "firm-supplied schedule"),
        )


def default_schedule(
    region: str = "IN-TN", finish_tier: FinishTier = FinishTier.STANDARD
) -> RateSchedule:
    return RateSchedule(region=region, finish_tier=finish_tier)


#: Flooring specification by room type and tier - drives which rate code applies.
FLOOR_FINISH_CODES: dict[str, dict[str, str]] = {
    "economy": {
        "wet": "FLR.CER", "living": "FLR.VIT", "bedroom": "FLR.VIT",
        "service": "FLR.IPS", "outdoor": "FLR.KOT", "default": "FLR.VIT",
    },
    "standard": {
        "wet": "FLR.CER", "living": "FLR.VIT", "bedroom": "FLR.VIT",
        "service": "FLR.KOT", "outdoor": "FLR.KOT", "default": "FLR.VIT",
    },
    "premium": {
        "wet": "FLR.CER", "living": "FLR.GRN", "bedroom": "FLR.WDN",
        "service": "FLR.KOT", "outdoor": "FLR.KOT", "default": "FLR.VIT",
    },
    "luxury": {
        "wet": "FLR.CER", "living": "FLR.MRB", "bedroom": "FLR.WDN",
        "service": "FLR.GRN", "outdoor": "FLR.GRN", "default": "FLR.GRN",
    },
}
