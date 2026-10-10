"""Quantity takeoff, pricing, risk simulation and cash flow.

The estimate is built in five stages, each of which is separately inspectable:

1. **Takeoff** - quantities derived from the model geometry. Wall area net of
   openings, concrete volumes from the actual column grid, wet-area counts from
   the actual room schedule. Nothing is inferred from floor area alone.
2. **Pricing** - each quantity meets a rate from the schedule, adjusted for
   region and specification.
3. **Additions** - overhead and profit, contingency, professional fees and tax,
   applied as visible separate lines rather than buried in the rates.
4. **Risk simulation** - a Monte Carlo over rate volatility and quantity
   tolerance producing a P10/P50/P90 band, because a single number implies a
   precision that does not exist.
5. **Calibration** - a learned correction from the firm's own completed
   projects, which is how the system gets better at predicting *this* firm's
   costs rather than the industry average.
"""

from __future__ import annotations

import contextlib
import math
import random
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from aip.core.logging import get_logger, log_event
from aip.domain.brief import ClientBrief, DesignStyle
from aip.domain.plan import FloorPlan, OpeningKind, RoomType, WallKind
from aip.engines.cost.rates import (
    FLOOR_FINISH_CODES,
    FinishTier,
    RateSchedule,
    Trade,
    default_schedule,
)

logger = get_logger("aip.cost")


class CostLineItem(BaseModel):
    """One priced row of the bill of quantities."""

    code: str
    description: str
    trade: str
    unit: str
    quantity: float
    rate: float
    amount: float
    volatility: float = 0.1
    basis: str = ""          # how the quantity was derived - the audit trail

    @property
    def share(self) -> float:
        return self.amount


class CashFlowPeriod(BaseModel):
    month: int
    label: str
    outflow: float
    cumulative: float
    percent_complete: float


class RiskFactor(BaseModel):
    name: str
    likelihood: float = Field(ge=0.0, le=1.0)
    cost_impact_percent: float
    schedule_impact_weeks: float
    mitigation: str = ""


class CostEstimate(BaseModel):
    """A complete, defensible cost prediction."""

    plan_id: str = ""
    currency: str = "INR"
    region: str = "IN-TN"
    finish_tier: str = "standard"

    built_area_m2: float = 0.0
    line_items: list[CostLineItem] = Field(default_factory=list)

    works_subtotal: float = 0.0
    overhead_profit: float = 0.0
    contingency: float = 0.0
    professional_fees: float = 0.0
    tax: float = 0.0
    total: float = 0.0
    rate_per_m2: float = 0.0

    p10: float = 0.0
    p50: float = 0.0
    p90: float = 0.0
    confidence: float = 0.7
    calibrated: bool = False
    calibration_factor: float = 1.0

    by_trade: dict[str, float] = Field(default_factory=dict)
    cash_flow: list[CashFlowPeriod] = Field(default_factory=list)
    duration_months: float = 0.0
    delay_probability: float = 0.0
    expected_delay_weeks: float = 0.0
    risks: list[RiskFactor] = Field(default_factory=list)

    assumptions: list[str] = Field(default_factory=list)
    summary: str = ""

    @property
    def uncertainty_band_percent(self) -> float:
        if self.p50 <= 0:
            return 0.0
        return round((self.p90 - self.p10) / self.p50 * 100, 1)

    def top_trades(self, n: int = 6) -> list[tuple[str, float]]:
        return sorted(self.by_trade.items(), key=lambda kv: kv[1], reverse=True)[:n]


# ---------------------------------------------------------------------------
# Takeoff
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Takeoff:
    """Raw quantities measured off the model."""

    quantities: dict[str, float] = field(default_factory=dict)
    basis: dict[str, str] = field(default_factory=dict)

    def add(self, code: str, quantity: float, basis: str = "") -> None:
        if quantity <= 0:
            return
        self.quantities[code] = self.quantities.get(code, 0.0) + quantity
        if basis and code not in self.basis:
            self.basis[code] = basis


#: Reinforcement intensity in kg per cubic metre of concrete, by element.
STEEL_RATIOS: dict[str, float] = {
    "footing": 78.0, "column": 185.0, "beam": 165.0, "slab": 92.0, "stair": 130.0,
}

