# Haq: Low-Level Design

**Related documents:** [High-level design](HLD.md) · [Implementation plan](IMPLEMENTATION_PLAN.md) · [Stress test](STRESS_TEST.md)

Numeric thresholds here are starting values, to be tuned against real documents in phase 6.

## 1. Repository layout

```
backend/
  app/
    main.py                 # app factory, startup recovery
    config.py               # pydantic-settings
    api/                    # documents.py runs.py qa.py health.py errors.py
    graph/
      state.py  build.py  runner.py  events.py
      nodes/                # acquire parse segment triage extract verify
                            # compile_rules evaluate script translate guard tts
    acquisition/            # fetchers.py ssrf.py validate.py
    documents/              # extract.py garble.py ocr.py tables.py segment.py normalize.py
    claims/                 # schemas.py verifier.py numbers.py
    eligibility/            # ast.py interpreter.py fields.py next_question.py
    voice/                  # translate.py guard.py tts.py stt.py
    qa/                     # retrieve.py answer.py
    profiles/               # store.py
    providers/              # gateway.py gemini.py openai.py sarvam.py ratelimit.py budget.py
    db/                     # models.py session.py migrations/
    prompts/                # triage.md extract.md entail.md rules.md script.md backtranslate.md qa.md
  tests/                    # unit/ integration/ fixtures/ eval/
  Dockerfile  pyproject.toml
frontend/
  app/                      # page.tsx  runs/[id]/page.tsx
  components/               # SourceInput AgentTrace RightsCard EligibilityPanel
                            # AudioPlayer PdfViewer ProvenanceBadge
  lib/                      # api.ts useRunStream.ts types.ts
docker-compose.yml  Caddyfile  .env.example  README.md
```

## 2. Configuration

| Variable | Purpose |
|---|---|
| `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `STORAGE_BUCKET` | Data services |
| `GEMINI_API_KEY`, `OPENAI_API_KEY`, `SARVAM_API_KEY` | Providers |
| `LLM_PRIMARY_MODEL`, `LLM_FALLBACK_MODEL`, `OCR_MODEL`, `EMBEDDING_MODEL`, `EMBEDDING_DIM` | Fixed at hour 0 from the providers' live model lists |
| `PRIMARY_PROVIDER=gemini` | `gemini` or `openai`: tried first for LLM calls and OCR, with the other as the fallback if configured. `LLM_FALLBACK_MODEL` names the OpenAI model either way. Embeddings always use Gemini, because vectors from different models can't be compared |
| `TTS_MODEL`, `TRANSLATE_MODEL`, `STT_MODEL` | Default `bulbul:v4-flash`, `sarvam-translate:v1`, `saaras:v4` |
| `MAX_CONCURRENT_RUNS=3`, `MAX_LLM_CALLS=60`, `RUN_TIMEOUT_S=420` | Limits |
| `LLM_FAST_MODEL` | Used for triage, which only decides whether to carry on |
| `MAX_PDF_MB=50`, `MAX_PAGES=200`, `PROFILE_TTL_S=3600` | Limits |
| `CROSS_PROVIDER_VERIFY=false` | Use the other provider for entailment |
| `ALLOWED_ORIGINS` | CORS |

## 3. Database schema

```sql
CREATE TABLE documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sha256 char(64) UNIQUE NOT NULL,
  source_url text,                -- null for uploads
  fetch_method text NOT NULL,     -- http | browser | upload
  fetched_at timestamptz NOT NULL,
  storage_path text NOT NULL,
  title text, issuing_authority text, issue_date date,
  page_count int NOT NULL, is_scanned boolean NOT NULL DEFAULT false,
  in_library boolean NOT NULL DEFAULT false
);

CREATE TABLE clauses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES documents ON DELETE CASCADE,
  ordinal int NOT NULL, page int NOT NULL,
  bbox real[4],                   -- null for OCR clauses
  text text NOT NULL, norm_text text NOT NULL, lang text NOT NULL,
  kind text NOT NULL,             -- para | table_row | heading
  extraction text NOT NULL,       -- native | ocr
  embedding vector(/* EMBEDDING_DIM */),
  UNIQUE (document_id, ordinal)
);

