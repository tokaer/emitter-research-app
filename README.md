# Emitter Research App

A batch emission factor matching application that maps product inputs to ecoinvent 3.11 datasets using hybrid search and Claude AI for intelligent candidate selection and decomposition.

## Overview

This application helps automate greenhouse gas (GHG) accounting by:
1. **Uploading** Excel templates with product/activity data
2. **Searching** 25,411 ecoinvent 3.11 emission datasets using hybrid BM25 + semantic search
3. **Matching** products to appropriate datasets via Claude AI
4. **Decomposing** complex products into components when no direct match exists
5. **Calculating** biogenic and common CO2-equivalent emissions
6. **Exporting** results to Excel with full provenance

## Architecture

### Tech Stack

**Backend**:
- FastAPI (Python 3.9.6)
- SQLite with FTS5 (full-text search)
- FAISS vector index (17,586 searchable activities)
- BM25Okapi (keyword search)
- Anthropic Claude API (Sonnet model)
- sentence-transformers (`paraphrase-multilingual-MiniLM-L12-v2`)

**Frontend**:
- React + TypeScript + Vite
- Zustand (state management)
- Tailwind CSS v4
- TanStack Table (data grids)

### Data Flow

```
Excel Upload → Normalization → Hybrid Search (BM25 + Embeddings)
    ↓
Claude AI Decision (Match / Ambiguous / Decompose)
    ↓
├─ Match:       Calculate emissions directly
├─ Ambiguous:   User selects from candidates
└─ Decompose:   Break into 3-10 components → Sub-search → Calculate sum
    ↓
Export Results (Biogenic, Common, Beschreibung, Quelle)
```

## Key Features

### 1. Hybrid Search
- **BM25**: Keyword-based ranking (top 100)
- **Embeddings**: Semantic similarity via FAISS (top 100)
- **Reciprocal Rank Fusion**: Merge results with RRF score
- **Region Priority**: Requested > GLO > RoW > Others
- **Unit Filtering**: Prioritize matching units (kg, kWh, MJ, m², etc.)

### 2. Intelligent Matching (Claude AI)
- **Match**: Single best dataset selected
- **Ambiguous**: Multiple plausible candidates (user picks)
- **Decompose**: Product broken into 3-10 components
  - Categories: materials, energy, packaging, transport, processes
  - Each component gets sub-searched and matched
  - Max 1 level deep (no nested decomposition)

### 3. Scope-Aware Search
The system uses GHG Protocol scope context to improve search quality:
- **Scope 1**: Prioritizes combustion/burning processes (e.g., "diesel, burned in building")
- **Scope 2**: Electricity, heat, steam supply
- **Scope 3**: Production/manufacturing processes (e.g., "steel, at plant")

### 4. Output Fields
Each processed row produces:
- **Biogene Emissionen** [t CO2-Eq]: Biogenic emissions
- **Common Factor** [t CO2-Eq]: Non-biogenic emissions
- **Beschreibung** (≤1000 chars): Calculation summary
- **Quelle** (≤1000 chars): ecoinvent 3.11 UUIDs (up to 10)
- **Detailed Calculation**: Full breakdown with all assumptions

### 5. Unit Mapping
German units automatically mapped to ecoinvent:
- Stück → unit
- Liter → l
- Kilogramm → kg
- Kilowattstunde → kWh
- Quadratmeter → m2
- ...and more

## Processing Pipeline

Detailed step-by-step flow for each input row. Steps marked with **LLM** require a Claude API call; all others are deterministic algorithms.

### Pipeline Overview

```
Upload ──> Normalize ──> Retrieve Candidates ──> LLM Decision ──> Calculate ──> Export
  [algo]     [algo]          [algo]               [LLM]           [algo]       [algo]
```

### Step-by-Step Flow

#### Step 1: Upload & Normalization `[Algorithm]`

| Action | Method | Details |
|--------|--------|---------|
| Parse Excel | `template_parser.py` | Read .xlsx columns, validate required fields |
| Normalize Bezeichnung | String ops | Lowercase, strip, transliterate (ä→a, ö→o) |
| Map Region | Lookup table | "Europa" → "RER", "Deutschland" → "DE" |
| Map Unit | `UNIT_MAP` dict | "Stück" → "unit", "Liter" → "l", "Kilogramm" → "kg" |

**No LLM needed** - pure string operations and lookup tables.