#: Electrical points per room type - drives the wiring package.
ELECTRICAL_POINTS: dict[RoomType, int] = {
    RoomType.LIVING: 14, RoomType.DRAWING: 12, RoomType.FAMILY: 11, RoomType.DINING: 8,
    RoomType.KITCHEN: 14, RoomType.MASTER_BEDROOM: 12, RoomType.BEDROOM: 10,
    RoomType.GUEST_BEDROOM: 9, RoomType.CHILDREN_BEDROOM: 10, RoomType.STUDY: 9,
    RoomType.HOME_OFFICE: 10, RoomType.BATHROOM: 5, RoomType.TOILET: 3,
    RoomType.POWDER: 3, RoomType.PUJA: 3, RoomType.STORE: 2, RoomType.UTILITY: 5,
    RoomType.CORRIDOR: 4, RoomType.FOYER: 4, RoomType.LOBBY: 4, RoomType.STAIRCASE: 4,
    RoomType.BALCONY: 2, RoomType.VERANDAH: 3, RoomType.TERRACE: 2, RoomType.GARAGE: 4,
    RoomType.GYM: 8, RoomType.HOME_THEATRE: 12, RoomType.LIBRARY: 8, RoomType.LAUNDRY: 4,
}


def take_off(plan: FloorPlan, brief: ClientBrief, tier: FinishTier) -> Takeoff:
    """Derive every billable quantity from the geometry."""
    t = Takeoff()
    grid = plan.column_grid
    levels = max(1, len(plan.levels))
    footprint = plan.footprint_area
    built = plan.total_built_area

    # ---------------------------------------------------------- structure --
    if grid is not None:
        columns = grid.column_count
        col_area = grid.column_size[0] * grid.column_size[1]
        col_height = plan.building_height
        col_volume = columns * col_area * col_height
        t.add("RCC.COL", col_volume, f"{columns} columns x {col_area:.3f} m2 x {col_height:.2f} m")
        t.add("STL.SUP", col_volume * STEEL_RATIOS["column"], "185 kg/m3 in columns")

        # Beams run along every grid line on every suspended level.
        env = plan.envelope()
        beam_length = (
            (len(grid.y_spacings) + 1) * env.width + (len(grid.x_spacings) + 1) * env.height
        ) * levels
        beam_volume = beam_length * 0.23 * grid.beam_depth
        t.add("RCC.BM", beam_volume, f"{beam_length:.0f} m of beam at 0.23 x {grid.beam_depth:.2f} m")
        t.add("STL.SUP", beam_volume * STEEL_RATIOS["beam"], "165 kg/m3 in beams")

        # Footings sized from the tributary load and the soil bearing capacity.
        tributary = (footprint / max(columns, 1)) if columns else 4.0
        load_kn = tributary * levels * 12.0            # ~12 kN/m2 service load
        bearing = max(80.0, plan.site.soil_bearing_kn_m2)
        footing_area = max(0.9, load_kn / bearing)
        footing_volume = columns * footing_area * 0.45
        t.add("RCC.FTG", footing_volume, f"{columns} footings of {footing_area:.2f} m2 x 0.45 m deep")
        t.add("STL.FTG", footing_volume * STEEL_RATIOS["footing"], "78 kg/m3 in footings")
        t.add("EXC.01", footing_volume * 2.6, "Excavation at 2.6x the footing volume incl. working space")
        t.add("PCC.01", columns * footing_area * 0.1, "100 mm levelling course under footings")
        t.add("BKF.01", footing_volume * 1.3, "Backfill around completed footings")

    # Slabs: one per suspended level, plus the roof.
    slab_thickness = grid.slab_thickness if grid else 0.125
    slab_volume = built * slab_thickness
    t.add("RCC.SLB", slab_volume, f"{built:.0f} m2 of slab at {slab_thickness * 1000:.0f} mm")
    t.add("STL.SUP", slab_volume * STEEL_RATIOS["slab"], "92 kg/m3 in slabs")

    for level in plan.levels:
        for stair in level.staircases:
            volume = stair.going * stair.width * 0.20 + stair.step_count * stair.tread * stair.riser * stair.width / 2
            t.add("RCC.STR", volume, f"Staircase of {stair.step_count} steps")
            t.add("STL.SUP", volume * STEEL_RATIOS["stair"], "130 kg/m3 in staircase")

    # ------------------------------------------------------------ masonry --
    exterior_area = 0.0
    interior_area = 0.0
    partition_area = 0.0
    for wall in plan.all_walls:
        if wall.kind is WallKind.EXTERIOR:
            exterior_area += wall.net_area
        elif wall.thickness >= 0.2:
            interior_area += wall.net_area
        else:
            partition_area += wall.net_area

    # Interior walls are shared between two rooms, so the raw sum double-counts.
    interior_area *= 0.5
    partition_area *= 0.5

    t.add("BRK.230", exterior_area + interior_area, "External and 230 mm internal walls, net of openings")
    t.add("BRK.115", partition_area, "115 mm partitions, net of openings")
    t.add("RCC.LNT", (exterior_area + interior_area + partition_area) * 0.008,
          "Lintels and sunshades at 0.8% of wall area")

    # ------------------------------------------------------------ plaster --
    internal_faces = exterior_area + interior_area * 2 + partition_area * 2
    t.add("PLS.INT", internal_faces, "All internal wall faces")
    t.add("PLS.EXT", exterior_area, "External wall outer face")
    t.add("PLS.CEL", built, "Soffit of all slabs")
    t.add("PNT.INT", internal_faces, "Internal walls")
    t.add("PNT.EXT", exterior_area, "External walls")
    t.add("PNT.CEL", built, "Ceilings")

    # ----------------------------------------------------------- flooring --
    finish_map = FLOOR_FINISH_CODES[tier.value]
    wet_rooms = 0
    full_baths = 0
    wc_only = 0
    for room in plan.all_rooms:
        if room.type is RoomType.SHAFT:
            continue
        category = _finish_category(room.type)
        code = finish_map.get(category, finish_map["default"])
        t.add(code, room.area, f"{room.display_name()} and similar")
        t.add("SKT.01", room.perimeter_length * 0.85, "Skirting less door openings")

        if room.type.is_wet:
            wet_rooms += 1
            t.add("WAL.TIL", room.perimeter_length * 2.1, f"Wet area dado to 2.1 m in {room.display_name()}")
            t.add("WPF.WET", room.area + room.perimeter_length * 0.3, "Wet area tanking with upstand")
            t.add("PLB.INT", 1, "One plumbing set per wet area")
        if room.type is RoomType.BATHROOM:
            full_baths += 1
        elif room.type in {RoomType.TOILET, RoomType.POWDER}:
            wc_only += 1

    t.add("SAN.BTH", full_baths, "Full bathrooms")
    t.add("SAN.WC", wc_only, "WC and powder rooms")

    # ------------------------------------------------------------ joinery --
    doors = {"flush": 0, "main": 0, "wpc": 0}
    window_area = {"glazed": 0.0, "ventilator": 0.0}
    for opening in plan.all_openings:
        if opening.kind is OpeningKind.MAIN_DOOR:
            doors["main"] += 1
        elif opening.kind.is_door:
            doors["flush"] += 1
        elif opening.kind is OpeningKind.VENTILATOR:
            window_area["ventilator"] += opening.area
        elif opening.kind.is_glazed:
            window_area["glazed"] += opening.area

    # Wet-area doors are WPC rather than flush; approximate one per wet room.
    wpc = min(doors["flush"], wet_rooms)
    doors["flush"] -= wpc
    doors["wpc"] = wpc

    t.add("DOR.MAIN", doors["main"], "Main entrance")
    t.add("DOR.FLS", doors["flush"], "Internal flush doors")
    t.add("DOR.WPC", doors["wpc"], "Wet area doors")
    window_code = "WIN.UPV" if tier in {FinishTier.PREMIUM, FinishTier.LUXURY} else "WIN.ALU"
    t.add(window_code, window_area["glazed"], "Glazed windows by area")
    t.add("WIN.VNT", window_area["ventilator"], "Ventilators by area")

    bedrooms = plan.rooms_of(
        RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.GUEST_BEDROOM, RoomType.CHILDREN_BEDROOM
    )
    if brief.budget.includes_furniture or tier in {FinishTier.PREMIUM, FinishTier.LUXURY}:
        t.add("WDR.01", sum(2.4 * 2.1 for _ in bedrooms), "One wardrobe per bedroom, 2.4 x 2.1 m")

    # ------------------------------------------------------------ services --
    points = sum(ELECTRICAL_POINTS.get(r.type, 4) for r in plan.all_rooms)
    t.add("ELE.PNT", points, f"{points} points across {len(plan.all_rooms)} rooms")
    t.add("ELE.DBD", levels, "One distribution board per level")
    t.add("ELE.LIT", built, "Light fitting allowance by area")
    t.add("PLB.EXT", 1, "External drainage connection")
    t.add("PLB.TNK", 1, "Sump, overhead tank and pump set")

    # ------------------------------------------------- ceilings and kitchen --
    if tier is not FinishTier.ECONOMY:
        ceiling_rooms = [
            r for r in plan.all_rooms
            if r.type.is_habitable and not r.type.is_outdoor
        ]
        t.add("FCL.GYP", sum(r.area for r in ceiling_rooms) * 0.7, "False ceiling to 70% of habitable area")
        t.add("FCL.PVC", sum(r.area for r in plan.all_rooms if r.type.is_wet), "Service area ceilings")

    kitchen = plan.first_room_of(RoomType.KITCHEN)
    if kitchen is not None:
        t.add("KIT.CTR", kitchen.perimeter_length * 0.28, "Counter at 0.6 m deep over ~47% of perimeter")
        t.add("KIT.MOD", kitchen.area, "Modular units priced per m2 of kitchen")

    # ------------------------------------------------------------ external --
    roof_area = plan.levels[-1].built_area if plan.levels else footprint
    t.add("WPF.ROF", roof_area, "Terrace waterproofing and weathering course")
    t.add("WPF.SMP", 24.0, "Sump and overhead tank internal faces")

    site = plan.site
    if site.boundary:
        from aip.domain.geometry import perimeter as poly_perimeter

        boundary = poly_perimeter(site.boundary)
        t.add("EXT.CMP", max(0.0, boundary - 4.0), "Compound wall less gate opening")
        t.add("EXT.GAT", 1, "Main gate")
        open_area = max(0.0, site.plot_area - footprint)
        t.add("EXT.PAV", open_area * 0.35, "Driveway and paths over 35% of open ground")
        t.add("EXT.LND", open_area * 0.45, "Soft landscaping over 45% of open ground")

    railing_length = sum(
        min(r.bbox.width, r.bbox.height)
        for r in plan.all_rooms
        if r.type in {RoomType.BALCONY, RoomType.TERRACE}
    )
    stair_railing = sum(s.going * 1.2 for lv in plan.levels for s in lv.staircases)
    railing_code = "RLG.SS" if tier in {FinishTier.PREMIUM, FinishTier.LUXURY} else "RLG.MS"
    t.add(railing_code, railing_length + stair_railing, "Balcony and staircase railings")

    parapet = 0.0
    if plan.levels:
        env = plan.envelope()
        parapet = 2 * (env.width + env.height)
    t.add("PAR.01", parapet, "Terrace parapet around the roof perimeter")

    # ------------------------------------------------------ preliminaries --
    t.add("PRE.SIT", 1, "Site establishment")
    t.add("PRE.SCF", exterior_area * 1.15, "Scaffolding to external faces")
    t.add("PRE.CLN", built, "Debris removal and handover cleaning")
    t.add("APR.01", footprint, "Anti-termite treatment to plinth")

    return t