CREATE TABLE runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid REFERENCES documents,  -- null until acquired
  language text NOT NULL,
  status text NOT NULL,   -- queued running waiting_input completed partial failed
  source jsonb NOT NULL,  -- upload path and hash, or URL; lets a queued run restart
  error_code text, llm_calls int NOT NULL DEFAULT 0,
  sarvam_chars int NOT NULL DEFAULT 0, client_hash text,
  created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz
);

CREATE TABLE run_events (
  run_id uuid REFERENCES runs ON DELETE CASCADE,
  seq int, type text NOT NULL, payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, seq)
);

CREATE TABLE claims (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES runs ON DELETE CASCADE,
  field text NOT NULL,   -- benefit eligibility document deadline authority obligation penalty
  text text NOT NULL, clause_ids uuid[] NOT NULL, quote text,
  status text NOT NULL,  -- pending verified not_stated
  failure_reason text, attempts int NOT NULL DEFAULT 0
);

CREATE TABLE rules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES runs ON DELETE CASCADE,
  claim_id uuid NOT NULL REFERENCES claims,
  ast jsonb NOT NULL, fields_required text[] NOT NULL
);

CREATE TABLE sentences (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES runs ON DELETE CASCADE,
  ordinal int NOT NULL, language text NOT NULL,
  source_text text NOT NULL, translated_text text,
  claim_ids uuid[] NOT NULL, audio_path text,
  guard_status text NOT NULL, -- pending passed flagged
  translator text,            -- sarvam | llm
  UNIQUE (run_id, language, ordinal)
);
```

## 4. Graph

### 4.1 State

```python
class RunState(TypedDict):
    run_id: str
    language: str
    source: SourceRequest
    document_id: str | None
    claim_ids: list[str]
    verify_attempts: dict[str, int]
    guard_attempts: dict[str, int]
    pending_fields: list[str]         # field names only
    verdict: Verdict | None           # outcomes only, never input values
    sentence_ids: list[str]
    partial: bool
```

Graph state is **ID-based**, because LangGraph saves it to Postgres on every step. Rows stay in their tables, which keeps checkpoints small.

**Profile values are never placed in graph state, because checkpoints would write them to disk.** Nodes read them through `ProfileStore`:

```python
class ProfileStore:                    # dict guarded by asyncio.Lock
    def get(self, run_id) -> dict: ...
    def merge(self, run_id, values: dict) -> None: ...   # refreshes the TTL
    def purge_expired(self) -> None: ...                 # background task, every 60 s
