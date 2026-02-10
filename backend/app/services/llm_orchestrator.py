"""Claude API integration for candidate selection and decomposition."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import anthropic

from app.models import (
    AmbiguousCandidate,
    CandidateResult,
    DecompComponent,
    DecisionType,
    InputRow,
    LLMDecision,
)

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class LLMOrchestrator:
    """Manages Claude API calls for dataset selection and decomposition."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        temperature: float = 0.2,
        top_p: float = 0.4,
    ):
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=5)
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self._system_prompt: Optional[str] = None
        self._selection_template: Optional[str] = None

    @property
    def system_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = (PROMPTS_DIR / "system_prompt.txt").read_text()
        return self._system_prompt

    @property
    def selection_template(self) -> str:
        if self._selection_template is None:
            self._selection_template = (PROMPTS_DIR / "candidate_selection.txt").read_text()
        return self._selection_template

    def decide(
        self,
        input_row: dict,
        candidates: list[CandidateResult],
        max_retries: int = 3,
        allow_decompose: bool = True,
    ) -> LLMDecision:
        """Ask Claude to select the best candidate or propose decomposition.

        Args:
            input_row: Dict with bezeichnung, produktinformationen, referenzeinheit, region_norm.
            candidates: List of CandidateResult from the retriever.
            max_retries: Number of retries on JSON parse failure.
            allow_decompose: If False, forces LLM to choose match or ambiguous only.

        Returns:
            LLMDecision with the decision type and relevant data.
        """
        # Format candidates for the prompt (emission values excluded to save tokens)
        candidates_data = []
        for c in candidates:
            candidates_data.append({
                "UUID": c.dataset.uuid,
                "Activity Name": c.dataset.activity_name,
                "Geography": c.dataset.geography,
                "Product": c.dataset.product_name,
                "Unit": c.dataset.unit,
            })

        # Modify prompt if decomposition is not allowed (for component searches)
        if not allow_decompose:
            user_prompt = self._build_component_prompt(
                input_row,
                candidates_data,
            )
        else:
            user_prompt = self.selection_template.format(
                bezeichnung=input_row.get("bezeichnung", ""),
                produktinformationen=input_row.get("produktinformationen", ""),
                referenzeinheit=input_row.get("referenzeinheit", ""),
                region=input_row.get("region_norm", "GLO"),
                candidates_json=json.dumps(candidates_data, indent=2, ensure_ascii=False),
            )

        last_error = None
        for attempt in range(max_retries):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    system=self.system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                raw_text = response.content[0].text
                return self._parse_response(raw_text, candidates)

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                last_error = e
                logger.warning(
                    f"LLM response parse error (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    continue

        raise RuntimeError(
            f"Failed to get valid JSON from LLM after {max_retries} attempts. "
            f"Last error: {last_error}"
        )

    def _build_component_prompt(
        self,
        input_row: dict,
        candidates_data: list[dict],
    ) -> str:
        """Build a prompt for component matching that ONLY allows match or ambiguous."""
        return f"""Task: Select the best emission dataset for this component. You MUST choose either "match" or "ambiguous" - decomposition is NOT allowed for components.

Input component:
- Bezeichnung: "{input_row.get('bezeichnung', '')}"
- Produktinformationen: "{input_row.get('produktinformationen', '')}"
- Referenzeinheit: "{input_row.get('referenzeinheit', '')}"
- Region: "{input_row.get('region_norm', 'GLO')}"

Candidates (each is a row from the ecoinvent database - do not modify any strings):
{json.dumps(candidates_data, indent=2, ensure_ascii=False)}

Rules:
- Prefer cradle-to-gate production processes.
- Prefer region order: requested region > GLO > RoW.
- Prefer unit match to Referenzeinheit.
- If ONE candidate is clearly the best match, choose "match" and return its UUID.
- If multiple candidates are plausible, choose "ambiguous" and return a ranked list of up to 10 options.
- IMPORTANT: Decomposition is NOT ALLOWED. You must pick from the provided candidates.

You MUST respond with ONLY this JSON structure (no other text):

{{
  "decision": "match" | "ambiguous",
  "match": {{
    "UUID": "exact-uuid-from-candidates"
  }},
  "ambiguous": {{
    "options": [
      {{"UUID": "...", "why_short": "short reason this candidate is plausible"}},
      ...
    ]
  }}
}}

Include ONLY the relevant section based on your decision."""

    def request_decomposition(
        self,
        input_row: dict,
        reason: str,
        max_retries: int = 3,
    ) -> LLMDecision:
        """Request decomposition when unit doesn't match or no candidates found.

        This sends a targeted prompt asking only for decomposition, not selection.
        """
        ref_unit = input_row.get('referenzeinheit', '')
        prompt = f"""Decompose this product into physical components for emission factor calculation.

Product:
- Bezeichnung: "{input_row.get('bezeichnung', '')}"
- Produktinformationen: "{input_row.get('produktinformationen', '')}"
- Referenzeinheit: "{ref_unit}"
- Region: "{input_row.get('region_norm', 'GLO')}"

Reason for decomposition: {reason}

====================================================================
MANDATORY CONSTRAINT: The sum of ALL component quantities MUST = 1.0 {ref_unit}
====================================================================

You are decomposing exactly 1 {ref_unit} of this product.
Each component is a FRACTION of that 1 {ref_unit}.
The fractions MUST add up to EXACTLY 1.0.

EXAMPLE: Decomposing 1 kg Hamburger:
  beef patty:  0.35 kg
  wheat bun:   0.25 kg
  cheese:      0.15 kg
  lettuce:     0.08 kg
  tomato:      0.07 kg
  onion:       0.05 kg
  condiments:  0.05 kg
  ─────────────────────
  TOTAL:       1.00 kg  <-- MUST equal 1.0

WRONG (DO NOT DO THIS):
  beef: 0.10 kg, bun: 0.08 kg, cheese: 0.02 kg = 0.20 kg TOTAL
  This is WRONG because 0.20 ≠ 1.0 kg!

Rules:
- 3-10 physical components
- All components should use "{ref_unit}" as unit where possible
- Use English search queries for each component (for ecoinvent database)
- component_label should be descriptive (e.g., "beef patty", "wheat bun", NOT generic "materials")

BEFORE writing the JSON, mentally add up all quantities and verify the sum is 1.0 {ref_unit}.

Respond with ONLY this JSON:

{{
  "decision": "decompose",
  "decompose": {{
    "assumptions": ["list all assumptions about composition, weights, etc."],
    "components": [
      {{
        "component_label": "descriptive name",
        "assumed_quantity": 0.35,
        "assumed_unit": "{ref_unit}",
        "search_query_text": "English search query for ecoinvent database"
      }}
    ]
  }}
}}"""

        messages = [{"role": "user", "content": prompt}]
        last_error = None

        for attempt in range(max_retries):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    system=self.system_prompt,
                    messages=messages,
                )
                raw_text = response.content[0].text
                decision = self._parse_response(raw_text, candidates=[])

                # Validate decomposition sum
                if decision.components:
                    total = sum(c.assumed_quantity for c in decision.components)
                    if not (0.95 <= total <= 1.05):
                        logger.warning(
                            f"Decomposition sum {total:.3f} != 1.0 {ref_unit} "
                            f"(attempt {attempt + 1}/{max_retries}). Retrying..."
                        )
                        # Add correction feedback and retry
                        comp_list = ", ".join(
                            f"{c.component_label}: {c.assumed_quantity}"
                            for c in decision.components
                        )
                        messages = [
                            {"role": "user", "content": prompt},
                            {"role": "assistant", "content": raw_text},
                            {"role": "user", "content": (
                                f"WRONG! Your components sum to {total:.3f} {ref_unit}, "
                                f"but MUST sum to exactly 1.0 {ref_unit}. "
                                f"Components: {comp_list}. "
                                f"Please recalculate with quantities that sum to 1.0 {ref_unit}. "
                                f"Return the corrected JSON only."
                            )},
                        ]
                        if attempt < max_retries - 1:
                            continue
                        # Last attempt still wrong - raise
                        raise ValueError(
                            f"Decomposition sum {total:.3f} != 1.0 after {max_retries} attempts"
                        )

                return decision

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                last_error = e
                logger.warning(
                    f"Decomposition parse error (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    continue

        raise RuntimeError(
            f"Failed to get decomposition from LLM after {max_retries} attempts. "
            f"Last error: {last_error}"
        )

    def _parse_response(
        self,
        raw_text: str,
        candidates: list[CandidateResult],
    ) -> LLMDecision:
        """Parse strict JSON response into LLMDecision."""
        # Strip markdown code fences if present
        text = raw_text.strip()
        if text.startswith("```"):
            # Remove first line (```json) and last line (```)
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])

        data = json.loads(text)
        decision = data["decision"]

        # Build a set of valid UUIDs from candidates for validation
        valid_uuids = {c.dataset.uuid for c in candidates}

        if decision == "match":
            match_data = data.get("match", {})
            uuid = match_data.get("UUID", "")
            if valid_uuids and uuid not in valid_uuids:
                raise ValueError(
                    f"LLM returned UUID not in candidate list: {uuid}"
                )
            return LLMDecision(type=DecisionType.MATCH, selected_uuid=uuid)

        elif decision == "ambiguous":
            amb_data = data.get("ambiguous", {})
            options = []
            for i, opt in enumerate(amb_data.get("options", [])):
                uuid = opt.get("UUID", "")
                if valid_uuids and uuid not in valid_uuids:
                    logger.warning(f"Skipping ambiguous UUID not in candidates: {uuid}")
                    continue
                # Look up full info from candidates
                candidate = next((c for c in candidates if c.dataset.uuid == uuid), None)
                options.append(
                    AmbiguousCandidate(
                        uuid=uuid,
                        activity_name=candidate.dataset.activity_name if candidate else opt.get("Activity Name", ""),
                        product_name=candidate.dataset.product_name if candidate else opt.get("Reference Product Name", ""),
                        geography=candidate.dataset.geography if candidate else opt.get("Geography", ""),
                        unit=candidate.dataset.unit if candidate else opt.get("Unit", ""),
                        why_short=opt.get("why_short", ""),
                        rank=i + 1,
                    )
                )
            return LLMDecision(type=DecisionType.AMBIGUOUS, candidates=options)

        elif decision == "decompose":
            decomp_data = data.get("decompose", {})
            assumptions = decomp_data.get("assumptions", [])
            components = []
            for comp in decomp_data.get("components", []):
                components.append(
                    DecompComponent(
                        component_label=comp["component_label"],
                        assumed_quantity=float(comp["assumed_quantity"]),
                        assumed_unit=comp["assumed_unit"],
                        search_query_text=comp["search_query_text"],
                    )
                )
            return LLMDecision(
                type=DecisionType.DECOMPOSE,
                components=components,
                assumptions=assumptions,
            )

        else:
            raise ValueError(f"Unknown decision type: {decision}")

    def convert_unit(
        self,
        reference_unit: str,
        dataset_unit: str,
        product_context: str,
        max_retries: int = 3,
    ) -> dict:
        """Ask Claude to convert between units using domain knowledge.

        Args:
            reference_unit: The target unit (Referenzeinheit).
            dataset_unit: The unit of the matched dataset.
            product_context: Description of the product for context.
            max_retries: Number of retries on parse failure.

        Returns:
            Dict with keys:
            - conversion_factor: float (how many dataset_units per 1 reference_unit)
            - explanation: str (explanation of the conversion)
        """
        prompt = f"""You are a unit conversion expert. Convert between the following units:

Product context: {product_context}
Reference unit (target): {reference_unit}
Dataset unit (source): {dataset_unit}

Task: Calculate how many {dataset_unit} are needed to represent exactly 1 {reference_unit} of this product.

Use your knowledge about:
- Energy content (e.g., 1 liter diesel ≈ 36 MJ)
- Weight conversions
- Volume conversions
- Any other relevant physical properties

Respond with ONLY this JSON (no other text):

{{
  "conversion_factor": <number>,
  "explanation": "Brief explanation of how you calculated this conversion"
}}

Example for "1 liter diesel" to "MJ":
{{
  "conversion_factor": 36.0,
  "explanation": "1 liter of diesel contains approximately 36 MJ of energy (lower heating value)"
}}"""

        last_error = None
        for attempt in range(max_retries):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    system=self.system_prompt,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw_text = response.content[0].text

                # Strip markdown code fences if present
                text = raw_text.strip()
                if text.startswith("```"):
                    lines = text.split("\n")
                    text = "\n".join(lines[1:-1])

                data = json.loads(text)
                return {
                    "conversion_factor": float(data["conversion_factor"]),
                    "explanation": data["explanation"],
                }

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                last_error = e
                logger.warning(
                    f"Unit conversion parse error (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    continue

        raise RuntimeError(
            f"Failed to get unit conversion from LLM after {max_retries} attempts. "
            f"Last error: {last_error}"
        )
