"""Hybrid BM25 + embedding candidate retrieval with region/unit filtering."""
from __future__ import annotations

import logging
import re
from typing import Optional

from rank_bm25 import BM25Okapi
from unidecode import unidecode

from app.models import CandidateResult, DatasetRow, RetrievalResult
from app.services.dataset_store import DatasetStore
from app.services.embedding_builder import EmbeddingIndex

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# German -> ecoinvent unit mapping
# ---------------------------------------------------------------------------

UNIT_MAP: dict[str, Optional[str]] = {
    # Direct DB units (lowercase)
    "kg": "kg",
    "kwh": "kWh",
    "mj": "MJ",
    "m2": "m2",
    "m3": "m3",
    "l": "l",
    "km": "km",
    "ha": "ha",
    "hour": "hour",
    "m": "m",
    "unit": "unit",
    "person*km": "person*km",
    "metric ton*km": "metric ton*km",
    "km*year": "km*year",
    "m2*year": "m2*year",
    "m*year": "m*year",
    "kg*day": "kg*day",
    "guest night": "guest night",
    # German unit names
    "stück": "unit",
    "stueck": "unit",
    "stk": "unit",
    "stk.": "unit",
    "pcs": "unit",
    "pc": "unit",
    "ea": "unit",
    "piece": "unit",
    "pieces": "unit",
    "liter": "l",
    "kilogramm": "kg",
    "kilowattstunde": "kWh",
    "meter": "m",
    "quadratmeter": "m2",
    "kubikmeter": "m3",
    "hektar": "ha",
    "stunde": "hour",
    "stunden": "hour",
    "personenkilometer": "person*km",
    "tonnenkilometer": "metric ton*km",
    "tkm": "metric ton*km",
    "pkm": "person*km",
    "sqm": "m2",
    "cbm": "m3",
}


def map_unit(raw_unit: str) -> Optional[str]:
    """Map a user-provided unit to an ecoinvent DB unit.

    Returns the mapped unit string or None if no mapping exists.
    """
    normalized = raw_unit.strip().lower()
    return UNIT_MAP.get(normalized)


# ---------------------------------------------------------------------------
# German -> English term translation for search queries
# Ecoinvent uses English activity names; German input terms need translation
# to enable BM25 keyword matching.
# ---------------------------------------------------------------------------