```

After a restart the profile is gone. `evaluate` then finds missing fields and asks for them again, which is the intended behaviour.

### 4.2 Execution rules

- `runner.py` starts each run as an `asyncio.Task` behind `Semaphore(MAX_CONCURRENT_RUNS)`.
- Startup finds runs marked `running` and resumes each from its checkpoint.
- `interrupt()` restarts a node from its top on resume, so **every node must be idempotent**. Each one checks existing rows and upserts on natural keys.
- The 180-second limit pauses while `waiting_input`.
- `events.emit()` inserts into `run_events`, allocating `seq`, then wakes in-memory subscribers.

### 4.3 Node contracts

| Node | Reads | Writes | Events | Failure |
|---|---|---|---|---|
| `acquire` | Source | `documents` | `fetch_attempt` | `SOURCE_UNREACHABLE`, ask for upload |
| `parse` | PDF | Page cache | `page_ocr` | `PDF_INVALID`, `PDF_ENCRYPTED` |
| `segment` | Pages | `clauses` | `segment_done` | `DOC_TOO_LONG`, ask for a page range |
| `triage` | Clause sample | Document metadata | `triage_result` | Not a policy: end run cleanly |
| `extract` | Clauses, failure reasons | `claims` | `claim_extracted` | Repair, then failover |
| `verify` | Claims, clauses | Claim status | `claim_verified`, `claim_rejected`, `retry` | After 2 retries: `not_stated` |
| `compile_rules` | Eligibility claims | `rules` | `rules_compiled` | Invalid AST: `Unevaluable` |
| `evaluate` | Rules, ProfileStore | `verdict`, `pending_fields` | `needs_input`, `verdict` | Pure code; interrupts for data |
| `script` | Verified claims, verdict | `sentences` | `script_ready` | Drops sentences without valid claim IDs |
| `translate` | Sentences | `translated_text` | `sentence_translated`, `failover` | Sarvam, then LLM |
| `guard` | Both texts | `guard_status` | `guard_failed`, `retry` | After 2 retries: `flagged` |
| `tts` | Passed sentences | `audio_path` | `sentence_ready` | Text-only result |

### 4.4 Routing

```python
route_after_triage  -> extract | END
route_after_verify  -> extract if any(pending and attempts < 2) else compile_rules
route_after_guard   -> translate if any(failed and attempts < 2) else tts
```

The retried `extract` receives only the failed claims and their reasons. If `budget.exhausted()`, routing skips forward, with `partial=True`.

## 5. Source acquisition

```python
async def acquire(req):
    if req.upload: return validate_and_store(req.upload, method="upload")
    check_url(req.url)                         # before any request
    for fetcher in (http_fetch, browser_fetch):
        result = await fetcher(req.url)        # re-checks each redirect
        if result.is_pdf: return validate_and_store(result, method=result.method)
        if result.pdf_links: return await choose_or_ask(result.pdf_links)
    raise SourceUnreachable(attempts)
```

| Concern | Rule |
|---|---|
| Schemes and ports | `http` or `https`, ports 80 and 443 only |
| SSRF | Resolve DNS and reject private, loopback, link-local, multicast and metadata addresses, including every redirect target. Max 5 redirects |
| Browser tier | All Chromium traffic goes through `GuardedProxy`, which applies these rules to every connection. Playwright's route handler only sees the first URL of a redirect chain, so it can't enforce them alone. The proxy also caps total bytes |
| Refused fetches | `blocked` and `too_large` end the run with `URL_BLOCKED` or `FILE_TOO_LARGE`. The browser tier isn't tried, because it would fetch the same address or file |
| TLS | Verify using certifi plus any missing government intermediates we add. Never disable verification |
| Limits | 45 s, 50 MB while streaming |
| File validation | `%PDF-` header, opens in PyMuPDF, not encrypted, at least 1 page |
| HTML page with PDF links | One link: follow. Several: the run ends with `MULTIPLE_PDFS`, with `details.options` as `[{url, label}]`. The UI starts a new run with the chosen URL |
| Deduplication | SHA-256 match reuses stored clauses and saves LLM cost |

## 6. Document intelligence

### 6.1 Per-page routing

```python
def needs_ocr(page) -> bool:
    text = page.get_text()
    if len(text.strip()) < 40: return True            # scan or image page
    if replacement_ratio(text) > 0.02: return True
    if has_broken_shaping(text): return True
    if legacy_font_pattern(page, text): return True
    if has_figure(page) and len(text.strip()) < 300: return True   # chart with a caption
    return False