#### Step 2: Candidate Retrieval `[Algorithm]`

| Action | Method | Details |
|--------|--------|---------|
| BM25 Search | `rank_bm25` | Keyword match against 17,586 activities → top 100 |
| Embedding Search | FAISS + MiniLM-L12 | Semantic similarity → top 100 |
| Reciprocal Rank Fusion | RRF formula | Merge both lists: `score = Σ 1/(k + rank)` |
| Scope Hint | String append | Scope 1 → adds "combustion burned fuel" to query |
| Region Sorting | Priority map | Exact match (0) > GLO (1) > RoW (2) > other (3) |
| Unit Filtering | String compare | Prefer candidates matching the mapped unit |
| Top-K Selection | Slice | Return top 20 candidates |

**No LLM needed** - BM25 is statistical, FAISS is vector math, RRF is arithmetic.

#### Step 3: LLM Decision `[LLM Call #1]`

The LLM receives the input description + 20 candidates and decides:

```
                        ┌─────────────────┐
  Input + Candidates ──>│  Claude Sonnet   │──> decision
                        │  (temp=0, p=0.2) │
                        └─────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                 ▼
          "match"         "ambiguous"       "decompose"
        1 best fit       2+ plausible      no fit found
```

**Decision rules** (enforced via prompt):

| Decision | Condition | Example |
|----------|-----------|---------|
| `match` | Exactly 1 plausible candidate | "Stahl" → only one steel production dataset |
| `ambiguous` | 2+ plausible candidates with different contexts, geographies, or specs | "Diesel Verbrennung" → burned in building machine / fishing vessel / agricultural machinery |
| `decompose` | No single candidate matches (complex product) | "Hamburger" → needs beef + bun + cheese + vegetables |

**Never decomposed**: Simple activities (Diesel, Benzin, Strom, Transport, Heizung, basic materials) always use match or ambiguous.

#### Step 4a: Match Flow

```
  UUID selected
       │
       ▼
  ┌──────────────────┐
  │ Validate UUID     │ [Algorithm] - exists in DB? not a market activity?
  └────────┬─────────┘
           ▼
  ┌──────────────────┐     Units equal?
  │ Compare Units     │ ──────────────── yes ──> quantity = 1.0
  └────────┬─────────┘                            │
           │ no                                   │
           ▼                                      │
  ┌──────────────────┐                            │
  │ Unit Conversion   │ [LLM Call #2]             │
  │ "1L Diesel=36MJ" │                            │
  └────────┬─────────┘                            │
           │ quantity = conversion_factor          │
           ▼                                      ▼
  ┌───────────────────────────────────────────────────────┐
  │ Calculate Emissions                        [Algorithm] │
  │                                                        │
  │   biogenic_kg  = db_value × quantity                   │
  │   common_kg    = db_value × quantity                   │
  │   biogenic_t   = biogenic_kg / 1000                    │
  │   common_t     = common_kg / 1000                      │
  └────────┬──────────────────────────────────────────────┘
           ▼
  ┌──────────────────┐
  │ Build Output      │ [Algorithm] - Beschreibung, Quelle, Provenance
  └──────────────────┘
```

#### Step 4b: Ambiguous Flow

```
  Candidate list (10+ options)
       │
       ▼
  ┌──────────────────┐
  │ Save to DB        │ [Algorithm] - store candidates as JSON
  │ Status: ambiguous │
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │ User selects      │ [Frontend UI] - user picks the correct dataset
  │ via Resolve tab   │
  └────────┬─────────┘
           ▼
       Continue with Match Flow (Step 4a)
```

#### Step 4c: Decompose Flow

```
  Components from LLM (3-10 parts, sum = 1.0 reference unit)
       │
       ▼  FOR EACH COMPONENT:
  ┌──────────────────┐
  │ Sub-Retrieval     │ [Algorithm] - same hybrid search per component
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │ Component Match   │ [LLM Call #2..#N] - match each component
  │ (no decompose!)   │   to an ecoinvent dataset
  └────────┬─────────┘
           ▼
  AFTER ALL COMPONENTS:
  ┌──────────────────┐
  │ Sum Validation    │ [Algorithm] - verify Σ quantities ≈ 1.0
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │ Calculate per     │ [Algorithm] - emission × quantity per component
  │ component + sum   │              then sum all components
  └──────────────────┘
```

