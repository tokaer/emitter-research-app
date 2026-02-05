"""Build output strings: Beschreibung, Quelle, Detailed calculation."""
from __future__ import annotations

from app.models import CalcResult, DecompCalcResult, OutputTooLongError
from app.services.calculator import format_number

# Increased from 500 to 1000 to support up to 10 components
MAX_CHARS = 1000


def build_beschreibung_match(
    input_row: dict,
    calc: CalcResult,
) -> str:
    """Build Beschreibung for a direct match result.

    Format: concise, mechanical, no filler text.
    """
    # Add unit conversion explanation if present
    conversion_note = ""
    if calc.unit_conversion:
        conversion_note = (
            f" [Umrechnung: {calc.unit_conversion['explanation']}]"
        )

    desc = (
        f"1 {input_row.get('referenzeinheit', '')} "
        f"= {calc.activity_name} ({calc.geography}); "
        f"Common: {format_number(calc.total_excl_bio_t)} t CO2-Eq "
        f"({format_number(calc.total_excl_bio_kg)} kg × 1/{calc.quantity if calc.quantity != 1 else ''}1000); "
        f"Biogen: {format_number(calc.biogenic_t)} t CO2-Eq; "
        f"Einheit: {calc.unit}"
        f"{conversion_note}"
    )
    # Clean up double spaces
    desc = " ".join(desc.split())
    return desc


def build_beschreibung_decomp(
    input_row: dict,
    decomp: DecompCalcResult,
) -> str:
    """Build Beschreibung for a decomposition result showing actual activity names."""
    parts = []
    for comp in decomp.components:
        # Show activity name instead of just component_label
        activity_short = comp.matched_activity[:40] + "..." if len(comp.matched_activity) > 40 else comp.matched_activity
        parts.append(
            f"{activity_short} ({comp.assumed_quantity} {comp.assumed_unit})"
        )

    components_str = " + ".join(parts)
    desc = f"1 {input_row.get('referenzeinheit', '')} = Zerlegung: {components_str}"
    desc = " ".join(desc.split())
    return desc


def build_quelle(uuids: list[str]) -> str:
    """Build Quelle string. Hard fail if >MAX_CHARS.

    Format: "ecoinvent 3.11; UUIDs: uuid1, uuid2, ..."
    """
    uuid_str = ", ".join(uuids)
    quelle = f"ecoinvent 3.11; UUIDs: {uuid_str}"

    if len(quelle) > MAX_CHARS:
        raise OutputTooLongError(
            field="Quelle",
            actual_length=len(quelle),
            max_length=MAX_CHARS,
            message=(
                f"Quelle exceeds {MAX_CHARS} char limit ({len(quelle)} chars) "
                f"with {len(uuids)} UUIDs. Maximum ~10 UUIDs fit within the limit. "
                f"This is a blocking error — content will not be silently truncated."
            ),
        )
    return quelle


def build_detailed_calculation_match(
    input_row: dict,
    calc: CalcResult,
) -> str:
    """Build full detailed calculation string for a match. No char limit."""
    lines = [
        "=== Detailed Calculation ===",
        "",
        f"Input: {input_row.get('bezeichnung', '')}",
        f"Produktinformationen: {input_row.get('produktinformationen', '')}",
        f"Referenzeinheit: {input_row.get('referenzeinheit', '')}",
        f"Region: {input_row.get('region_norm', 'GLO')}",
        "",
        "--- Matched Dataset ---",
        f"UUID: {calc.uuid}",
        f"Activity: {calc.activity_name}",
        f"Geography: {calc.geography}",
        f"Unit: {calc.unit}",
        f"Quantity: {calc.quantity}",
    ]

    # Add unit conversion explanation if present
    if calc.unit_conversion:
        lines.extend([
            "",
            "--- Unit Conversion ---",
            f"Reference unit: {input_row.get('referenzeinheit', '')}",
            f"Dataset unit: {calc.unit}",
            f"Conversion factor: {calc.unit_conversion['conversion_factor']}",
            f"Explanation: {calc.unit_conversion['explanation']}",
        ])

    lines.extend([
        "",
        "--- Calculation ---",
        f"Biogenic [kg CO2-Eq]: {calc.biogenic_kg}",
        f"  = DB value × {calc.quantity} = {calc.biogenic_kg} kg",
        f"  = {calc.biogenic_kg} / 1000 = {calc.biogenic_t} t CO2-Eq",
        f"  Formatted: {format_number(calc.biogenic_t)} t CO2-Eq",
        "",
        f"Total excl. biogenic [kg CO2-Eq]: {calc.total_excl_bio_kg}",
        f"  = DB value × {calc.quantity} = {calc.total_excl_bio_kg} kg",
        f"  = {calc.total_excl_bio_kg} / 1000 = {calc.total_excl_bio_t} t CO2-Eq",
        f"  Formatted: {format_number(calc.total_excl_bio_t)} t CO2-Eq",
    ])

    return "\n".join(lines)


def build_detailed_calculation_decomp(
    input_row: dict,
    decomp: DecompCalcResult,
) -> str:
    """Build full detailed calculation string for a decomposition. No char limit."""
    lines = [
        "=== Detailed Calculation (Decomposition) ===",
        "",
        f"Input: {input_row.get('bezeichnung', '')}",
        f"Produktinformationen: {input_row.get('produktinformationen', '')}",
        f"Referenzeinheit: {input_row.get('referenzeinheit', '')}",
        f"Region: {input_row.get('region_norm', 'GLO')}",
        "",
        "--- Assumptions ---",
    ]

    for assumption in decomp.assumptions:
        lines.append(f"  - {assumption}")

    lines.extend([
        "",
        "--- Components ---",
    ])

    for comp in decomp.components:
        lines.extend([
            f"",
            f"  [{comp.component_label}]",
            f"  UUID: {comp.matched_uuid}",
            f"  Activity: {comp.matched_activity}",
            f"  Geography: {comp.matched_geography}",
            f"  Quantity: {comp.assumed_quantity} {comp.assumed_unit}",
            f"  Biogenic: {comp.scaled_biogenic_kg} kg CO2-Eq",
            f"  Total excl. biogenic: {comp.scaled_total_kg} kg CO2-Eq",
        ])

    lines.extend([
        "",
        "--- Totals ---",
        f"Sum biogenic [kg]: {decomp.biogenic_kg_sum}",
        f"Sum total excl. biogenic [kg]: {decomp.total_excl_bio_kg_sum}",
        f"",
        f"Biogenic [t CO2-Eq]: {decomp.biogenic_kg_sum} / 1000 = {decomp.biogenic_t}",
        f"  Formatted: {format_number(decomp.biogenic_t)}",
        f"Total excl. biogenic [t CO2-Eq]: {decomp.total_excl_bio_kg_sum} / 1000 = {decomp.total_excl_bio_t}",
        f"  Formatted: {format_number(decomp.total_excl_bio_t)}",
    ])

    return "\n".join(lines)


def validate_beschreibung(beschreibung: str) -> str:
    """Validate Beschreibung length. Raises OutputTooLongError if >500 chars."""
    if len(beschreibung) > MAX_CHARS:
        raise OutputTooLongError(
            field="Beschreibung",
            actual_length=len(beschreibung),
            max_length=MAX_CHARS,
        )
    return beschreibung
