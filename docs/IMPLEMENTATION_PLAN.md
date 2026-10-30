# Haq: Phased Implementation Plan

**Related documents:** [High-level design](HLD.md) · [Low-level design](LLD.md) · [Stress test](STRESS_TEST.md)

## 1. How to use this plan

- Hours count from the start of the 35-hour window. Record the actual start time here: `H0 = ________`
- Each phase ends at a **gate**. If a gate is missed, use the [cut list](#5-cut-list) rather than taking time from the next phase.
- **A** owns graph, data and AI. **B** owns voice, frontend and deployment.
- Commit small and often, and push at least hourly, as evidence the work happened in the window. Write no application code before H0.
- Check decisions against the [hackathon rules](#8-hackathon-rules).

## 2. Timeline

| Phase | Hours | Outcome |
|---|---|---|
| 0. Spikes | 0-3 | Every external dependency has been tried for real |
| 1. Skeleton | 3-6 | A thin system is live on a public URL |
| 2. Documents | 6-10 | Real PDFs become reliable clauses |
| 3. Claims | 10-15 | Verified rights card with clickable citations |
| Sleep | 15-19 | Alternate |
| 4. Eligibility and voice | 19-24 | **Full Hindi flow works on the public URL** |
| 5. Finish | 24-28 | Usable by a stranger, with the second language |
| 6. Harden | 28-30 | Feature freeze, failures fixed, real numbers measured |
| Sleep | 30-32 | |
| 7. Ship | 32-35 | Submitted by hour 34 |

## 3. Phases

### Phase 0: Spikes (hours 0-3)

**Goal:** find anything that would break the plan while it's still cheap to change.

| # | Task | Owner | Done when |
|---|---|---|---|
| 0.1 | Ask organisers whether AI coding tools count as authorised assistance, whether any APIs are restricted, and whether design docs written before H0 are acceptable | Both | Answers recorded |
| 0.2 | Add `.gitignore`, `.env.example`, folder structure | A | Pushed |
| 0.3 | Create Gemini, OpenAI and Sarvam keys. Add about ₹500 Sarvam credit, turn on Gemini billing, check limits in AI Studio | B | One successful call to each |
| 0.4 | Choose and record exact model names from live lists | A | `.env.example` updated |
| 0.5 | Create the Mumbai VM and Supabase project (Mumbai), install Docker | B | SSH works, database reachable |
| 0.6 | From the VM, try official PDFs from at least 8 ministry or state sites, using plain fetch then Playwright | A | At least 3 fetched, results recorded |
| 0.7 | Gemini OCR on a real scanned Hindi page | A | Result read and judged by a Hindi reader |
| 0.8 | Sarvam test: sentence with money and dates, through translate and TTS, on both TTS models | B | Best model chosen by listening |
| 0.9 | Choose Bengali or Marathi | Both | Recorded |

**Gate, go/no-go:**

| Check | If it fails |
|---|---|
| At least 3 PDFs fetched from the VM | Fetch from a home connection and upload; label them "uploaded" |
| Hindi OCR readable | Try OpenAI vision |
| Speech understandable with amounts and dates | Other Bulbul model, then write amounts out in words before TTS |
| Organisers allow tools and APIs | Follow their ruling before writing more code |
| Credits and billing active | Fix before leaving this phase |

### Phase 1: Skeleton (hours 3-6)

**Goal:** a real run travels from browser to backend to database and back, on public URLs.

| # | Task | Owner | Done when |
|---|---|---|---|
| 1.1 | FastAPI app, settings, health endpoint | A | `/v1/health` responds locally |
| 1.2 | Database migrations for all tables | A | Tables exist in Supabase |
| 1.3 | LangGraph with pass-through nodes and Postgres checkpointer | A | A run reaches the end |
| 1.4 | Event store and SSE with `Last-Event-ID` | A | Refresh replays missed events |
| 1.5 | Upload endpoint with PDF validation and Supabase Storage | A | A real PDF is stored with its hash |
| 1.6 | Dockerfile, Compose, Caddy with HTTPS and no SSE buffering | B | Public `/v1/health` |
| 1.7 | Next.js app on Vercel, `SourceInput`, `AgentTrace`, `useRunStream` | B | Upload shows live node progress |

**Gate:** on the public URL, uploading a real PDF shows a live trace, and a page refresh mid-run recovers it.

### Phase 2: Documents (hours 6-10)

**Goal:** trustworthy clauses from digital, scanned, legacy-font and table-heavy PDFs.

| # | Task | Owner | Done when |
|---|---|---|---|
| 2.1 | URL fetch, SSRF guard and tests, TLS bundle | A | Blocked addresses fail in tests |
| 2.2 | Playwright fetcher | A | Reaches a JavaScript page |
| 2.3 | PyMuPDF extraction with positions | A | Clauses have correct pages and boxes |
| 2.4 | Garble detection, tested on legacy-font Hindi PDFs | A | Garbled pages go to OCR |
| 2.5 | OCR with concurrency and failed-page tracking | A | Scanned PDF gives clauses |
| 2.6 | Table rows, segmentation, normalisation, language tags | A | Table criteria appear as whole clauses |
| 2.7 | Embeddings and SHA-256 reuse | A | Second run skips re-processing |
| 2.8 | Fetch 5-8 official documents through the pipeline as the library | A | Library has real provenance |
| 2.9 | `PdfViewer` with `bbox` highlight and OCR page view | B | Clicking a clause highlights it |
| 2.10 | `ProvenanceBadge`, library tab, URL tab | B | All three inputs work |

**Gate:** one digital and one scanned Hindi PDF both produce clauses that a reader confirms are correct and correctly located.

### Phase 3: Claims (hours 10-15)

**Goal:** the core USP: only verified, clickable facts appear.

| # | Task | Owner | Done when |
|---|---|---|---|
| 3.1 | Provider gateway: retries, failover, circuit, budget | A | Fake failures trigger failover in tests |
| 3.2 | Triage prompt and node | A | A non-policy PDF stops cleanly |
| 3.3 | Extraction schema, prompt and field-based retrieval | A | Real documents give atomic claims |
| 3.4 | `numbers.py` with table-driven tests | A | All listed formats pass |
| 3.5 | Verifier checks 1-3, then entailment | A | Fabricated quotes are rejected in tests |
| 3.6 | Retry loop passing failure reasons, then `not_stated` | A | Trace shows real rejection and repair |
| 3.7 | `RightsCard` with source links, "not stated" and live updates | B | Claim click highlights its clause |
| 3.8 | Trace display for rejections, retries and failover | B | The self-correction is obvious |

**Gate:** on the public URL, a real document gives a rights card with all citations working. If it's late, keep working on it through the first part of the sleep block: **this is the feature the project cannot lose.**

### Sleep (hours 15-19)

Stagger sleep. Leave nothing long-running that needs supervision. Before sleeping, note the next task in the repo.

### Phase 4: Eligibility and voice (hours 19-24)

**Goal:** the complete citizen experience in Hindi.

| # | Task | Owner | Done when |
|---|---|---|---|
| 4.1 | AST, interpreter and three-valued tests | A | Truth table passes |
| 4.2 | Field registry, rule compiler, invalid-to-`Unevaluable` | A | Real criteria compile or degrade |
| 4.3 | `ProfileStore`, `evaluate`, `interrupt`, `next_field`, answers endpoint | A | Run pauses and resumes; **no profile value in checkpoint tables** |
| 4.4 | Script node with claim validation | A | No sentence without a verified source |
| 4.5 | Translation, fallback, numeric and meaning guards | B | A changed amount in a test is caught |
| 4.6 | TTS, rate limiter, audio cache | B | Clips appear sentence by sentence |
| 4.7 | STT endpoint and answer parsing with confirmation | B | Spoken answer confirmed in UI |
| 4.8 | `EligibilityPanel`, `AudioPlayer` with clause sync | B | Tap a sentence to see its clause |
| 4.9 | Run everything on the public URL, on a phone | Both | Works with a document not used before |

**Gate, the most important one:** complete Hindi flow on the public URL, from a real document to spoken explanation with source links. If this is missed at hour 24, stop other work and apply the cut list until it passes.

**First handover (hour 24):** each person walks through the other's code.

### Phase 5: Finish (hours 24-28)

**Goal:** turn a working system into a clear one.

| # | Task | Owner | Done when |
|---|---|---|---|
| 5.1 | Second language, reviewed by a speaker | B | Audio and captions checked |
| 5.2 | Grounded Q&A, by text and then voice | A | Out-of-scope question gets abstention |
| 5.3 | Cross-provider entailment option | A | Works with the flag on; decide default after evaluation |
| 5.4 | Page-range flow for long documents | A | A 300-page PDF is handled |
| 5.5 | Empty, loading and error states, mobile layout | B | Every error code has a UI |
| 5.6 | Issue-date warning, disclaimer, privacy notice | B | Visible in the flow |
| 5.7 | Abuse limits and queue position | A | Sixth rapid run is limited |
| 5.8 | Test with someone who hasn't seen it | Both | They complete it unaided |

**Gate:** a stranger completes the flow without help. **Stretch, only if every gate has passed:** "what changed for me" comparison between two policy versions.

### Phase 6: Harden (hours 28-30)

**Feature freeze. Bug fixes only.**

| # | Task | Owner | Done when |
|---|---|---|---|
| 6.1 | Run the [failure matrix](STRESS_TEST.md#3-failure-matrix) on the public URL | Both | All cases end in a clear message |
| 6.2 | Label 3-4 real documents and run the [evaluation](STRESS_TEST.md#4-evaluation) | A | Real numbers recorded |
| 6.3 | Tune thresholds and prompts from results | A | Re-run shows the effect |
| 6.4 | Read and listen to all demo output | B | Errors fixed or documents replaced |
| 6.5 | Test the restart recovery and laptop standby | B | Both rehearsed |
| 6.6 | Check logs and checkpoint tables for personal data | A | None found |

**Gate:** failure matrix passes, and evaluation numbers exist.

### Phase 7: Ship (hours 32-35)

| # | Task | Owner | Done when |
|---|---|---|---|
| 7.1 | README: overview, setup, diagrams, results, env vars | A | Setup works from a fresh clone |
| 7.2 | 6-slide deck using measured numbers | B | Reviewed by both |
| 7.3 | Record 2-3 minute video of the live system | Both | Covers the demo script below; shows the public URL |
| 7.4 | Second handover and mock judge questions | Both | Each explains the codebase, data flow and AI logic independently |
| 7.5 | Fill in the submission template | Both | All links open in incognito |
| 7.6 | **Submit on the Learning Platform by hour 34** | Both | Confirmation saved |
| 7.7 | Final hour: buffer only, no risky changes | | Tag the submitted commit |

## 4. Demo script (2-3 minutes)

| Time | Show | Point proven |
|---|---|---|
| 0:00-0:20 | The problem, and a real policy PDF | Real-world need |
| 0:20-0:50 | Live fetch and agent trace, with a rejected claim being repaired | Agentic self-correction |
| 0:50-1:15 | Rights card, click to highlighted clause | Attribution |
| 1:15-1:45 | Voice follow-up in Hindi and the verdict | Deterministic eligibility, voice |
| 1:45-2:15 | Hindi audio with sentence and clause sync | Core outcome |
| 2:15-2:35 | Out-of-scope question gets abstention | Guardrails |
| 2:35-2:50 | Evaluation numbers and roadmap | Credibility |

Self-corrections depend on the real run. Test the demo documents to find one that often triggers a rejection, and never stage or fake one. **Live judging:** run a prepared document first, then invite a judge to choose a real government PDF. Always demo the running system, and never present the recording as a live app.

## 5. Cut list

Apply in this order when a gate is missed.

| Order | Cut | Replacement |
|---|---|---|
| 1 | Cross-provider verification | Same provider |
| 2 | Voice Q&A | Typed Q&A, then none |
| 3 | Second language | Hindi only |
| 4 | Table-specific parsing | Normal text segmentation |
| 5 | Playwright tier | Upload and library |
| 6 | Voice answers to eligibility | Form answers, with spoken explanation kept |

**Never cut:** citations, deterministic verification, eligibility interpreter, Hindi spoken output, failure handling, public deployment.

## 6. Submission checklist

- [ ] Problem statement and audience written
- [ ] Solution overview and architecture written
- [ ] Live URL works in incognito and on a phone
- [ ] 2-3 minute video of the real system, publicly viewable
- [ ] Public repository with README, setup, diagram and all source
- [ ] No secrets in git history (scan before submitting)
- [ ] 5-7 slide deck, publicly viewable
- [ ] GitHub link, deck and video submitted on the Learning Platform before the deadline
- [ ] Social post link added (optional)
- [ ] No mock data in application code: no seed files, hardcoded datasets or placeholder numbers
- [ ] Both members can independently explain the codebase, data flow and AI logic
- [ ] Both members confirmed eligible: IIT, NIT, IIIT or BITS students graduating in 2027 or later

## 7. Risk watch

| Time | Check |
|---|---|
| Hour 3 | Can the VM fetch official documents? |
| Hour 15 | Is the verified rights card live? If not, start cutting |
| Hour 24 | Is the Hindi flow live? |
| Hour 28 | Freeze, regardless of what's unfinished |
| Hour 34 | Submitted |
| 15 minutes before judging | Check `/v1/health`, Sarvam credit, one quick full run |

## 8. Hackathon rules

Breaking a rule marked **DQ** means immediate disqualification.

| Rule | What it means for this project |
|---|---|
| Teams of 2-3, no team changes | We are two people, so the plan has no extra capacity to call on |
| Built during the Stage 1 window (**DQ** if pre-existing) | Only design docs exist before H0; all application code comes after it |
| Submit on the Learning Platform before the deadline | GitHub link, document or deck, 2-3 minute demo video, optional social post |
| No dummy data (**DQ**) | Documents come from live government sites or user upload. Library entries are database rows created by the real pipeline, never seed files. Labelled evaluation data and fake providers stay under `backend/tests/` |
| Open source and boilerplate allowed | Core logic, AI integration and agent workflows are written in the window |
| Every member can explain the project | Handovers at hours 24 and 32, plus mock questions |
| No pre-recorded demo or mockup passed off as live (**DQ**) | Judging uses the running system. No canned responses or stored demo outputs in the app |
| No plagiarism or unauthorised assistance (**DQ**) | Get the organisers' ruling on AI coding tools in task 0.1 |