TERM_TRANSLATIONS: dict[str, str] = {
    # ===== FUELS & COMBUSTIBLES =====
    "benzin": "petrol gasoline",
    "superbenzin": "petrol gasoline",
    "diesel": "diesel",
    "dieselkraftstoff": "diesel",
    "heizoel": "heating oil light fuel oil",
    "heizöl": "heating oil light fuel oil",
    "erdgas": "natural gas",
    "kerosin": "kerosene jet fuel",
    "flugbenzin": "kerosene jet fuel aviation",
    "flüssiggas": "liquefied petroleum gas LPG",
    "fluessiggas": "liquefied petroleum gas LPG",
    "lpg": "liquefied petroleum gas LPG",
    "propan": "propane liquefied petroleum gas",
    "butan": "butane liquefied petroleum gas",
    "biogas": "biogas",
    "biodiesel": "biodiesel",
    "bioethanol": "ethanol bioethanol",
    "holzpellets": "wood pellets",
    "hackschnitzel": "wood chips",
    "braunkohle": "lignite brown coal",
    "steinkohle": "hard coal",
    "kohle": "coal",
    "koks": "coke petroleum coke",
    "brennholz": "firewood fuel wood",
    "torf": "peat",
    "wasserstoff": "hydrogen",
    "methanol": "methanol",
    "ethanol": "ethanol",
    # ===== ENERGY =====
    "strom": "electricity",
    "elektrizitaet": "electricity",
    "elektrizität": "electricity",
    "oekostrom": "electricity wind solar hydro",
    "ökostrom": "electricity wind solar hydro",
    "windstrom": "electricity wind",
    "solarstrom": "electricity photovoltaic solar",
    "photovoltaik": "photovoltaic solar electricity",
    "solarthermie": "solar collector heat",
    "fernwaerme": "district heat",
    "fernwärme": "district heat",
    "nahwaerme": "heat district heating",
    "nahwärme": "heat district heating",
    "waermepumpe": "heat pump",
    "wärmepumpe": "heat pump",
    "bhkw": "combined heat power cogeneration CHP",
    "blockheizkraftwerk": "combined heat power cogeneration CHP",
    "druckluft": "compressed air",
    "dampf": "steam heat",
    "geothermie": "geothermal heat",
    "brennstoffzelle": "fuel cell",
    # ===== TRANSPORT & LOGISTICS =====
    "lkw": "lorry truck transport freight",
    "pkw": "passenger car transport",
    "auto": "passenger car transport",
    "lastwagen": "lorry truck transport freight",
    "sattelzug": "lorry truck articulated transport",
    "transporter": "van light commercial transport",
    "lieferwagen": "van delivery transport",
    "flugtransport": "air transport freight flight",
    "flugzeug": "aircraft flight",
    "flug": "aircraft flight transport air",
    "kurzstreckenflug": "aircraft flight short-haul",
    "langstreckenflug": "aircraft flight long-haul",
    "schiff": "ship vessel barge freight",
    "schiffstransport": "ship transport freight",
    "containerschiff": "container ship transoceanic freight",
    "binnenschiff": "barge inland waterway transport",
    "bahn": "train rail transport freight",
    "zug": "train rail transport freight",
    "gueterzug": "freight train rail transport",
    "güterzug": "freight train rail transport",
    "bus": "bus transport passenger",
    "fahrrad": "bicycle transport",
    "roller": "scooter motor transport",
    "motorrad": "motorcycle transport",
    "traktor": "tractor agricultural machinery",
    "gabelstapler": "forklift industrial truck",
    "bagger": "excavator construction machinery",
    "kran": "crane construction machinery",
    "spedition": "freight transport lorry",
    "kurier": "courier transport delivery",
    "logistik": "transport freight logistics",
    # ===== METALS =====
    "stahl": "steel",
    "edelstahl": "stainless steel chromium",
    "baustahl": "reinforcing steel",
    "bewehrungsstahl": "reinforcing steel",
    "aluminium": "aluminium",
    "kupfer": "copper",
    "eisen": "iron pig iron cast iron",
    "zink": "zinc",
    "zinn": "tin",
    "blei": "lead",
    "nickel": "nickel",
    "titan": "titanium",
    "chrom": "chromium",
    "mangan": "manganese",
    "gold": "gold",
    "silber": "silver",
    "platin": "platinum",
    "lithium": "lithium",
    "messing": "brass copper zinc",
    "bronze": "bronze copper tin",
    # ===== PLASTICS & POLYMERS =====
    "kunststoff": "plastic polyethylene polypropylene",
    "plastik": "plastic polyethylene",
    "pe": "polyethylene",
    "polyethylen": "polyethylene",
    "pp": "polypropylene",
    "polypropylen": "polypropylene",
    "ps": "polystyrene",
    "polystyrol": "polystyrene",
    "pvc": "polyvinylchloride PVC",
    "pet": "polyethylene terephthalate PET",
    "pu": "polyurethane",
    "polyurethan": "polyurethane",
    "nylon": "nylon polyamide",
    "polyamid": "nylon polyamide",
    "polycarbonat": "polycarbonate",
    "abs": "acrylonitrile butadiene styrene ABS",
    "epoxid": "epoxy resin",
    "epoxidharz": "epoxy resin",
    "acryl": "acrylic polymethyl methacrylate",
    "silikon": "silicone",
    "gummi": "synthetic rubber",
    "kautschuk": "synthetic rubber latex",
    "styropor": "polystyrene expandable EPS",
    "folie": "film packaging polyethylene",
    # ===== CHEMICALS & SOLVENTS =====
    "ammoniak": "ammonia",
    "chlor": "chlorine",
    "salzsaeure": "hydrochloric acid",
    "salzsäure": "hydrochloric acid",
    "schwefelsaeure": "sulfuric acid",
    "schwefelsäure": "sulfuric acid",
    "salpetersaeure": "nitric acid",
    "salpetersäure": "nitric acid",
    "natronlauge": "sodium hydroxide",
    "natriumhydroxid": "sodium hydroxide",
    "kalk": "lime calcium oxide quicklite",
    "soda": "soda ash sodium carbonate",
    "sauerstoff": "oxygen",
    "stickstoff": "nitrogen",
    "co2": "carbon dioxide",
    "kohlendioxid": "carbon dioxide",
    "acetylen": "acetylene",
    "ethylen": "ethylene",
    "propylen": "propylene",
    "benzol": "benzene",
    "toluol": "toluene",
    "xylol": "xylene",
    "loesungsmittel": "solvent organic",
    "lösungsmittel": "solvent organic",
    "reinigungsmittel": "cleaning agent detergent",
    "waschmittel": "detergent soap",
    "seife": "soap",
    "schmierstoff": "lubricating oil lubricant",
    "schmieroel": "lubricating oil",
    "schmieröl": "lubricating oil",
    "harnstoff": "urea",
    "formaldehyd": "formaldehyde",
    "glycerin": "glycerine",
    "isopropanol": "isopropanol",
    "aceton": "acetone",
    "kaeltemittel": "refrigerant",
    "kältemittel": "refrigerant",
    # ===== CONSTRUCTION MATERIALS =====
    "beton": "concrete",
    "zement": "cement",
    "ziegel": "brick",
    "klinker": "clinker brick",
    "gips": "gypsum plaster",
    "putz": "plaster rendering",
    "moertel": "morite mortar",
    "mörtel": "mortar",
    "kies": "gravel",
    "sand": "sand",
    "schotter": "gravel crushed stone",
    "asphalt": "asphalt bitumen",
    "bitumen": "bitumen",
    "daemmung": "insulation",
    "dämmung": "insulation",
    "mineralwolle": "rock wool mineral wool insulation",
    "glaswolle": "glass wool insulation",
    "steinwolle": "rock wool insulation",
    "xps": "polystyrene extruded insulation XPS",
    "eps": "polystyrene expandable insulation EPS",
    "dachziegel": "roof tile",
    "dachpappe": "roofing bitumen felt",
    "fenster": "window flat glass",
    "tuer": "door",
    "tür": "door",
    "fliese": "ceramic tile",
    "keramik": "ceramic",
    "sanitaer": "sanitary ceramic",
    "sanitär": "sanitary ceramic",
    "estrich": "screed floor",
    "parkett": "parquet wood floor",
    "laminat": "laminate floor",
    "tapete": "wallpaper",
    "farbe": "paint alkyd acrylic",
    "lack": "paint varnish coating",
    "anstrich": "paint coating",
    "beschichtung": "coating",
    "kleber": "adhesive",
    "klebstoff": "adhesive",
    "dichtung": "sealant sealing",
    # ===== WOOD & TIMBER =====
    "holz": "wood timber sawnwood",
    "bauholz": "sawnwood timber construction",
    "schnittholz": "sawnwood",
    "sperrholz": "plywood",
    "spanplatte": "particle board",
    "faserplatte": "fibreboard MDF",
    "mdf": "fibreboard MDF medium density",
    "osb": "oriented strand board OSB",
    "furnierholz": "veneer plywood",
    # ===== PAPER & PACKAGING =====
    "papier": "paper",
    "karton": "cardboard",
    "pappe": "cardboard corrugated board",
    "wellpappe": "corrugated board",
    "verpackung": "packaging",
    "zellstoff": "pulp",
    "druckpapier": "paper printing",
    "toilettenpapier": "tissue paper",
    "getraenkekarton": "beverage carton",
    "getränkekarton": "beverage carton",
    # ===== GLASS =====
    "glas": "glass flat glass",
    "flachglas": "flat glass",
    "flaschenglas": "packaging glass container",
    "glasfaser": "glass fibre",
    # ===== TEXTILES =====
    "textil": "textile",
    "stoff": "textile fabric",
    "gewebe": "textile weaving",
    "baumwolle": "cotton",
    "wolle": "wool",
    "polyester": "polyester PET fibre",
    "nylon": "nylon polyamide fibre",
    "viskose": "viscose rayon",
    "seide": "silk",
    "leinen": "flax linen",
    "leder": "leather bovine",
    "jute": "jute fibre",
    "hanf": "hemp fibre",
    "faerbung": "dyeing textile",
    "färbung": "dyeing textile",
    "bleichen": "bleaching textile",
    "naehen": "sewing textile",
    "nähen": "sewing textile",
    # ===== FOOD & AGRICULTURE =====
    "fleisch": "meat cattle pig poultry",
    "rindfleisch": "beef cattle",
    "schweinefleisch": "pork pig swine",
    "huehnerfleisch": "chicken poultry",
    "hühnerfleisch": "chicken poultry",
    "gefluegel": "poultry chicken",
    "geflügel": "poultry chicken",
    "fisch": "fish",
    "milch": "milk dairy cow",
    "kaese": "cheese dairy",
    "käse": "cheese dairy",
    "butter": "butter dairy",
    "joghurt": "yogurt dairy",
    "ei": "egg hen",
    "eier": "egg hen",
    "weizen": "wheat grain",
    "mais": "maize corn grain",
    "gerste": "barley grain",
    "roggen": "rye grain",
    "hafer": "oat grain",
    "reis": "rice paddy grain",
    "soja": "soybean",
    "raps": "rape seed oil",
    "sonnenblume": "sunflower seed oil",
    "palmoel": "palm oil",
    "palmöl": "palm oil",
    "olivenoel": "olive oil",
    "olivenöl": "olive oil",
    "zucker": "sugar beet cane",
    "zuckerruebe": "sugar beet",
    "zuckerrübe": "sugar beet",
    "kartoffel": "potato",
    "tomate": "tomato",
    "apfel": "apple",
    "banane": "banana",
    "orange": "orange citrus",
    "kaffee": "coffee",
    "tee": "tea",
    "kakao": "cocoa",
    "schokolade": "cocoa chocolate",
    "brot": "bread wheat",
    "mehl": "flour wheat",
    "nudeln": "pasta wheat",
    "bier": "beer barley",
    "wein": "wine grape",
    "duenger": "fertiliser fertilizer",
    "dünger": "fertiliser fertilizer",
    "stickstoffduenger": "nitrogen fertiliser",
    "stickstoffdünger": "nitrogen fertiliser",
    "phosphatduenger": "phosphate fertiliser",
    "phosphatdünger": "phosphate fertiliser",
    "pestizid": "pesticide",
    "herbizid": "herbicide",
    "fungizid": "fungicide",
    "insektizid": "insecticide",
    "futtermittel": "feed animal",
    "tierfutter": "feed animal",
    "gewaechshaus": "greenhouse cultivation",
    "gewächshaus": "greenhouse cultivation",
    # ===== WATER & WASTEWATER =====
    "wasser": "water tap water",
    "trinkwasser": "tap water drinking water",
    "grundwasser": "groundwater well",
    "regenwasser": "rainwater",
    "abwasser": "wastewater treatment",
    "klaeranlage": "wastewater treatment plant",
    "kläranlage": "wastewater treatment plant",
    "klaerschlamm": "sewage sludge",
    "klärschlamm": "sewage sludge",
    # ===== WASTE & DISPOSAL =====
    "abfall": "waste treatment disposal",
    "muell": "waste municipal solid",
    "müll": "waste municipal solid",
    "restmuell": "waste municipal solid incineration",
    "restmüll": "waste municipal solid incineration",
    "muellverbrennung": "waste incineration municipal",
    "müllverbrennung": "waste incineration municipal",
    "deponie": "landfill disposal",
    "sondermuell": "hazardous waste treatment",
    "sondermüll": "hazardous waste treatment",
    "schrott": "scrap metal recycling",
    "altpapier": "waste paper recycling",
    "altglas": "waste glass recycling",
    "altmetall": "scrap metal recycling",
    "elektronikschrott": "waste electric electronic equipment WEEE",
    "elektroschrott": "waste electric electronic equipment WEEE",
    "bioabfall": "biowaste composting",
    "kompost": "composting biowaste",
    "schlacke": "slag ash",
    "asche": "ash bottom fly",
    # ===== ELECTRONICS & IT =====
    "computer": "computer desktop",
    "laptop": "laptop notebook computer",
    "notebook": "laptop notebook computer",
    "server": "computer server rack",
    "monitor": "display screen LCD",
    "bildschirm": "display screen LCD",
    "drucker": "printer",
    "handy": "mobile phone smartphone",
    "smartphone": "mobile phone smartphone",
    "tablet": "tablet computer",
    "batterie": "battery",
    "akku": "battery rechargeable lithium",
    "lithiumbatterie": "battery lithium ion",
    "kabel": "cable electric",
    "trafo": "transformer",
    "transformator": "transformer",
    "kondensator": "capacitor",
    "leiterplatte": "printed circuit board PCB",
    "halbleiter": "semiconductor",
    "solarzelle": "photovoltaic cell solar",
    "solarmodul": "photovoltaic panel module",
    "windturbine": "wind turbine",
    "windkraftanlage": "wind turbine power plant",
    "led": "light emitting diode LED",
    "leuchtmittel": "lamp light",
    "gluehbirne": "lamp incandescent light",
    "glühbirne": "lamp incandescent light",
    # ===== VEHICLES & MACHINERY =====
    "fahrzeug": "vehicle passenger car",
    "personenwagen": "passenger car",
    "elektroauto": "electric vehicle passenger car battery",
    "hybridauto": "hybrid vehicle passenger car",
    "lastkraftwagen": "lorry truck",
    "anhaenger": "trailer",
    "anhänger": "trailer",
    "motor": "engine motor combustion",
    "generator": "generator electric",
    "kompressor": "compressor",
    "pumpe": "pump",
    "ventilator": "fan ventilation",
    "klimaanlage": "air conditioning",
    "lueftung": "ventilation HVAC",
    "lüftung": "ventilation HVAC",
    "heizkessel": "boiler heating",
    "kessel": "boiler",
    "ofen": "furnace oven",
    "trockner": "dryer drying",
    "waschmaschine": "washing machine",
    "kuehlschrank": "refrigerator",
    "kühlschrank": "refrigerator",
    "kuehlung": "cooling refrigeration",
    "kühlung": "cooling refrigeration",
    # ===== PROCESSES =====
    "verbrennung": "combustion burned burning",
    "herstellung": "production manufacturing",
    "produktion": "production manufacturing",
    "fertigung": "manufacturing production",
    "montage": "assembly",
    "entsorgung": "disposal waste treatment",
    "recycling": "recycling",
    "transport": "transport freight",
    "heizung": "heating heat",
    "kuehlen": "cooling refrigeration",
    "kühlen": "cooling refrigeration",
    "trocknen": "drying",
    "mahlen": "milling grinding",
    "schneiden": "cutting",
    "schweissen": "welding",
    "schweißen": "welding",
    "loeten": "soldering",
    "löten": "soldering",
    "giessen": "casting foundry",
    "gießen": "casting foundry",
    "schmieden": "forging",
    "walzen": "rolling metal",
    "extrudieren": "extrusion",
    "spritzgiessen": "injection moulding",
    "spritzgießen": "injection moulding",
    "pressen": "pressing",
    "destillation": "distillation",
    "raffinerie": "refinery petroleum",
    "veredelung": "finishing treatment",
    "beschichten": "coating",
    "galvanisieren": "electroplating zinc chromium",
    "eloxieren": "anodising aluminium",
    "verzinken": "zinc coating galvanising",
    "beizen": "pickling acid treatment",
    "haerten": "hardening heat treatment",
    "härten": "hardening heat treatment",
    "verpacken": "packaging",
    "lagern": "storage warehousing",
    "reinigen": "cleaning",
    # ===== OFFICE & SERVICES =====
    "buero": "office",
    "büro": "office",
    "hotel": "hotel guest night accommodation",
    "uebernachtung": "hotel guest night",
    "übernachtung": "hotel guest night",
    "kantine": "meal restaurant catering",
    "catering": "meal restaurant catering",
    "drucken": "printing paper",
    "kopieren": "printing paper copying",
    "reinigung": "cleaning",
    "gebaeude": "building construction",
    "gebäude": "building construction",
    "buerogebaeude": "office building",
    "bürogebäude": "office building",
}