def _finish_category(room_type: RoomType) -> str:
    if room_type.is_wet:
        return "wet"
    if room_type.is_outdoor:
        return "outdoor"
    if room_type in {
        RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.GUEST_BEDROOM,
        RoomType.CHILDREN_BEDROOM, RoomType.STUDY, RoomType.HOME_OFFICE,
    }:
        return "bedroom"
    if room_type in {
        RoomType.LIVING, RoomType.DRAWING, RoomType.FAMILY, RoomType.DINING,
        RoomType.FOYER, RoomType.LOBBY, RoomType.LIBRARY, RoomType.HOME_THEATRE,
    }:
        return "living"
    return "service"


# ---------------------------------------------------------------------------
# Estimation
# ---------------------------------------------------------------------------

OVERHEAD_PROFIT_PERCENT = 15.0
PROFESSIONAL_FEE_PERCENT = 7.0
GST_PERCENT = 18.0


def estimate_cost(
    plan: FloorPlan,
    brief: ClientBrief | None = None,
    *,
    schedule: RateSchedule | None = None,
    monte_carlo_runs: int = 4000,
    calibration_factor: float = 1.0,
    seed: int | None = 42,
) -> CostEstimate:
    """Full cost prediction for a plan."""
    brief = brief or ClientBrief()
    # A plan may carry its own specification decision - the cost worker in the
    # consensus protocol sets one when it steps the finish down to meet budget.
    # Reading only the brief made that mutation a silent no-op, so the protocol
    # proposed a step-down, measured no saving, and rejected its own fix.
    tier = _infer_tier(brief)
    override = plan.metadata.get("finish_tier")
    if override:
        # An unrecognised override falls back to the inferred tier rather than
        # failing the estimate: the plan is still costable, just at the default
        # specification.
        with contextlib.suppress(ValueError):
            tier = FinishTier(str(override).lower())
    schedule = schedule or default_schedule(
        region=_infer_region(brief), finish_tier=tier
    )

    takeoff = take_off(plan, brief, tier)
    line_items: list[CostLineItem] = []
    by_trade: dict[str, float] = {}

    for code, quantity in sorted(takeoff.quantities.items()):
        rate = schedule.rate_for(code)
        if rate is None:
            continue
        applied = rate.rate * schedule.factor_for(rate.trade)
        amount = quantity * applied
        line_items.append(
            CostLineItem(
                code=code,
                description=rate.description,
                trade=rate.trade.value,
                unit=rate.unit,
                quantity=round(quantity, 3),
                rate=round(applied, 2),
                amount=round(amount, 2),
                volatility=rate.volatility,
                basis=takeoff.basis.get(code, ""),
            )
        )
        by_trade[rate.trade.value] = by_trade.get(rate.trade.value, 0.0) + amount

    works = sum(item.amount for item in line_items)
    overhead = works * OVERHEAD_PROFIT_PERCENT / 100
    contingency_pct = brief.budget.contingency_percent if brief.budget else 7.5
    contingency = (works + overhead) * contingency_pct / 100
    fees = (works + overhead) * PROFESSIONAL_FEE_PERCENT / 100
    pre_tax = works + overhead + contingency + fees
    tax = pre_tax * GST_PERCENT / 100
    total = (pre_tax + tax) * calibration_factor

    built = plan.total_built_area or 1.0

    p10, p50, p90 = _simulate(
        line_items, overhead, contingency_pct, fees_pct=PROFESSIONAL_FEE_PERCENT,
        runs=monte_carlo_runs, calibration=calibration_factor, seed=seed,
    )

    duration = _duration_months(plan, brief)
    risks = _risk_register(plan, brief, total)
    delay_probability, expected_delay = _delay_forecast(risks)

    estimate = CostEstimate(
        plan_id=plan.id,
        currency=schedule.currency,
        region=schedule.region,
        finish_tier=tier.value,
        built_area_m2=round(built, 2),
        line_items=line_items,
        works_subtotal=round(works, 2),
        overhead_profit=round(overhead, 2),
        contingency=round(contingency, 2),
        professional_fees=round(fees, 2),
        tax=round(tax, 2),
        total=round(total, 2),
        rate_per_m2=round(total / built, 2),
        p10=round(p10, 2),
        p50=round(p50, 2),
        p90=round(p90, 2),
        calibrated=abs(calibration_factor - 1.0) > 1e-6,
        calibration_factor=round(calibration_factor, 4),
        by_trade={k: round(v, 2) for k, v in sorted(by_trade.items(), key=lambda kv: -kv[1])},
        duration_months=duration,
        delay_probability=delay_probability,
        expected_delay_weeks=expected_delay,
        risks=risks,
    )
    estimate.cash_flow = _cash_flow(total, duration, schedule.currency)
    estimate.confidence = _confidence(estimate, plan)
    estimate.assumptions = _assumptions(schedule, tier, contingency_pct)
    estimate.summary = _summarise(estimate, brief)

    log_event(
        logger, "cost.estimated",
        plan=plan.id, total=estimate.total, rate_per_m2=estimate.rate_per_m2,
        items=len(line_items), band_pct=estimate.uncertainty_band_percent,
    )
    return estimate