```

`has_figure` means images covering at least 15% of the page, or more than 50 vector drawings. On the PMAY-G Hindi booklet, a page with a one-line heading had its amounts only inside a chart image, so the text layer alone lost them.

`has_broken_shaping` catches a corruption found on most pages of every Devanagari PDF we tested, in valid Unicode and with modern fonts: `ग्ामीीण` for `ग्रामीण`. It counts sequences no font can produce: a repeated vowel sign, a vowel sign after a virama, and a vowel sign with no consonant. These PDFs go to OCR, so Hindi documents depend on OCR quota and speed. A page with little text and no images is kept as it is, and doesn't use OCR.

`legacy_font_pattern` flags two things: font names containing `Kruti`, `DevLys`, `Chanakya` or `Shusha`, and pages with an expected Hindi context but Latin text with a low dictionary-word ratio and many unusual symbols. Tune it on real Hindi PDFs in phase 2.

### 6.2 OCR

Render at 200 DPI and send to `OCR_MODEL`, then `OCR_FALLBACK_MODEL`, with a prompt requiring a JSON list of `{kind, text}` in reading order. Language comes from our own detection. Text must be copied exactly and illegible parts marked `[illegible]`. Run up to 5 pages concurrently, and record failed pages so they appear in the UI. OCR clauses have `bbox = NULL`.

Gemini refuses pages that quote known text such as a statute, returning `finishReason=RECITATION` on every model. Those pages go to `LLM_FALLBACK_MODEL` on OpenAI if it is configured. Otherwise they are recorded as failed with reason `recitation`, and the run ends as `partial`. We do not try to get around the refusal.

Each page is saved to `document_pages` as soon as it's read, so a retry or a later run of the same file only reads the pages still missing. A run that times out can therefore be started again without losing progress. When a later run recovers a page, the document's ordinals are renumbered so they stay in reading order. Citations store clause ids, so they stay valid.

### 6.3 Segmentation

1. Take PyMuPDF text blocks in reading order, and drop repeated headers and footers.
2. Convert each `find_tables()` row to `Header: value; Header: value`, as `kind=table_row`, only if every column boundary has a drawn vertical rule. Without rules PyMuPDF guesses columns from the text, which put a Day Scholars amount under the wrong header on a real scheme table, so those pages stay plain text with no added labels.
3. Merge broken lines, and split on numbered items (`1.`, `(a)`, `3.2`) and blank lines.
4. Split clauses over 1,200 characters at sentence boundaries, using `।` as well as `.`.
5. Detect language by Unicode script, with a library check for English and Latin text.

### 6.4 Normalisation

`norm_text` = Unicode NFC, Devanagari and Bengali digits converted to 0-9, curly quotes unified, whitespace collapsed, case folded. Verification always compares normalised forms, while the UI shows the original text.

### 6.5 Embeddings

Embed each clause with `EMBEDDING_MODEL` in batches. Retrieval filters by `document_id`, so a full scan is fast enough and no vector index is needed.

## 7. Claims engine

### 7.1 Schemas

```python
class CandidateClaim(BaseModel):
    field: Literal["benefit","eligibility","document","deadline",
                   "authority","obligation","penalty"]
    text: str = Field(max_length=300)    # one atomic fact in plain English
    clause_ordinals: list[int] = Field(min_length=1, max_length=3)
    quote: str = Field(max_length=500)   # verbatim, in the source language

class ExtractionResult(BaseModel):
    title: str | None
    issuing_authority: str | None
    issue_date: date | None
    claims: list[CandidateClaim]
    not_stated: list[str]                # requested fields absent from the document
```

Prompts refer to clauses by `ordinal`, which is shorter and safer than UUIDs.

### 7.2 Extraction input

| Document size | Input |
|---|---|
| 30 pages or fewer | All clauses |
| More than 30 pages | For each claim field, the top 60 clauses by embedding similarity to a fixed field query, plus all headings |

Clauses are sent inside `<document>` tags as `[ordinal] text`. The prompt states that the text is untrusted data, and any instructions inside it must be ignored.

### 7.3 Verifier

```python
async def verify_claim(claim, clauses) -> Verification:
    cited = [clauses.get(o) for o in claim.clause_ordinals]
    if None in cited:                       return fail("CLAUSE_NOT_FOUND")
    source = " ".join(c.norm_text for c in cited)
    quote = normalize(claim.quote)
    ocr = any(c.extraction == "ocr" for c in cited)
    ok = partial_ratio(quote, source) >= 92 if ocr else quote in source
    if not ok:                              return fail("QUOTE_NOT_IN_SOURCE")
    if not numbers(claim.text) <= numbers(claim.quote):
                                            return fail("NUMBER_NOT_IN_QUOTE")
    label = await entail(claim.text, cited)  # ENTAILED | PARTIAL | NOT_ENTAILED
    if label != "ENTAILED":                 return fail(label)
    return ok_result()
