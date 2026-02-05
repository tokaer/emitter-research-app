"""Validation: UUID existence, activity name match, market filter, char limits."""
from __future__ import annotations

import logging

from app.models import ValidationResult
from app.services.dataset_store import DatasetStore

logger = logging.getLogger(__name__)


class Validator:
    """Validates output data against database and business rules."""

    def __init__(self, store: DatasetStore):
        self.store = store

    def validate_uuid(self, uuid: str) -> ValidationResult:
        """Check UUID exists in database."""
        row = self.store.lookup_by_uuid(uuid)
        if row is None:
            return ValidationResult(
                valid=False,
                error=f"UUID not found in database: {uuid}",
            )
        return ValidationResult(valid=True, data=row)

    def validate_activity_not_market(self, uuid: str) -> ValidationResult:
        """Ensure the selected activity is not a market activity."""
        row = self.store.lookup_by_uuid(uuid)
        if row is None:
            return ValidationResult(
                valid=False,
                error=f"UUID not found: {uuid}",
            )
        lower = row.activity_name.strip().lower()
        if lower.startswith("market for") or lower.startswith("market group"):
            return ValidationResult(
                valid=False,
                error=f"Market activity selected: '{row.activity_name}'. Market activities are excluded.",
            )
        return ValidationResult(valid=True)

    def validate_char_limit(
        self, field_name: str, value: str, max_chars: int = 500
    ) -> ValidationResult:
        """Hard fail if field exceeds character limit."""
        if len(value) > max_chars:
            return ValidationResult(
                valid=False,
                error=(
                    f"{field_name} exceeds {max_chars} char limit: "
                    f"{len(value)} chars. This is a blocking error."
                ),
            )
        return ValidationResult(valid=True)

    def validate_decimal_format(self, value: str) -> ValidationResult:
        """Verify comma-decimal format (no dots as decimal separator)."""
        # Allow dots only in the integer part (thousand separators would use dots)
        # But our format doesn't use thousand separators, so dots shouldn't appear
        if "." in value:
            return ValidationResult(
                valid=False,
                error=f"Value contains dot instead of comma: '{value}'",
            )
        return ValidationResult(valid=True)

    def validate_result(
        self,
        uuids: list[str],
        beschreibung: str,
        quelle: str,
        biogenic_t: str,
        common_t: str,
    ) -> list[ValidationResult]:
        """Run all validations on a completed result.

        Returns list of ValidationResults. Check all .valid fields.
        """
        results = []

        # Validate each UUID
        for uuid in uuids:
            results.append(self.validate_uuid(uuid))
            results.append(self.validate_activity_not_market(uuid))

        # Validate char limits
        results.append(self.validate_char_limit("Beschreibung", beschreibung))
        results.append(self.validate_char_limit("Quelle", quelle))

        # Validate decimal format
        results.append(self.validate_decimal_format(biogenic_t))
        results.append(self.validate_decimal_format(common_t))

        # Log any failures
        failures = [r for r in results if not r.valid]
        if failures:
            for f in failures:
                logger.error(f"Validation failed: {f.error}")

        return results