def _simulate(
    line_items: list[CostLineItem],
    overhead: float,
    contingency_pct: float,
    fees_pct: float,
    *,
    runs: int,
    calibration: float,
    seed: int | None,
) -> tuple[float, float, float]:
    """Monte Carlo over rate volatility and quantity tolerance.

    Rates are sampled log-normally, which respects the fact that construction
    prices cannot go negative and that their upside tail is fatter than their
    downside. Quantities carry a smaller symmetric tolerance representing
    measurement and detailing variance. Correlated market movement is modelled by
    a shared shock so the simulation does not understate the spread by assuming
    every trade moves independently - which is the classic error that produces
    deceptively tight confidence intervals.
    """
    if not line_items:
        return 0.0, 0.0, 0.0

    rng = random.Random(seed)
    totals: list[float] = []
    base_works = sum(i.amount for i in line_items)
    overhead_ratio = overhead / base_works if base_works else 0.15

    for _ in range(max(200, runs)):
        market_shock = rng.gauss(0.0, 0.055)      # common escalation factor
        works = 0.0
        for item in line_items:
            rate_factor = math.exp(rng.gauss(0.0, item.volatility) + market_shock)
            qty_factor = 1.0 + rng.gauss(0.0, 0.045)
            works += item.amount * rate_factor * max(0.5, qty_factor)

        oh = works * overhead_ratio
        cont = (works + oh) * contingency_pct / 100
        fee = (works + oh) * fees_pct / 100
        pre_tax = works + oh + cont + fee
        totals.append((pre_tax + pre_tax * GST_PERCENT / 100) * calibration)

    totals.sort()
    n = len(totals)
    return totals[int(n * 0.10)], totals[int(n * 0.50)], totals[min(n - 1, int(n * 0.90))]