```

The cheap checks run first. Entailment is judged in batches of 8 claims per call, which keeps long documents inside `MAX_LLM_CALLS`. For OCR clauses a fuzzy match would accept `3.5 lakh` for `2.5 lakh`, so the quote's numbers must also appear exactly in the source. Quotes under 8 characters fail as `QUOTE_TOO_SHORT`. A claim the entailment reply skips counts as `NOT_ENTAILED`. A quote from a Hindi source can back an English claim, because entailment works across languages and `numbers()` normalises digit systems.

### 7.4 Number parsing

`numbers.parse()` returns canonical values for:

| Input | Canonical |
|---|---|
| `₹2,50,000`, `Rs. 250000`, `2.5 lakh`, `2.5 लाख`, `ढाई लाख` | `INR:250000` |
| `1 crore`, `1 करोड़` | `INR:10000000` |
| `5%`, `5 percent`, `5 प्रतिशत` | `PCT:5` |
| `31 March 2027`, `31-03-2027`, `31 मार्च 2027` | `DATE:2027-03-31` |
| Others | `NUM:value` |

This module has the most edge cases and gets the most unit tests. An unparseable numeric-looking token counts as a failure, because a false rejection is safer than a wrong amount.

## 8. Eligibility engine

### 8.1 AST

```python
class Cmp(BaseModel):
    type: Literal["cmp"]; field: str
    op: Literal["eq","ne","lt","lte","gt","gte","in","not_in"]
    value: int | float | str | bool | list[str]

class And(BaseModel): type: Literal["and"]; items: list["Expr"]
class Or(BaseModel):  type: Literal["or"];  items: list["Expr"]
class Not(BaseModel): type: Literal["not"]; item: "Expr"
class Unevaluable(BaseModel): type: Literal["unevaluable"]; source_text: str

Expr = Annotated[Cmp | And | Or | Not | Unevaluable, Field(discriminator="type")]
```

### 8.2 Three-valued evaluation

```python
def ev(e, p) -> Tri:   # TRUE, FALSE, UNKNOWN
    match e:
        case Cmp():         return UNKNOWN if e.field not in p else compare(p[e.field], e.op, e.value)
        case Not():         return tri_not(ev(e.item, p))
        case And():         return FALSE if FALSE in vals(e) else UNKNOWN if UNKNOWN in vals(e) else TRUE
        case Or():          return TRUE  if TRUE  in vals(e) else UNKNOWN if UNKNOWN in vals(e) else FALSE
        case Unevaluable(): return UNKNOWN
```

| Result | Verdict |
|---|---|
| Any rule `FALSE` | `DOES_NOT_MEET`, naming the rule and clause |
| Unknown with askable fields | `NEEDS_INFO` |
| Unknown from `Unevaluable` only | `CANNOT_DETERMINE` |
| All `TRUE` | `MEETS_STATED_CRITERIA` |

### 8.3 Fields

```python
class FieldDef(BaseModel):
    name: str; type: Literal["int","float","bool","enum","str"]
    options: list[str] | None; min: float | None; max: float | None
    question_en: str; unit: str | None
```

- **Registry:** `age`, `gender`, `state`, `district`, `annual_income_inr`, `occupation`, `social_category`, `land_holding_hectares`, `business_turnover_inr`, `employee_count`, `is_bpl`, `is_student`, `has_disability`.
- **Document-specific fields:** the compiler may add one with a generated question.
- **Validation:** answers are checked against type and range, so an age of 300 gets a re-ask.
- **Rule checks:** Pydantic validates the AST, unknown fields are rejected, and each rule must link to a verified claim. Any compile failure becomes `Unevaluable(claim.text)`.

### 8.4 Next question

```python
def next_field(rules, profile):
    undecided = [r for r in rules if ev(r.ast, profile) is UNKNOWN]
    counts = Counter(f for r in undecided for f in missing_fields(r, profile))
    return counts.most_common(1)[0][0] if counts else None
