"""Emission factor calculation: lookup, scale, sum, convert kg→t."""
from __future__ import annotations

import logging
import math
from typing import Optional

from app.models import CalcResult, DecompCalcResult, ResolvedComponent
from app.services.dataset_store import DatasetStore

logger = logging.getLogger(__name__)


def truncate_to_decimals(value: float, decimals: int = 10) -> float:
    """Truncate (not round) a float to the given number of decimal places."""
    if math.isnan(value) or math.isinf(value):
        return value
    factor = 10 ** decimals
    if value >= 0:
        return math.floor(value * factor) / factor
    else:
        return math.ceil(value * factor) / factor


def format_number(value: float) -> str:
    """Format a number with comma decimal separator, max 10 decimals, truncated.

    Rules:
    - Comma as decimal separator
    - Max 10 decimal places
    - Truncate, not round
    - Remove trailing zeros (keep at least format like "0,0")
    """
    truncated = truncate_to_decimals(value, 10)
    # Format with exactly 10 decimal places
    formatted = f"{truncated:.10f}"
    # Remove trailing zeros but keep at least one decimal
    parts = formatted.split(".")
    integer_part = parts[0]
    decimal_part = parts[1].rstrip("0") or "0"
    # Use comma as decimal separator
    return f"{integer_part},{decimal_part}"


class Calculator:
    """Performs emission factor calculations."""

    def __init__(self, store: DatasetStore):
        self.store = store

    def calculate_match(
        self,
        uuid: str,
        quantity: float = 1.0,
        unit_conversion: Optional[dict] = None,
    ) -> CalcResult:
        """Calculate emission values for a single matched UUID.

        Args:
            uuid: The matched dataset UUID.
            quantity: Quantity in the dataset's unit (default 1.0).
            unit_conversion: Optional dict with "factor" and "explanation" for unit conversion.

        Returns:
            CalcResult with all calculated values.

        Raises:
            ValueError: If UUID not found in database.
        """
        ds = self.store.lookup_by_uuid(uuid)
        if ds is None:
            raise ValueError(f"UUID not found in database: {uuid}")

        # For amount=1: values are per unit directly
        # For amount=-1: values represent credits (by-products)
        # All -1 amount rows have 0 emissions in this dataset, but handle correctly
        if ds.amount != 0:
            emission_per_unit_bio = ds.biogenic_kg / abs(ds.amount)
            emission_per_unit_total = ds.total_excl_bio_kg / abs(ds.amount)
            if ds.amount < 0:
                emission_per_unit_bio = -emission_per_unit_bio
                emission_per_unit_total = -emission_per_unit_total
        else:
            emission_per_unit_bio = 0.0
            emission_per_unit_total = 0.0

        scaled_bio_kg = emission_per_unit_bio * quantity
        scaled_total_kg = emission_per_unit_total * quantity

        return CalcResult(
            uuid=uuid,
            activity_name=ds.activity_name,
            geography=ds.geography,
            quantity=quantity,
            unit=ds.unit,
            biogenic_kg=scaled_bio_kg,
            total_excl_bio_kg=scaled_total_kg,
            biogenic_t=scaled_bio_kg / 1000,
            total_excl_bio_t=scaled_total_kg / 1000,
            unit_conversion=unit_conversion,
        )

    def calculate_decomposition(
        self,
        components: list[dict],
        assumptions: Optional[list[str]] = None,
    ) -> DecompCalcResult:
        """Sum emission factors across decomposition components.

        Args:
            components: List of dicts with keys:
                - component_label, assumed_quantity, assumed_unit
                - matched_uuid (must be resolved already)
            assumptions: List of assumption strings from LLM.

        Returns:
            DecompCalcResult with per-component and total values.
        """
        resolved = []
        total_bio_kg = 0.0
        total_total_kg = 0.0

        for comp in components:
            uuid = comp["matched_uuid"]
            quantity = comp["assumed_quantity"]

            calc = self.calculate_match(uuid, quantity)

            resolved.append(
                ResolvedComponent(
                    component_label=comp["component_label"],
                    assumed_quantity=quantity,
                    assumed_unit=comp["assumed_unit"],
                    matched_uuid=uuid,
                    matched_activity=calc.activity_name,
                    matched_geography=calc.geography,
                    scaled_biogenic_kg=calc.biogenic_kg,
                    scaled_total_kg=calc.total_excl_bio_kg,
                )
            )

            total_bio_kg += calc.biogenic_kg
            total_total_kg += calc.total_excl_bio_kg

        return DecompCalcResult(
            components=resolved,
            assumptions=assumptions or [],
            biogenic_kg_sum=total_bio_kg,
            total_excl_bio_kg_sum=total_total_kg,
            biogenic_t=total_bio_kg / 1000,
            total_excl_bio_t=total_total_kg / 1000,
        )