def _duration_months(plan: FloorPlan, brief: ClientBrief) -> float:
    """Construction duration from area, levels and specification complexity."""
    built = max(plan.total_built_area, 20.0)
    # Empirical: roughly 45 m2 per month of finished residential work for a
    # single crew, with economies of scale that flatten on larger projects.
    base = 3.5 + (built / 45.0) ** 0.88
    base *= 1.0 + 0.12 * max(0, len(plan.levels) - 1)
    tier = _infer_tier(brief)
    base *= {
        FinishTier.ECONOMY: 0.9, FinishTier.STANDARD: 1.0,
        FinishTier.PREMIUM: 1.18, FinishTier.LUXURY: 1.4,
    }[tier]
    return round(min(base, 48.0), 1)


def _cash_flow(total: float, duration_months: float, currency: str) -> list[CashFlowPeriod]:
    """S-curve cash flow.

    Construction spend is not linear: mobilisation and substructure are slow,
    the superstructure and finishes phase consumes the bulk, and handover tapers.
    A logistic curve reproduces that shape closely enough for a client to plan
    their draw-down against, which is what this output is for.
    """
    months = max(1, int(round(duration_months)))
    periods: list[CashFlowPeriod] = []
    previous = 0.0
    for month in range(1, months + 1):
        x = month / months
        # Logistic S-curve centred at 50% with a realistic steepness.
        progress = 1.0 / (1.0 + math.exp(-9.0 * (x - 0.5)))
        # Normalise so the curve starts at 0 and ends at 1 exactly.
        lo = 1.0 / (1.0 + math.exp(4.5))
        hi = 1.0 / (1.0 + math.exp(-4.5))
        progress = (progress - lo) / (hi - lo)
        cumulative = total * progress
        periods.append(
            CashFlowPeriod(
                month=month,
                label=f"Month {month}",
                outflow=round(cumulative - previous, 2),
                cumulative=round(cumulative, 2),
                percent_complete=round(progress * 100, 1),
            )
        )
        previous = cumulative
    return periods