```

The UI asks one question at a time, up to 8. The citizen can skip a question or answer "don't know", which is stored as `DECLINED` so it isn't asked again and stays `UNKNOWN` during evaluation.

### 8.5 Voice answers

A transcript goes through an LLM that returns `{field, value, confidence}` under the field's schema, and range checks then apply. **The UI always shows the parsed value for confirmation before it is saved**, because a misheard income can change the outcome. Questions are translated once through Sarvam and cached.

## 9. Voice layer

### 9.1 Script

The prompt receives verified claims with IDs and the verdict, and returns:

```python
class ScriptSentence(BaseModel):
    text: str = Field(max_length=220)
    claim_ids: list[str] = Field(min_length=1)
    kind: Literal["fact","verdict","action","not_stated"]
```

Code checks that claim IDs exist and that all numbers are in the cited claims. Sentences that fail are dropped, or the script is regenerated once. Fixed strings such as the not-legal-advice notice aren't sent through this check.

**Style:** under 18 words a sentence where possible, no legal jargon, and order of verdict, benefit, what to do, documents, deadline, who to contact. The citizen's own values never appear.

### 9.2 Translation and guard

```python
async def translate_one(s, lang):
    text = await sarvam.translate(s.text, target=lang, numerals_format="international")
    # on 402, 429 after retries, or 5xx: LLM translation, translator="llm"

def numeric_guard(src, tgt):      return numbers(src) == numbers(tgt)
async def meaning_guard(src, tgt): return await llm_backtranslate_judge(src, tgt)
```

The numeric guard runs first. The meaning guard is called only if that passes, and returns `SAME`, `MINOR_DIFF` or `CHANGED`; only `CHANGED` fails. Test `mayura:v1` with `modern-colloquial` at hour 3, since it allows a less formal register.

### 9.3 TTS and audio

- Cache key: `sha256(model|voice|language|translated_text)`, stored as `audio/{key}.mp3`.
- Sentences are generated in order with concurrency 3, so the first plays quickly.
- Before TTS, `₹` and number formats are tested at hour 3. If they read badly, a formatter writes amounts out in words for TTS only, and the guard still uses the digit version.

### 9.4 STT

Accepts WebM and MP4, max 30 seconds and 2 MB server-side. Calls `saaras:v4` with `language_code=unknown`. Empty transcripts or low `language_probability` return a re-ask. The audio is never stored or logged.

## 10. Provider gateway

```python
class Gateway:
    async def structured(self, task, prompt, schema, budget) -> BaseModel: ...
    async def embed(self, texts) -> list[list[float]]: ...
    async def vision_ocr(self, image, prompt) -> OcrResult: ...

# Sarvam calls sit behind the same retry and rate-limit layer:
# sarvam.translate, sarvam.tts, sarvam.stt
```

| Condition | Handling |
|---|---|
| 429, 503, 5xx, timeout | Backoff of 1, 2, 4 seconds with jitter, then failover |
| Schema failure | One repair prompt with the validation error, then failover |
| Safety block | Failover once, then `not_stated` |
| Sarvam 402 | No retry, set a flag, degrade immediately |
| Primary failed 5 times in 60 s | Circuit opens: skip it for 60 s |
| Rate limit | Token bucket per Sarvam API, 1 per second |

Each call adds to `Budget` and `runs.llm_calls`. LLM timeout is 45 seconds.

## 11. Grounded Q&A

1. Embed the question, or its English translation if needed, and retrieve the top 12 clauses.
2. The LLM returns `{answer, clause_ordinals, quote}` or `{answer: null}`.
3. The answer goes through `verify_claim`.
4. On failure or null, the response is the abstention: "this document does not say", with the issuing authority if known.
5. The answer is then translated, guarded and spoken like any other sentence.

Limits: 500 characters per question and 20 questions per run.

## 12. API

### 12.1 Endpoints

| Method and path | Request | Response |
|---|---|---|
| `POST /v1/documents` | JSON `{url, language}` or multipart `{file, language}` | `202 {run_id}` |
| `GET /v1/library` | | Prepared documents with provenance |
| `POST /v1/library/{document_id}/runs` | `{language}` | `202 {run_id}` |
| `GET /v1/documents/{id}/file` | | PDF stream |
| `GET /v1/documents/{id}/clauses` | | `{clauses: [{id, ordinal, page, bbox, text, lang, kind, extraction}], failed_pages}`. `page` is 1-based. `bbox` is `[x0, y0, x1, y1]` in PDF points from the top left, or `null` for OCR |
| `GET /v1/runs/{id}` | | Full run view, also the polling fallback. Adds `claims: [{id, field, text, quote, clauses: [{id, ordinal, page, bbox, extraction}]}]`, verified claims only, and `not_stated: [field]` |
| `GET /v1/runs/{id}/events` | `Last-Event-ID` | SSE stream |
| `POST /v1/runs/{id}/answers` | `{answers: {field: value}}`, or `{skip: [field]}` | `200 {status}` |
| `POST /v1/runs/{id}/stt` | Multipart audio, `field` | `{transcript, parsed, confidence}` |
| `POST /v1/runs/{id}/qa` | `{question, language}` | `{answer, citations, audio_url, abstained}` |
| `POST /v1/runs/{id}/page-range` | `{from, to}` | `202` |
| `GET /v1/health` | | Database, provider and credit flags |

### 12.2 Error format

```json
{"error": {"code": "SOURCE_UNREACHABLE", "message": "The site didn't respond.",
           "action": "upload", "details": {"attempts": ["http", "browser"]}}}