def translate_terms(text: str) -> str:
    """Expand German terms with English translations for better retrieval.

    Checks each word (and 2-word combinations) in the text against
    TERM_TRANSLATIONS and appends English equivalents. The original text
    is preserved.
    """
    words = text.strip().lower().split()
    additions: list[str] = []
    matched_indices: set[int] = set()

    # First pass: check 2-word combinations (e.g., "lkw transport")
    for i in range(len(words) - 1):
        bigram = words[i].strip() + words[i + 1].strip()
        bigram_clean = unidecode(bigram)
        if bigram_clean in TERM_TRANSLATIONS:
            additions.append(TERM_TRANSLATIONS[bigram_clean])
            matched_indices.add(i)
            matched_indices.add(i + 1)
        elif bigram in TERM_TRANSLATIONS:
            additions.append(TERM_TRANSLATIONS[bigram])
            matched_indices.add(i)
            matched_indices.add(i + 1)

    # Second pass: single words (skip already matched in bigrams)
    for i, word in enumerate(words):
        if i in matched_indices:
            continue
        clean = unidecode(word.strip())
        if clean in TERM_TRANSLATIONS:
            additions.append(TERM_TRANSLATIONS[clean])
        # Check original (with umlauts) too
        original = word.strip()
        if original in TERM_TRANSLATIONS and TERM_TRANSLATIONS[original] not in additions:
            additions.append(TERM_TRANSLATIONS[original])

    if additions:
        return text + " " + " ".join(additions)
    return text