### LLM Call Summary

| Scenario | LLM Calls | Example |
|----------|-----------|---------|
| Match, same unit | **1** | "Stahl, kg" → 1× decide |
| Match, different unit | **2** | "Diesel, Liter" → 1× decide + 1× convert_unit |
| Ambiguous | **1** | "Diesel Verbrennung" → 1× decide, user selects manually |
| Ambiguous + different unit | **1 + 1** | decide + convert_unit after user selection |
| Decompose (5 components) | **1 + 5** | 1× decide(=decompose) + 5× component matching |
| Decompose (10 components) | **1 + 10** | 1× decide(=decompose) + 10× component matching |

### What the LLM Does vs. What Algorithms Do

| Task | Method | Why |
|------|--------|-----|
| **Semantic matching** (which dataset fits "Diesel Verbrennung"?) | LLM | Requires understanding of German product names, GHG scopes, and ecoinvent naming conventions |
| **Decomposition** (break "Hamburger" into physical components) | LLM | Requires world knowledge about product composition |
| **Unit conversion** (1 Liter Diesel = ? MJ) | LLM | Open-ended conversions including product-specific densities, energy content, and potentially monetary/daily-rate conversions |
| Candidate retrieval (find relevant datasets) | Algorithm | BM25 + FAISS + RRF - statistical and vector-based |
| Emission calculation (multiply + convert kg→t) | Algorithm | Pure arithmetic: `value × quantity / 1000` |
| Validation (UUID exists? market activity?) | Algorithm | Database lookups |
| Output formatting (Beschreibung, Quelle) | Algorithm | String templates with character limits |
| Region/unit mapping | Algorithm | Lookup tables (UNIT_MAP, region normalization) |

### Rate Limiting

- **API limit**: 10,000 input tokens/minute (Anthropic)
- **Per-request**: ~2,000 tokens (20 candidates × ~100 tokens each)
- **Mitigation**: 15-second delay between rows, `max_retries=5` with exponential backoff
- **Decomposition retry**: If component sum ≠ 1.0, LLM is asked to correct (up to 3 attempts)

## Installation

### Prerequisites
- Python 3.9.6+
- Node.js 18+
- Anthropic API key

### Backend Setup

```bash
cd backend

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cat > .env << EOF
ANTHROPIC_API_KEY=your_api_key_here
LLM_MODEL=claude-sonnet-4-20250514
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
EOF

# Build database and FAISS index (one-time, ~2 minutes)
python -m scripts.build_index
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```

## Usage

### 1. Start Servers

**Backend**:
```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Frontend**:
```bash
cd frontend
npm run dev
# Opens at http://localhost:5173
```

### 2. Upload Data

**Excel Template** must have columns:
- Scope (optional)
- Kategorie (optional)
- Unterkategorie (optional)
- Bezeichnung (required) - Product/activity name
- Produktinformationen (optional) - Additional context
- Referenzeinheit (required) - Unit (kg, Liter, Stück, kWh, etc.)
- Region (optional) - Geographic region (default: GLO)
- Referenzjahr (optional) - Reference year

### 3. Processing Modes

**Auto Mode**:
- Automatically picks top candidate for ambiguous matches
- Fastest processing

**Review Mode**:
- Pauses for user review on ambiguous matches
- More control over selections

### 4. Resolve Ambiguities

If rows are marked "ambiguous":
1. Switch to **Resolve** tab
2. Expand each ambiguous row
3. Select the best matching candidate
4. Click "Confirm" or use batch confirm

### 5. Export Results

Click **Export Excel** to download:
- All input columns
- Biogene Emissionen [t CO2-Eq]
- Common Factor [t CO2-Eq]
- Beschreibung
- Quelle (ecoinvent UUIDs)
- Detailed Calculation

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/upload` | Upload Excel template |
| POST | `/api/v1/jobs` | Create empty job |
| GET | `/api/v1/jobs/{id}` | Get job status |
| GET | `/api/v1/jobs/{id}/rows` | List input rows + results |
| POST | `/api/v1/jobs/{id}/rows` | Add manual row |
| PUT | `/api/v1/jobs/{id}/rows/{rid}` | Edit row |
| DELETE | `/api/v1/jobs/{id}/rows/{rid}` | Delete row |
| POST | `/api/v1/jobs/{id}/process` | Start batch processing |
| GET | `/api/v1/jobs/{id}/progress` | Poll processing status |
| GET | `/api/v1/jobs/{id}/ambiguities` | List unresolved ambiguities |
| POST | `/api/v1/jobs/{id}/rows/{rid}/resolve` | Resolve single ambiguity |
| POST | `/api/v1/jobs/{id}/resolve-batch` | Batch resolve |
| GET | `/api/v1/jobs/{id}/export` | Download Excel results |