def _risk_register(plan: FloorPlan, brief: ClientBrief, total: float) -> list[RiskFactor]:
    """Named, quantified project risks rather than a single contingency number."""
    risks: list[RiskFactor] = [
        RiskFactor(
            name="Material price escalation",
            likelihood=0.55,
            cost_impact_percent=6.0,
            schedule_impact_weeks=0.0,
            mitigation="Lock steel and cement rates early, or include a price-variation clause.",
        ),
        RiskFactor(
            name="Monsoon disruption",
            likelihood=0.65 if 8.0 <= plan.site.latitude <= 25.0 else 0.35,
            cost_impact_percent=1.5,
            schedule_impact_weeks=3.0,
            mitigation="Complete substructure and roof before the monsoon window.",
        ),
        RiskFactor(
            name="Labour availability",
            likelihood=0.4,
            cost_impact_percent=3.0,
            schedule_impact_weeks=2.5,
            mitigation="Contract crews in advance and avoid harvest-season starts.",
        ),
        RiskFactor(
            name="Client-driven design change",
            likelihood=0.7 if not brief.must_haves else 0.5,
            cost_impact_percent=5.5,
            schedule_impact_weeks=3.0,
            mitigation="Freeze the design before foundations; price variations formally.",
        ),
        RiskFactor(
            name="Statutory approval delay",
            likelihood=0.35,
            cost_impact_percent=1.0,
            schedule_impact_weeks=5.0,
            mitigation="Submit for sanction in parallel with detailed design.",
        ),
    ]

    if plan.site.soil_bearing_kn_m2 < 120:
        risks.append(
            RiskFactor(
                name="Poor soil bearing capacity",
                likelihood=0.6,
                cost_impact_percent=4.5,
                schedule_impact_weeks=2.0,
                mitigation="Commission a geotechnical investigation before foundation design.",
            )
        )
    if len(plan.levels) > 2:
        risks.append(
            RiskFactor(
                name="Multi-storey coordination complexity",
                likelihood=0.45,
                cost_impact_percent=2.5,
                schedule_impact_weeks=2.0,
                mitigation="Sequence services coordination ahead of slab casting.",
            )
        )
    if brief.budget.is_specified and total > brief.budget.ceiling:
        risks.append(
            RiskFactor(
                name="Budget overrun already forecast",
                likelihood=0.85,
                cost_impact_percent=round((total / brief.budget.amount - 1) * 100, 1),
                schedule_impact_weeks=0.0,
                mitigation="Value-engineer the specification or reduce built-up area before tender.",
            )
        )
    return risks