```

| Code | HTTP or event | Suggested action |
|---|---|---|
| `INVALID_URL`, `URL_BLOCKED` | 400 | Enter another link |
| `FILE_TOO_LARGE` | 413 | Upload a smaller file |
| `RATE_LIMITED` | 429 | Wait |
| `SOURCE_UNREACHABLE`, `NOT_A_PDF` | Event | Upload or pick from the library |
| `PDF_INVALID`, `PDF_ENCRYPTED` | Event | Try another file |
| `DOC_TOO_LONG` | Event | Choose a page range |
| `NOT_A_POLICY` | Event | Try another document |
| `PROVIDERS_UNAVAILABLE` | Event | Retry the run |
| `MULTIPLE_PDFS` | Event | Choose from `details.options` |
| `NO_READABLE_TEXT` | Event | Try another file |
| `RUN_TIMEOUT` | Event | Retry the run; finished pages are kept. If claims were already verified, the run ends as `partial` and keeps them, and unchecked claims are never shown |
| `RUN_NOT_FOUND`, `DOCUMENT_NOT_FOUND` | 404 | Start again |

### 12.3 SSE

```
id: 42
event: claim_rejected
data: {"claim_id":"...","reason":"QUOTE_NOT_IN_SOURCE","attempt":1}
```

On connection, the server replays events with `seq > Last-Event-ID`, then streams live. A comment heartbeat goes out every 15 seconds, and terminal events close the stream. Caddy must not buffer this route (`flush_interval -1`).

### 12.4 Abuse limits

Five new runs per IP per 10 minutes, and 20 STT calls per run. `client_hash` is a salted IP hash, so raw IPs aren't stored.

### 12.5 Run event contract

`language` in every request is one of `hi`, `bn`, `mr` or `en`.

The frontend builds the trace only from these events, so a refresh, an SSE replay and polling all give the same view. `seq` is the SSE `id`. `EventSource` drops named events it hasn't subscribed to, so any new type must also be added to `RUN_EVENT_TYPES` in `frontend/lib/types.ts`.

| Event | Payload | Meaning |
|---|---|---|
| `run_status` | `{status, error?}` | Every status change. `completed`, `partial` and `failed` are terminal: the server closes the stream after sending one. `error` uses the 12.2 format |
| `node_started` | `{node}` | A node began. Emit it again on retry or resume |
| `node_finished` | `{node, duration_ms, implemented}` | A node ended normally. `implemented: false` marks a pass-through, shown as "Not built yet" |
| `fetch_attempt` | `{method}` | `http`, `browser` or `upload` |
| `page_ocr` | `{page, reason}`, or `{page, failed: true, reason}` | A page started or failed OCR |
| `segment_done` | `{clauses, failed_pages}` | Clauses can be read now. Clause count, and pages that couldn't be read |
| `embeddings_done` | `{embedded}` | Embedding finished, or `false` if it failed or took over a minute. The next run retries it |
| `triage_result` | `{is_policy}` | |
| `claim_extracted` | `{claim_id, field}` | |
| `claim_verified` | `{claim_id}` | |
| `claim_rejected` | `{claim_id, reason, attempt}` | |
| `retry` | `{reason, attempt}` | |
| `rules_compiled` | `{count}` | |
| `needs_input` | `{field}` | Field name only |
| `verdict` | `{outcome}` | Never input values |
| `script_ready` | `{sentences}` | Sentence count |
| `sentence_translated` | `{sentence_id, translator}` | |
| `failover` | `{from, to, reason}` | |
| `guard_failed` | `{sentence_id, reason, attempt}` | |
| `sentence_ready` | `{sentence_id}` | |

`GET /v1/runs/{id}` returns `{id, status, document, error, events: [{seq, type, payload}]}`, with `document` as `null` until acquired and every event so far in `events`. The polling fallback feeds this into the same reducer. The API must allow `ALLOWED_ORIGINS` through CORS on all routes, and an unknown run returns 404 with `RUN_NOT_FOUND`.

## 13. Frontend

### 13.1 Run view state

```ts
type RunView = {
  status: "queued"|"running"|"waiting_input"|"completed"|"partial"|"failed";
  document?: DocumentView;       // includes provenance
  steps: Step[];                 // from events
  claims: Claim[];
  question?: Question;
  verdict?: Verdict;
  sentences: Sentence[];
  error?: ApiError;
};
```

`useRunStream` applies events through a reducer, ignoring `seq` values already seen. After 3 failed SSE reconnects it polls `GET /v1/runs/{id}` every 3 seconds. Refreshing the page rebuilds the view from the server. The profile isn't sent back, so typed answers don't reappear.

### 13.2 Components

| Component | Key behaviour |
|---|---|
| `SourceInput` | URL, upload and library tabs; language picker; privacy notice |
| `AgentTrace` | Node timeline, with rejections and failovers kept visible |
| `RightsCard` | Grouped by field, source link per claim, "not stated" shown explicitly |
| `EligibilityPanel` | One question at a time, mic or typed, confirmation, skip, per-criterion result |
| `AudioPlayer` | Starts on tap, plays clips in sequence, skips flagged sentences visibly, English toggle, speed control |
| `PdfViewer` | PDF.js; draws `bbox` highlights; for OCR clauses shows the page and quote panel; on mobile opens as a sheet |
| `ProvenanceBadge` | URL, method, fetch time, hash, issue date, old-document warning |

### 13.3 Browser handling

Choose the recorder format with `MediaRecorder.isTypeSupported`, using WebM or MP4. The mic requires HTTPS and a user gesture. If either fails, the panel switches to typing without an error dead-end.

## 14. Observability

Structured JSON logs with `run_id`, node, provider, latency and result. **Never log** profile values, transcripts, audio or raw IPs. `/v1/health` reports database status, whether keys are configured, circuit state, and the Sarvam credit flag, without showing secrets.

## 15. Testing

| Level | Scope | Method |
|---|---|---|
| Unit | `numbers`, `normalize`, `garble`, `ssrf`, interpreter, `next_field`, verifier checks 1-3 | pytest, table-driven |
| Integration | Graph with fake providers for failures | Inject 429, 402, bad JSON and timeouts |
| Live | One digital and one scanned document end to end | Real APIs, marked to run on demand |
| Evaluation | Labelled real documents | See [stress test](STRESS_TEST.md#4-evaluation) |
| Manual | Failure matrix on the public URL | See [stress test](STRESS_TEST.md#3-failure-matrix) |

Fake providers and labelled files exist only under `backend/tests/`. A CI or pre-commit check confirms that application code imports nothing from there, so nothing there can be mistaken for app data.