def normalize_query(text: str) -> str:
    """Normalize text for search: lowercase, strip, collapse whitespace, transliterate."""
    text = text.strip().lower()
    text = unidecode(text)  # ä -> a, ö -> o, ü -> u, ß -> ss
    text = re.sub(r"\s+", " ", text)
    return text


def tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer for BM25."""
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return text.split()


# ---------------------------------------------------------------------------
# CandidateRetriever
# ---------------------------------------------------------------------------

class CandidateRetriever:
    """Hybrid BM25 + embedding search with region/unit filtering."""

    def __init__(
        self,
        store: DatasetStore,
        embedding_index: EmbeddingIndex,
        rrf_k: int = 60,
    ):
        self.store = store
        self.embedding_index = embedding_index
        self.rrf_k = rrf_k

        # Build BM25 index from non-market rows
        self._bm25: Optional[BM25Okapi] = None
        self._bm25_ids: list[int] = []
        self._bm25_rows: dict[int, DatasetRow] = {}

    def initialize(self):
        """Build BM25 index. Call once after DatasetStore is initialized."""
        logger.info("Building BM25 index...")
        texts_with_ids = self.store.get_non_market_search_texts()
        self._bm25_ids = [t[0] for t in texts_with_ids]
        tokenized = [tokenize(t[1]) for t in texts_with_ids]
        self._bm25 = BM25Okapi(tokenized)
        logger.info(f"BM25 index built with {len(self._bm25_ids)} documents")

    def retrieve(
        self,
        bezeichnung: str,
        produktinfo: str,
        referenzeinheit: str,
        region: Optional[str],
        top_k: int = 50,
        scope: Optional[str] = None,
        kategorie: Optional[str] = None,
    ) -> RetrievalResult:
        """Retrieve candidate datasets for an input row.

        Returns RetrievalResult with either candidates or force_decompose=True.
        """
        # Step 1: Map unit and check existence
        mapped_unit = map_unit(referenzeinheit)
        db_units = self.store.get_all_units()

        if mapped_unit is None or mapped_unit not in db_units:
            return RetrievalResult(
                force_decompose=True,
                force_decompose_reason=(
                    f"Unit '{referenzeinheit}' (mapped: {mapped_unit}) "
                    f"not found in database. Available units: {sorted(db_units)}"
                ),
            )

        # Step 2: Build query text with enhanced context
        # Translate German terms to English for better ecoinvent matching
        translated_bezeichnung = translate_terms(bezeichnung)
        query_parts = [translated_bezeichnung]

        if produktinfo:
            translated_produktinfo = translate_terms(produktinfo)
            query_parts.append(translated_produktinfo)

        # Add scope context hints for better semantic matching
        if scope:
            if "Scope 1" in scope or "1." in scope:
                # Scope 1: Direct emissions, typically combustion
                query_parts.append("combustion burned fuel")
            elif "Scope 3" in scope or "3." in scope:
                # Scope 3: Indirect emissions, typically production/manufacturing
                query_parts.append("production manufacturing")

        # Add category context if available
        if kategorie:
            translated_kategorie = translate_terms(kategorie)
            query_parts.append(translated_kategorie)

        query = normalize_query(" ".join(query_parts))
        if not query.strip():
            return RetrievalResult(
                force_decompose=True,
                force_decompose_reason="Empty query after normalization",
            )

        # Step 3: BM25 search
        bm25_results = self._bm25_search(query, top_n=100)

        # Step 4: Embedding search
        embed_results = self._embedding_search(query, top_n=100)

        # Step 5: Reciprocal Rank Fusion
        fused = self._rrf_merge(bm25_results, embed_results)

        # Step 6: Region priority + unit filtering
        region_norm = (region or "GLO").strip().upper()
        region_priority = self._build_region_priority(region_norm)

        scored_candidates = []
        for row_id, rrf_score, bm25_rank, embed_rank in fused:
            ds = self.store.get_dataset_by_id(row_id)
            if ds is None:
                continue

            # Compute region priority
            reg_prio = region_priority.get(ds.geography, 3)

            scored_candidates.append(
                CandidateResult(
                    dataset=ds,
                    bm25_rank=bm25_rank,
                    embedding_rank=embed_rank,
                    fused_score=rrf_score,
                    region_priority=reg_prio,
                )
            )

        # Sort: region priority first, then fused score (descending)
        scored_candidates.sort(key=lambda c: (c.region_priority, -c.fused_score))

        # Filter to preferred unit matches, but include others if few matches
        unit_matched = [c for c in scored_candidates if c.dataset.unit == mapped_unit]
        unit_other = [c for c in scored_candidates if c.dataset.unit != mapped_unit]

        if len(unit_matched) >= top_k:
            final = unit_matched[:top_k]
        else:
            # Fill with non-unit-matched candidates
            final = unit_matched + unit_other[: top_k - len(unit_matched)]

        return RetrievalResult(
            force_decompose=False,
            candidates=final,
            query_used=query,
        )

    def _bm25_search(self, query: str, top_n: int = 100) -> list[tuple[int, float]]:
        """BM25 search returning (dataset_row_id, score) pairs. Higher=better."""
        if self._bm25 is None:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        # Get top N indices
        top_indices = scores.argsort()[-top_n:][::-1]
        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append((self._bm25_ids[idx], float(scores[idx])))
        return results

    def _embedding_search(self, query: str, top_n: int = 100) -> list[tuple[int, float]]:
        """Embedding search returning (dataset_row_id, score) pairs. Higher=better."""
        if not self.embedding_index.is_loaded:
            return []
        return self.embedding_index.search(query, top_k=top_n)

    def _rrf_merge(
        self,
        bm25_results: list[tuple[int, float]],
        embed_results: list[tuple[int, float]],
    ) -> list[tuple[int, float, Optional[int], Optional[int]]]:
        """Reciprocal Rank Fusion: merge two ranked lists.

        Returns list of (row_id, rrf_score, bm25_rank, embed_rank).
        """
        k = self.rrf_k
        scores: dict[int, float] = {}
        bm25_ranks: dict[int, int] = {}
        embed_ranks: dict[int, int] = {}

        for rank, (row_id, _) in enumerate(bm25_results):
            scores[row_id] = scores.get(row_id, 0) + 1.0 / (k + rank + 1)
            bm25_ranks[row_id] = rank + 1

        for rank, (row_id, _) in enumerate(embed_results):
            scores[row_id] = scores.get(row_id, 0) + 1.0 / (k + rank + 1)
            embed_ranks[row_id] = rank + 1

        merged = sorted(scores.items(), key=lambda x: -x[1])
        return [
            (row_id, score, bm25_ranks.get(row_id), embed_ranks.get(row_id))
            for row_id, score in merged
        ]

    def _build_region_priority(self, requested_region: str) -> dict[str, int]:
        """Build region -> priority mapping.

        0 = exact match, 1 = GLO, 2 = RoW, 3 = other.
        """
        prio: dict[str, int] = {requested_region: 0}
        if requested_region != "GLO":
            prio["GLO"] = 1
        if requested_region != "RoW":
            prio["RoW"] = 2
        return prio