def _delay_forecast(risks: list[RiskFactor]) -> tuple[float, float]:
    """Probability of any material delay, and its expected magnitude.

    Risks are treated as independent, so the chance of *no* delay is the product
    of each not occurring. That is a simplification - real delays correlate - but
    it is transparent and errs toward caution.
    """
    delaying = [r for r in risks if r.schedule_impact_weeks > 0]
    if not delaying:
        return 0.0, 0.0
    no_delay = 1.0
    expected = 0.0
    for risk in delaying:
        no_delay *= 1.0 - risk.likelihood
        expected += risk.likelihood * risk.schedule_impact_weeks
    return round(1.0 - no_delay, 3), round(expected, 1)


def _confidence(estimate: CostEstimate, plan: FloorPlan) -> float:
    """How much the critic layer should trust this estimate."""
    confidence = 0.85
    if estimate.uncertainty_band_percent > 40:
        confidence -= 0.15
    if not plan.column_grid:
        confidence -= 0.12          # structural quantities were approximated
    if len(estimate.line_items) < 20:
        confidence -= 0.1
    if estimate.calibrated:
        confidence += 0.08          # corrected by this firm's own history
    return round(max(0.35, min(0.95, confidence)), 3)


def _assumptions(schedule: RateSchedule, tier: FinishTier, contingency: float) -> list[str]:
    return [
        f"Rates are {schedule.source}, indexed to {schedule.region} "
        f"(factor {schedule.to_dict()['region_multiplier']:.2f}).",
        f"Specification level assumed '{tier.label}'.",
        f"Contractor overhead and profit at {OVERHEAD_PROFIT_PERCENT:.0f}%.",
        f"Contingency at {contingency:.1f}% and professional fees at {PROFESSIONAL_FEE_PERCENT:.0f}%.",
        f"GST at {GST_PERCENT:.0f}% on the works contract value.",
        "Excludes land cost, statutory approval fees, loose furniture and external electrical connection charges.",
        "Quantities are taken off the model geometry; a site survey may alter substructure quantities.",
    ]


