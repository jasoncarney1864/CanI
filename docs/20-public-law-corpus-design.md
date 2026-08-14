# 20. Public-Law Corpus Design (CanI Docs / Legal spoke)

**Status:** Design accepted — open questions resolved by Jason 2026-08-13 (§20.12); not implemented
**Last updated:** 2026-08-13
**Depends on:** docs/08 (RAG pipeline), docs/09 (data model), docs/14 (security)

## 20.1 What this adds and what it must never do

Today the Legal spoke answers "what does my document say" against the user's own uploads
(e.g. their HOA's CC&Rs). This feature adds a second, shared corpus of governing public
law so the system can also answer "is what they're doing even legal to begin with."

**v1 scope (per Q1, §20.12): state law only — NRS Chapter 116.** County code (Washoe)
and federal sources are designed for below but explicitly deferred; nothing in v1 may
depend on them. The corpus model, schema, and fetcher contract still accommodate all
three levels so the deferred sources are registry rows + one fetcher module away, not a
redesign.

Product principles this design is built around, in priority order:

1. **Never alter the semantics or spirit of the law.** This is a plain-language
   *translation layer*, not reinterpretation. Every answer that draws on the law corpus
   must pair the plain-English explanation with the **verbatim quoted source text** and a
   proper citation (e.g. "NRS 116.31065"). A paraphrase-only summary of law is a bug.
2. **Attribution is structural, not stylistic.** The answer must make it unambiguous
   which claims come from the user's document and which come from statute/code — carried
   in typed citation metadata, not just prose phrasing the model chooses.
3. **Not legal advice.** The existing Legal-spoke disclaimer stays; law citations
   additionally surface *when the law text was fetched*, because statutes amend.
4. **Lightweight and free.** No live per-query calls to external services. Sources are
   periodically fetched, snapshotted, chunked, and embedded into our own store — the same
   pipeline shape user documents already use.

## 20.2 Approach in one paragraph

A new shared (non-user-owned) corpus lives in a **second Qdrant collection**, fed by a
**scheduled refresh job** that fetches each registered jurisdiction source, snapshots the
raw response to blob storage, parses it into **statute-section-aligned chunks** (one
chunk = one citable section wherever possible), and embeds/upserts only sections whose
content hash changed. `retrieval-worker` embeds the query once and searches **both**
collections — the user's owner-scoped collection exactly as today, plus the law
collection filtered by jurisdiction — then grounds an answer over a context window with
per-chunk source labels, returning citations extended with `source_kind`, citation
string, source URL, and the verbatim quote.

## 20.3 Why a second collection, not a "system owner" in the existing one

The obvious alternative is a reserved system user (e.g. a well-known UUID) that "owns"
the law corpus inside the existing collection, reusing `OwnerScopedQdrant` unchanged.
Rejected, for the same reason the wrapper exists at all:

- The tenant-isolation invariant (docs/08 §8.8, docs/09 §9.6: *no query without an owner
  filter, re-verify owner on every returned point*) is currently simple enough to audit
  by reading one class. A magic shared owner punches a permanent hole in that invariant —
  every future reader must know "owner filter mandatory, except this one UUID."
- The law corpus has a different lifecycle: it gets **rebuilt wholesale** on schema or
  parser changes, and re-fetched on a schedule. A separate collection can be dropped and
  rebuilt without any risk to user vectors, and can carry its own payload indexes
  (`jurisdiction`, `source_kind`, `law_source_id`) without widening the user collection's
  index set.
- Isolation failure modes become one-directional: a bug in law-corpus code can at worst
  return wrong *public* law text; it cannot leak one user's content to another, because
  it never touches the user collection.

So: new collection, default name `cani-public-law` (configurable, §20.9), same embedder
and vector size as the user collection (the query is embedded once and reused for both
searches), with the same `VectorDimensionMismatchError` tripwire on startup — this is the
guard that caught the fakes-in-prod incident class (see CLAUDE.md), and the law
collection needs it for the same reason.

New wrapper class alongside `OwnerScopedQdrant` in
`apps/shared-lib/cani_shared/vector/qdrant_client.py` (or a sibling module
`public_law_client.py` if the file gets long):

```python
class PublicLawQdrant:
    """Read/write access to the shared public-law collection. No owner filter — the
    corpus is public by definition — but search REQUIRES a non-empty jurisdiction
    filter, enforced the same fail-closed way OwnerScopedQdrant enforces owner:
    there is no method that searches the whole corpus unscoped."""

    def ensure_collection(self, vector_size: int) -> None: ...   # same 409-tolerant + dimension-assert pattern
    def upsert_section(self, *, vector, payload, point_id) -> str: ...
    def delete_points(self, point_ids: list[str]) -> None: ...   # for repealed/removed sections
    def search(self, *, query_vector, jurisdictions: list[str], limit: int = 8) -> list[ScoredChunk]: ...
```

Payload indexes: `jurisdiction`, `source_kind`, `law_source_id` (KEYWORD), mirroring how
`ensure_collection` creates the user collection's indexes today.

### Law chunk payload

Mirrors the user-chunk payload where the concepts overlap, so retrieval-worker can treat
both uniformly, plus law-specific fields:

| Field | Example | Notes |
|---|---|---|
| `chunk_id` | uuid | matches `law_chunk_manifests.chunk_id` |
| `chunk_text` | verbatim section text | **exact source text — this is what gets quoted** |
| `source_kind` | `state_statute` \| `county_code` \| `federal_statute` \| `federal_regulation` | |
| `jurisdiction` | `us-nv`, `us-nv-washoe`, `us` | hierarchical slug, filterable |
| `law_source_id` | uuid of registry row | |
| `citation` | `NRS 116.31065` | canonical human citation, rendered verbatim in answers |
| `heading` | `NRS 116.31065  Rules.` | section heading as published |
| `source_url` | `https://www.leg.state.nv.us/NRS/NRS-116.html#NRS116Sec31065` | deep link with anchor |
| `chunk_index` | int | document order within the source |
| `fetched_at` | ISO timestamp | when we captured this text — surfaces in the citation |
| `content_sha256` | hash of `chunk_text` | change detection (§20.7) |
| `embedding_version` | as today | same drift guard as user chunks |

No `page_start`/`page_end` — statutes cite by section, not page (§20.8 covers the
`Citation` model consequences).

## 20.4 Data model: migration `db/migrations/0005_public_law_corpus.sql`

Three tables, following the existing naming and indexing style of `0001_core_schema.sql`.
None carry `owner_user_id` — that is deliberate and should be called out in the migration
comment, since it is the first schema in the system that is *not* user-scoped.

```sql
-- Registry of external law sources. One row per fetchable unit (an NRS chapter, a
-- county code, a CFR title part). Shared corpus: intentionally NOT owner-scoped.
CREATE TABLE IF NOT EXISTS law_sources (
    law_source_id   UUID PRIMARY KEY,
    source_key      TEXT NOT NULL UNIQUE,   -- stable machine key, e.g. 'nrs-116', 'washoe-county-code'
    display_name    TEXT NOT NULL,          -- 'Nevada Revised Statutes, Chapter 116'
    source_kind     TEXT NOT NULL,          -- state_statute | county_code | federal_statute | federal_regulation
    jurisdiction    TEXT NOT NULL,          -- 'us-nv', 'us-nv-washoe', 'us'
    citation_prefix TEXT NOT NULL,          -- 'NRS 116', 'WCC'
    fetch_url       TEXT NOT NULL,
    license_note    TEXT NOT NULL,          -- provenance/terms note, e.g. 'public record; scraped from NV Legislature site'
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per successful fetch that produced new content. blob_uri points at the raw
-- snapshot (audit trail + re-chunk without re-fetch). checksum is over the raw bytes:
-- an unchanged fetch records last_checked_at on law_sources but inserts no version row.
CREATE TABLE IF NOT EXISTS law_source_versions (
    law_source_version_id UUID PRIMARY KEY,
    law_source_id         UUID NOT NULL REFERENCES law_sources(law_source_id),
    fetched_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    blob_uri              TEXT NOT NULL,
    checksum              TEXT NOT NULL,
    section_count         INT,
    status                TEXT NOT NULL   -- fetched | chunked | indexed | failed
);
CREATE INDEX IF NOT EXISTS idx_law_source_versions_source
    ON law_source_versions (law_source_id, fetched_at DESC);

-- Law-corpus analogue of chunk_manifests: Postgres is the ledger of what is in Qdrant,
-- keyed the same way, so drift between the two stores is detectable and repairable.
CREATE TABLE IF NOT EXISTS law_chunk_manifests (
    chunk_id              UUID PRIMARY KEY,
    law_source_version_id UUID NOT NULL REFERENCES law_source_versions(law_source_version_id),
    law_source_id         UUID NOT NULL REFERENCES law_sources(law_source_id),
    citation              TEXT NOT NULL,
    heading               TEXT,
    source_url            TEXT NOT NULL,
    chunk_index           INT NOT NULL,
    token_count           INT NOT NULL,
    content_sha256        TEXT NOT NULL,
    embedding_version     TEXT NOT NULL,
    qdrant_point_id       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_law_chunk_manifests_source
    ON law_chunk_manifests (law_source_id, citation);
```

Plus `last_checked_at TIMESTAMPTZ` on `law_sources` (updated even when content is
unchanged, so "is the refresh job alive" is observable from SQL).

Repository functions go in `cani_shared/db/repositories.py` next to their user-corpus
analogues: `list_enabled_law_sources`, `create_law_source_version`,
`get_latest_law_chunk_manifests(law_source_id)`, `replace_law_chunk_manifests`,
`touch_law_source_checked`.

Raw snapshots land in a new blob container `public-law-snapshots`
(`cani_shared/blob.py`: add `PUBLIC_LAW_SNAPSHOTS_CONTAINER` to `_ALL_CONTAINERS`), path
`{source_key}/{law_source_version_id}/raw.{ext}`.

## 20.5 New shared module: `cani_shared/law/`

All law-corpus logic that more than one service touches lives in shared-lib, per the
"most changes start here" convention:

```
apps/shared-lib/cani_shared/law/
    __init__.py
    models.py        # LawSection, FetchedLawDocument dataclasses
    fetcher.py       # LawSourceFetcher ABC + FakeLawFetcher
    sources/
        __init__.py  # SOURCE_REGISTRY: source_key -> fetcher class
        nrs.py       # NrsChapterFetcher (NRS 116 first) — the only source module in v1
        # municode.py (Washoe County) is NOT built in v1 — on hold per §20.12 Q1
    sectioner.py     # section-aligned chunking for statute text
```

### 20.5.1 Fetcher contract (`fetcher.py`)

```python
@dataclass
class LawSection:
    citation: str        # 'NRS 116.31065'
    heading: str | None  # 'Rules.'
    text: str            # verbatim section body — never normalized beyond whitespace
    source_url: str      # deep link incl. anchor
    order: int

@dataclass
class FetchedLawDocument:
    raw_bytes: bytes         # exactly what the wire returned — snapshotted to blob as-is
    content_type: str
    sections: list[LawSection]

class LawSourceFetcher(ABC):
    source_key: str
    @abstractmethod
    def fetch(self) -> FetchedLawDocument: ...
```

Fetch and parse are one step on purpose: each source's parser is coupled to that source's
markup, and keeping them together means a markup change breaks loudly inside the one
module that owns that source. Parsers must be **lossless on section text** — trim
whitespace, decode entities, nothing else. The verbatim-quote guarantee (§20.1 principle
1) is only as good as this code.

Fetchers use `httpx` (already a dependency; also the CLAUDE.md-mandated choice over curl)
with: a descriptive `User-Agent` including a contact address, conditional GET
(`If-None-Match`/`If-Modified-Since`) where the server supports it, a fixed ~1 req/sec
politeness delay for multi-page sources, and no concurrency. These are public,
zero-budget government sites; being a polite scraper is both ethics and self-interest.

HTML parsing needs a real parser — **new dependency: `beautifulsoup4`** (pure Python, no
native wheels, so no Windows-on-ARM venv hazard). Regexing statute HTML is how semantics
get silently mangled.

### 20.5.2 First source: NRS Chapter 116 (`sources/nrs.py`)

The Nevada Legislature publishes each NRS chapter as a single static HTML page —
`https://www.leg.state.nv.us/NRS/NRS-116.html` — with per-section anchors
(`#NRS116Sec31065` style) and a consistent heading pattern (`NRS 116.31065  Rules.`).
State statute text is a public record; no API, no auth, one GET per chapter. This is the
easiest possible first source and it exercises the entire pipeline.

`NrsChapterFetcher(chapter='116')` is parameterized by chapter so NRS 118A (landlord–
tenant) etc. are a registry row away, not new code.

### 20.5.3 Deferred source: Washoe County code (`sources/municode.py`) — ON HOLD (Q1)

**Decision 2026-08-13: skip county code entirely for this phase.** Do not build the
fetcher, and do not pursue Municode or county access yet — state-law-only is the actual
v1 scope, not an interim. This section stays as design context for when the hold lifts.

Washoe County's code is hosted on Municode (`library.municode.com/nv/washoe_county`),
which is a JS-rendered SPA — the HTML page is not scrapable with a plain GET. The SPA is
fed by a JSON backend (`api.municode.com`) that returns clean structured content, but it
is **unofficial and Municode's terms of use restrict automated access**. The county's
*law* is public domain; Municode's *platform* is not ours to hammer. Two facts recorded
for the future revisit: the county clerk also self-hosts a county-code page at
`washoecounty.gov/clerks/cco/county_code.php` (a possible non-Municode source), and the
citation convention is confirmed as `WCC <chapter>.<section>` (see Q6, §20.12). The
fetcher contract above is deliberately source-shaped so whichever access path is chosen
later (Municode JSON, county-provided PDFs + existing extractor) slots in without
touching the rest of the pipeline.

### 20.5.4 Federal sources (later phase, easier than expected)

The "no official APIs" premise actually inverts at the federal level: the **eCFR has an
official public REST API** (ecfr.gov), and the **US Code is published as bulk USLM XML**
by the Office of the Law Revision Counsel (uscode.house.gov). Both are free, official,
and fit the fetch-and-cache pattern *better* than scraping. Federal is therefore
scheduled last not because it is hard but because Fair Housing Act / FCC OTARD-type
federal questions are rarer for the HOA use case than NRS 116 questions.

### 20.5.5 Section-aligned chunking (`sectioner.py`)

The generic chunker (`cani_shared/chunking.py`) targets 600–900 tokens with overlap and
guesses section boundaries from heading heuristics. For law, boundaries are **known
exactly** (the fetcher already produced `LawSection`s), and overlap is actively harmful —
a chunk that straddles NRS 116.31065 and 116.31067 can produce a quote attributed to the
wrong section, which violates principle 1.

`sectioner.py` therefore maps sections to chunks directly:

- One `LawSection` → one chunk, carrying the section's citation, when the section fits
  the existing `TARGET_MAX_TOKENS` budget (nearly all NRS 116 sections do).
- Oversized sections split at subsection boundaries (`1.`, `(a)` markers), **without
  overlap**, each part keeping the parent citation plus a part suffix in `chunk_index`
  order. A split never crosses a section boundary.
- Token counting reuses `_count_tokens`/tiktoken from `chunking.py` so budgets stay
  consistent with the user corpus.

## 20.6 Provider-factory fit (`cani_shared/providers/factory.py`)

The factory's job is "single place that decides real-vs-fake from config so services
agree." The law corpus adds one builder in the same shape:

```python
def build_law_fetchers(settings: Settings) -> dict[str, LawSourceFetcher]:
    """Real HTTP fetchers when external fetching is enabled; deterministic fakes
    otherwise, so CI and unit tests never touch government websites."""
    if settings.law_fetch_enabled:
        return {key: cls() for key, cls in SOURCE_REGISTRY.items()}
    return {key: FakeLawFetcher(key) for key in SOURCE_REGISTRY}
```

`FakeLawFetcher` serves a bundled, trimmed excerpt of real NRS 116 text (public record,
fine to vendor as a test fixture under `tests/fixtures/law/`) — deterministic sections,
stable checksums, no network. Same philosophy as `FakeEmbedder`/`FakeGrounder`.

**Fail-open lesson applied:** the fakes-in-prod sprint happened because nothing errored
when config was absent. Two mitigations here: (1) `law_fetch_enabled` is an **explicit
flag**, not inferred from credential presence — there are no credentials to infer from,
and silently deciding "no config → fake law" in prod would re-run that incident with
statutes; (2) the refresh job logs `law_refresh_completed` with `fetcher_kind=real|fake`
per source, and the law collection's `ensure_collection` carries the same
dimension-mismatch tripwire as the user collection.

Embedder and vector client are **reused as-is** via the existing `build_embedder` — the
law corpus must live in the same embedding space as queries, and recording
`embedding_version` per chunk keeps the drift guard intact.

## 20.7 The refresh job

**Where it runs:** a new entrypoint in the ingestion-worker package —
`apps/ingestion-worker/ingestion_worker_app/law_refresh.py` with a
`python -m ingestion_worker_app.law_refresh` main. Not a new `apps/` package: it shares
every dependency ingestion already has (blob, embedder, Qdrant, repositories, chunk
budget), and a sixth installable package is overhead a solo-dev monorepo doesn't need.
Not woven into the poll loop either: law refresh is scheduled batch work, not
queue-driven per-user work, and mixing them couples a scraper's failure modes into the
user ingestion path.

**How it's scheduled:** dev/local — run manually or via `scripts/refresh_law_corpus.py`.
Prod — a **scheduled Azure Container Apps Job** (weekly, e.g. Monday 09:00 UTC) in
`infra/container-apps/`, following the pattern the migration-runner job already
established there. Cost between runs: zero. Statutes change on legislative-session
timescales; weekly is generous.

**Per-source flow (idempotent, diff-based):**

1. `fetch()` → raw bytes + parsed sections.
2. SHA-256 the raw bytes; if unchanged vs. the source's latest version row → touch
   `last_checked_at`, done. (Analogue of the per-owner checksum dedupe on upload.)
3. Snapshot raw bytes to `public-law-snapshots`; insert `law_source_versions` row.
4. Run `sectioner`; hash each chunk's text.
5. Diff against `get_latest_law_chunk_manifests(law_source_id)` by citation:
   - **unchanged** section → keep the existing point (no re-embed — this is the free-tier
     cost control; a chapter amendment re-embeds only amended sections);
   - **new/changed** → embed and upsert with a **deterministic point id**:
     `uuid5(LAW_NS, f"{source_key}:{citation}:{part}")`, so re-upserts replace in place
     and the collection never accumulates stale duplicates of a section;
   - **removed** (repealed) → `delete_points` the orphaned ids.
6. Replace the manifest rows; mark the version `indexed`.

Failures are per-source: one broken parser (NRS markup change) logs `law_source_failed`
and moves on; it must never block other sources. The previous good version stays live in
Qdrant — a failed refresh degrades to "slightly staler law," never to "no law."

## 20.8 Retrieval and answer assembly (`retrieval-worker`)

### Search: two corpora, two budgets

`RetrieveRequest` (and docs-api's pass-through `QueryRequest`) gains:

```python
class RetrieveRequest(BaseModel):
    question: str
    spoke: str = "General"
    include_public_law: bool | None = None   # None -> defaults to (spoke == "Legal")
    jurisdictions: list[str] | None = None   # None -> settings.law_default_jurisdictions
```

### Jurisdiction selection: the state picker (Q2, decided)

Jurisdiction comes from a **"select your state" dropdown in the web app's Legal spoke**
— the "select your store" pattern (à la Walmart/Best Buy), decided over a hub-api
profile field to keep v1 simple:

- **Session-level, client-side.** The selection persists in the browser (localStorage)
  and is sent as `jurisdictions` on every `/query`. No new hub-api endpoint, no schema
  change, no profile migration. A profile field can be layered on later as the *default*
  for the picker if users want stickiness across devices; the request contract doesn't
  change either way.
- **State level only.** The dropdown lists states; county granularity waits for county
  sources (Q1). Selecting a state maps to its jurisdiction slug (`Nevada` → `us-nv`).
- **Multi-state by construction, one state at launch.** The dropdown renders from a
  `SUPPORTED_STATES` list (slug + display name) in `apps/web` — shipping with exactly
  one entry, Nevada. Adding a state later is: a `law_sources` registry row + fetcher
  params for that state's statutes, plus one entry in this list. Nothing else changes.
- With one supported state the picker is effectively informative rather than a choice —
  that's fine; it sets the UX contract now so multi-state later is not a redesign.

Flow in `retrieve()`:

1. Embed the question once (unchanged).
2. Owner-scoped search of the user collection — **byte-for-byte the code that exists
   today**, including the retry wrapper and lazy init.
3. If public law is in play: `PublicLawQdrant.search(jurisdictions=...)`, wrapped in the
   same `retry_transient`. A law-search failure degrades the answer to document-only
   (with a note in the response), it does not 500 the query — the user's own document is
   the primary corpus and its availability shouldn't depend on the secondary one.
4. **Fixed per-corpus budgets, not merged ranking:** top 4 user chunks + top 3 law chunks
   (tunable constants next to `CONTEXT_TOP_K`). Scores are technically comparable (same
   embedder, cosine) but statutory boilerplate reliably out-scores messy scanned CC&Rs on
   generic legal phrasing; a merged pool would starve the user's own document, and the
   product wants *both* perspectives present ("your document says X; the statute says Y").

### Grounding: labeled context, quote-paired output

`ChatGrounder.ground` changes signature from `context_chunks: list[str]` to a list of
labeled chunks:

```python
@dataclass
class ContextChunk:
    text: str
    source_label: str   # 'your document "Shadow Ridge CC&Rs", §7.2' | 'NRS 116.31065 (Nevada state law)'
    source_kind: str    # 'user_document' | 'state_statute' | 'county_code' | ...
```

`_build_user_prompt` renders `[chunk:N | {source_label}] {text}` so the model always
knows which corpus a passage came from. `SYSTEM_PROMPT` gains rules enforcing the
product principles (additions, not a rewrite — the injection-guardrail and
answer-only-from-context rules stand):

- Structure answers that use both corpora as **"What your document says"** then **"What
  the governing law says"** then, only if both are present, how they relate.
- Every claim about the law must be **paired with a short verbatim quote** from the law
  chunk it came from, in quotation marks with its citation. Plain-language explanation
  *accompanies* the quote; it never replaces it.
- Explain, never characterize: say what the quoted text states; do not label conduct
  "illegal"/"legal" beyond what the quoted text itself says; if document and statute
  appear to conflict, present both texts and note the apparent tension rather than
  adjudicating it.

The `[chunk:N]` marker mechanism and `used_chunk_indices` parsing are unchanged — indices
now span the concatenated (user + law) context list.

### Citations: extended, backward-compatibly

`Citation` in `cani_shared/models.py` currently hard-requires `document_id`,
`page_start`, `page_end` — meaningless for a statute. Extend rather than fork, so the
web app's existing rendering keeps working for document citations:

```python
class Citation(BaseModel):
    source_kind: str = "user_document"        # discriminator, default keeps old payloads valid
    # user-document fields, now optional (absent on law citations)
    document_id: str | None = None
    document_title: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    section_label: str | None = None
    chunk_id: str
    snippet: str | None = None                # verbatim text — for law citations this IS the quoted statute
    # law-corpus fields (absent on user-document citations)
    citation_ref: str | None = None           # 'NRS 116.31065'
    source_url: str | None = None
    law_fetched_at: datetime | None = None    # honesty about currency: 'text as of <date>'
```

Making `page_start`/`page_end` optional is a **breaking model change for
`apps/web`** — the client must branch its citation card on `source_kind` (document card
with page + Document Viewer spotlight vs. law card with citation ref, quote, deep link,
and fetched date). Flagged as UI work in §20.11.

The Legal-spoke disclaimer prefix in `retrieve()` extends when law citations are present:
statute text is reproduced as fetched on the cited date and may have been amended since.
Per **Q3 (decided)**, the quiet per-citation "as of {date}" stamp is the *whole*
staleness story — no escalating warning banner. The product explicitly gives no legal
advice, only a semantics-preserving translation, so a dated citation is sufficient
disclosure.

### Verdicts (Q4, decided)

**Suppress the yes/no verdict badge whenever any law chunk was cited.** The badge
("Yes / No / Yes, with conditions") reads as exactly the legal *opinion* principle 1
forbids when the question is "is this legal." Suppression is scoped narrowly: **only the
badge disappears** — the law citations, verbatim quotes, and plain-language explanation
all still render. Implementation: in `retrieve()`, when the citation list contains any
`source_kind != "user_document"`, set `verdict=None` on the `RetrievalAnswer` regardless
of what the grounder emitted (and keep the grounder-side marker handling unchanged, so
document-only answers keep their badge exactly as today).

## 20.9 Config additions (`cani_shared/config.py`, `.env.example`)

Following the explicit-`alias` convention:

```python
law_fetch_enabled: bool = Field(default=False, alias="CANI_LAW_FETCH_ENABLED")
law_qdrant_collection: str = Field(default="", alias="CANI_LAW_QDRANT_COLLECTION")   # empty -> feature off at query time
law_default_jurisdictions: str = Field(default="us-nv", alias="CANI_LAW_DEFAULT_JURISDICTIONS")  # comma-separated; state-only in v1 (Q1/Q2) — 'us' joins when federal ships, 'us-nv-washoe' if/when county code does
```

`law_qdrant_collection` empty ⇒ retrieval-worker never constructs `PublicLawQdrant` and
behavior is exactly today's — the whole feature ships dark and turns on per environment.
Both flags documented in `.env.example`; Container Apps Bicep gains them for prod (the
recent "wire keys into Container Apps" commit is the pattern to follow).

## 20.10 Testing

- **Unit** (`tests/unit/`, no network — enforced by the fake factory):
  - `nrs.py` parser against a vendored trimmed `NRS-116.html` fixture: section count,
    exact citation strings, **byte-exact section text** (the lossless guarantee gets a
    literal string-equality test), anchor URLs.
  - `sectioner.py`: one-section-one-chunk, oversize split at subsection boundaries, no
    overlap, no cross-section bleed.
  - Refresh diff logic: unchanged → no re-embed; changed → deterministic point id reused;
    removed → deleted. (Fake embedder + a stub Qdrant recording calls.)
  - Citation assembly: law chunk → `source_kind`, `citation_ref`, quote, no page fields;
    old-payload compatibility (payload without law fields still validates).
  - Grounder prompt: labeled context rendering; verdict suppression when law chunks cited.
- **Integration** (`tests/integration/`, compose): seed the law collection via
  `FakeLawFetcher` + fake embedder, upload a small CC&Rs fixture, `/query` on the Legal
  spoke, assert the answer carries citations of **both** source kinds and that each law
  citation's `snippet` is a verbatim substring of the fixture statute text. The verbatim
  check is the product principle turned into CI.

## 20.11 Phasing (updated for the §20.12 decisions)

| Phase | Scope | Gate |
|---|---|---|
| 1 | Migration 0005, `cani_shared/law/` with **NRS fetcher + sectioner only** (no `sources/municode.py`), `PublicLawQdrant`, refresh entrypoint, unit tests. Ships dark. | — |
| 2 | Retrieval dual-search, grounder labeling + prompt, `Citation` extension, **verdict suppression on law-cited answers (Q4)**, config flags, integration test. No readiness tripwire (Q5: on hold). Enable in dev. | Phase 1 |
| 3 | `apps/web`: citation cards branched on `source_kind` with quote + "as of {date}" stamp (Q3: no staleness banner); **state jurisdiction dropdown** (Q2: session-level, `SUPPORTED_STATES` = Nevada only). Enable in prod. | Phase 2 |
| 4 | More NRS chapters (118A etc.) as registry rows; more states in the dropdown as their statute fetchers land. | demand |
| 5 | Federal: eCFR API + USLM US Code fetchers; add `us` to default jurisdictions. | demand |
| — (held) | Washoe County code source. **On hold per Q1** — no fetcher, no access outreach, until the hold is revisited. Citation format pre-verified (Q6): `WCC <chapter>.<section>`. | revisit Q1 |

## 20.12 Decision log (all questions resolved by Jason, 2026-08-13)

- **Q1 — Washoe County / Municode access: HOLD — skip county code entirely.** Not built,
  and no access outreach to Municode or the county either. State-law-only (NRS 116) is
  the actual v1 scope, not an interim. §20.5.3 is retained as design context; two facts
  are pre-recorded there for the eventual revisit (the county clerk's self-hosted code
  page at washoecounty.gov, and the confirmed citation format — see Q6).
- **Q2 — Jurisdiction selection: state-level dropdown picker in the UI** ("select your
  store" pattern), session-level and client-side (localStorage → `jurisdictions` on each
  query), not a hub-api profile field for v1. State granularity only; the dropdown
  renders from a multi-state-capable `SUPPORTED_STATES` list that ships with exactly one
  entry, **Nevada**. Adding states later = a registry row + fetcher params + one list
  entry. Details in §20.8.
- **Q3 — Staleness disclosure: quiet per-citation "as of {date}" stamp only.** No
  escalating warning banner. Rationale (Jason): the product explicitly gives no legal
  advice — it translates legalese into plain language without altering semantics — so a
  dated citation is sufficient disclosure. Weekly refresh cadence stands.
- **Q4 — Verdict badge: confirmed, suppress when any law citation is involved** — but
  *only* the yes/no badge. The citation, verbatim quote, and plain-language translation
  still render in full. Mechanically: `verdict=None` on the response whenever the
  citation list contains a non-`user_document` source kind (§20.8).
- **Q5 — Empty-collection tripwire: HOLD — do not build the readiness check.**
  Rationale (Jason): unproven problem; with effectively one user who understands the
  system's current state, the silent-empty-fallback risk is low. Graceful degradation to
  document-only answers stands as designed. Revisit when there are more users or the
  silent fallback demonstrably causes confusion.
- **Q6 — County citation format: verified 2026-08-13** (ahead of need, since Q1 is
  held). Washoe County cites its code as `WCC <chapter>.<section>` — e.g. WCC 10.050,
  WCC 125.010 — matching this doc's assumption. Sources: the county's own code pages
  ([washoecounty.gov](https://www.washoecounty.gov/clerks/cco/county_code.php),
  [code-compliance FAQ](https://www.washoecounty.gov/csd/planning_and_development/code_enforcement/common_questions_codeenf.php))
  and [Municode's Washoe County library](https://library.municode.com/nv/washoe_county).
  `citation_prefix='WCC'` is safe to bake in whenever the county source ships.
