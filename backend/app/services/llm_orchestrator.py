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

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
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
        # Format candidates for the prompt
        candidates_data = []
        for c in candidates:
            candidates_data.append({
                "UUID": c.dataset.uuid,
                "Activity Name": c.dataset.activity_name,
                "Geography": c.dataset.geography,
                "Reference Product Name": c.dataset.product_name,
                "Unit": c.dataset.unit,
                "Biogenic [kg CO2-Eq]": c.dataset.biogenic_kg,
                "Total (excl. Biogenic) [kg CO2-Eq]": c.dataset.total_excl_bio_kg,
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
        prompt = f"""The following product needs to be decomposed into its physical components for emission factor calculation.
The product could not be matched directly because: {reason}

Product:
- Bezeichnung: "{input_row.get('bezeichnung', '')}"
- Produktinformationen: "{input_row.get('produktinformationen', '')}"
- Referenzeinheit: "{input_row.get('referenzeinheit', '')}"
- Region: "{input_row.get('region_norm', 'GLO')}"

CRITICAL REQUIREMENT - Component Quantities:
The sum of all assumed_quantity values MUST equal EXACTLY 1 {input_row.get('referenzeinheit', '')}.

Example for 1 kg Hamburger:
- Beef patty: 0.40 kg
- Bun: 0.30 kg
- Cheese: 0.15 kg
- Vegetables: 0.10 kg
- Condiments: 0.05 kg
→ Sum: 1.00 kg ✓

WRONG Example (DO NOT DO THIS):
- Beef: 0.15 kg
- Chicken: 1.0 kg  ← This alone exceeds the reference unit!
→ Sum: 1.15 kg ✗

Decompose this product into 3-10 physical components that together represent exactly 1 {input_row.get('referenzeinheit', '')} of the product.
Use these categories: materials, energy, packaging, transport, processes.
For each component, provide a search query in English that can find matching emission datasets in the ecoinvent database.
Use standard units (kg, kWh, MJ, m, m2, m3, l, km, metric ton*km, unit, hour).
All components should use the same unit as the reference unit ({input_row.get('referenzeinheit', '')}) where possible.

Respond with ONLY this JSON:

{{
  "decision": "decompose",
  "decompose": {{
    "assumptions": ["list all assumptions about material composition, weights, energy use, etc."],
    "components": [
      {{
        "component_label": "materials | energy | packaging | transport | processes",
        "assumed_quantity": 1.0,
        "assumed_unit": "kg",
        "search_query_text": "English search query for ecoinvent database"
      }}
    ]
  }}
}}"""

        last_error = None
        for attempt in range(max_retries):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=self.system_prompt,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw_text = response.content[0].text
                return self._parse_response(raw_text, candidates=[])

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