def _summarise(estimate: CostEstimate, brief: ClientBrief) -> str:
    parts = [
        f"Estimated {estimate.total:,.0f} {estimate.currency} for "
        f"{estimate.built_area_m2:,.0f} m2, i.e. {estimate.rate_per_m2:,.0f} per m2 "
        f"at '{estimate.finish_tier}' specification in {estimate.region}.",
        f"The 80% confidence range is {estimate.p10:,.0f} to {estimate.p90:,.0f} "
        f"({estimate.uncertainty_band_percent:.0f}% band), from a Monte Carlo over "
        f"rate volatility and quantity tolerance.",
    ]
    top = estimate.top_trades(3)
    if top:
        parts.append(
            "Largest packages: "
            + ", ".join(
                f"{Trade(name).label} {amount / estimate.total:.0%}" for name, amount in top
            )
            + "."
        )
    parts.append(
        f"Programme {estimate.duration_months:.0f} months, with a "
        f"{estimate.delay_probability:.0%} chance of some delay "
        f"(expected {estimate.expected_delay_weeks:.0f} weeks if it occurs)."
    )
    if brief.budget.is_specified:
        ratio = estimate.total / brief.budget.amount
        if ratio > 1.02:
            parts.append(
                f"This is {ratio - 1:.0%} above the stated budget of "
                f"{brief.budget.amount:,.0f}."
            )
        else:
            parts.append(
                f"This sits within the stated budget of {brief.budget.amount:,.0f} "
                f"({ratio:.0%} of it)."
            )
    if estimate.calibrated:
        parts.append(
            f"Corrected by a factor of {estimate.calibration_factor:.3f} learned "
            f"from this practice's completed projects."
        )
    return " ".join(parts)


def _infer_tier(brief: ClientBrief) -> FinishTier:
    """Choose a specification level from budget intensity and stated style."""
    explicit = brief.metadata.get("finish_tier")
    if explicit:
        try:
            return FinishTier(str(explicit).lower())
        except ValueError:
            pass

    luxury_styles = {
        DesignStyle.LUXURY_CLASSICAL, DesignStyle.ART_DECO,
        DesignStyle.INDO_SARACENIC, DesignStyle.RAJASTHANI_HAVELI,
    }
    if any(s in luxury_styles for s in brief.style.styles):
        return FinishTier.LUXURY

    if brief.budget.is_specified and brief.target_built_area > 0:
        per_m2 = brief.budget.amount / brief.target_built_area
        if per_m2 < 22_000:
            return FinishTier.ECONOMY
        if per_m2 < 38_000:
            return FinishTier.STANDARD
        if per_m2 < 65_000:
            return FinishTier.PREMIUM
        return FinishTier.LUXURY
    return FinishTier.STANDARD


def _infer_region(brief: ClientBrief) -> str:
    explicit = brief.metadata.get("region")
    if explicit:
        return str(explicit)

    locality = (brief.site.locality or "").lower()
    hints = {
        "chennai": "IN-TN", "coimbatore": "IN-TN", "madurai": "IN-TN", "tamil": "IN-TN",
        "bengaluru": "IN-KA", "bangalore": "IN-KA", "mysore": "IN-KA", "karnataka": "IN-KA",
        "kochi": "IN-KL", "kerala": "IN-KL", "trivandrum": "IN-KL", "calicut": "IN-KL",
        "mumbai": "IN-MH", "pune": "IN-MH", "nagpur": "IN-MH", "maharashtra": "IN-MH",
        "delhi": "IN-DL", "gurgaon": "IN-HR", "gurugram": "IN-HR", "noida": "IN-UP",
        "hyderabad": "IN-TG", "telangana": "IN-TG", "vijayawada": "IN-AP",
        "ahmedabad": "IN-GJ", "surat": "IN-GJ", "gujarat": "IN-GJ",
        "jaipur": "IN-RJ", "kolkata": "IN-WB", "bhopal": "IN-MP", "indore": "IN-MP",
        "goa": "IN-GA", "chandigarh": "IN-PB", "lucknow": "IN-UP",
    }
    for hint, region in hints.items():
        if hint in locality:
            return region
    return "IN-TN"