## Data Facts

- **Total datasets**: 25,412 (ecoinvent 3.11)
- **Searchable activities**: 17,586 (market rows excluded)
- **Supported units**: 18 (kg, kWh, MJ, m², m³, l, km, ha, hour, unit, etc.)
- **Max components**: 10 per decomposition
- **UUID limit**: ~10 UUIDs fit in 1000-char Quelle field
- **Embedding dimensions**: 384 (multilingual model supports German→English)

## Configuration

### Backend (`.env`)

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional (defaults shown)
LLM_MODEL=claude-sonnet-4-20250514
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
CSV_PATH=../data/Cut-off Cumulative LCIA v3.11 Kopie.csv
DB_PATH=../data/emitter.db
FAISS_INDEX_PATH=../data/embeddings/index.faiss
FAISS_METADATA_PATH=../data/embeddings/metadata.pkl
CANDIDATE_TOP_K=20
RRF_K=60
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

### Frontend (`vite.config.ts`)

Proxies `/api` requests to `http://localhost:8000` automatically.

## Critical Implementation Details

### Thread-Safe SQLite
Each thread gets its own connection via `threading.local()`:
```python
_thread_local = threading.local()

def connect():
    if not hasattr(_thread_local, 'conn'):
        _thread_local.conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            timeout=30.0,
        )
        _thread_local.conn.execute("PRAGMA busy_timeout=30000")
    return _thread_local.conn
```
This prevents `disk I/O error` during concurrent decomposition processing.

### Nested Decomposition Prevention
Component searches call `llm.decide()` with `allow_decompose=False`:
```python
comp_decision = llm.decide(
    comp_input,
    sub_retrieval.candidates,
    allow_decompose=False  # Prevents nested decomposition
)
```

### Rate Limiting
Anthropic client automatically retries 429 errors with exponential backoff.

## Testing Examples

```bash
# Test simple match
curl -X POST http://localhost:8000/api/v1/jobs
JOB_ID=<job_id>

curl -X POST http://localhost:8000/api/v1/jobs/$JOB_ID/rows \
  -H "Content-Type: application/json" \
  -d '{
    "bezeichnung": "Diesel",
    "produktinformationen": "",
    "referenzeinheit": "Liter",
    "region": "RER",
    "scope": "Scope 1",
    "kategorie": "Kraftstoffe",
    "referenzjahr": ""
  }'

curl -X POST http://localhost:8000/api/v1/jobs/$JOB_ID/process \
  -H "Content-Type: application/json" \
  -d '{"mode": "auto"}'

# Poll progress
curl http://localhost:8000/api/v1/jobs/$JOB_ID/progress
```

## Troubleshooting

### Server won't start
- Check `ANTHROPIC_API_KEY` in `.env`
- Verify database exists: `ls ../data/emitter.db`
- Rebuild index: `python -m scripts.build_index`

### "Unit not found" errors
Check unit mapping in `backend/app/services/candidate_retriever.py` → `UNIT_MAP`

### Processing hangs
- Check Claude API rate limits (429 errors in logs)
- Server automatically retries with backoff
- Reduce batch size if needed

### Frontend shows 500 errors
- Check backend logs: `tail -f /tmp/uvicorn.log`
- Verify API key is valid
- Restart backend server

## Development

### Run Tests
```bash
cd backend
pytest tests/
```

### Rebuild Database
```bash
cd backend
python -m scripts.build_index
```

### Code Structure
```
backend/
  app/
    main.py              # FastAPI app
    config.py            # Settings
    models.py            # Pydantic schemas
    routers/             # API endpoints
    services/            # Core business logic
    prompts/             # LLM prompts
  scripts/
    build_index.py       # DB + FAISS builder

frontend/
  src/
    App.tsx              # Main app
    store/               # Zustand state
    components/          # React components
    api/                 # API client
```

## License

Proprietary - Internal use only

## Support

For issues or questions, contact the development team.
