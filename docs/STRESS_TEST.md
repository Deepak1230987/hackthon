# Haq: Stress Test

**Related documents:** [High-level design](HLD.md) · [Low-level design](LLD.md) · [Implementation plan](IMPLEMENTATION_PLAN.md)

## 1. Live checks

Run on 30 October 2026 using a server-side web fetcher, not a browser and probably not from an Indian IP. Treat site results as warning signs to re-test from the Mumbai VM in phase 0.

| Check | Result | Effect on the design |
|---|---|---|
| myScheme scheme page | Error page with no scheme content | Not a main source; Playwright may still reach it |
| eGazette | TLS certificate verification failed | Complete the CA bundle; never disable verification |
| PIB RSS page | HTTP 403 | Fetch tiers needed; not relied on |
| india.gov.in guidelines listing | HTTP 403 | Same |
| Ministry of Education PM POSHAN page | HTTP 404 | Links go stale; library chosen and tested in phase 2 |
| Sarvam TTS | 2,500 characters per request; Hindi, Bengali, Marathi supported | Fits per-sentence design |
| Sarvam STT | Sync API intended for under 30 seconds | Recording capped at 25 seconds |
| Sarvam translation | 1,000 or 2,000 character limit; `numerals_format` available | Enables the numeric guard |
| Sarvam limits | 60 requests/min per API; 402 when credits run out | Shared limiter, explicit 402 handling |
| Sarvam pricing | ₹100 free credit; TTS ₹1-3 and translation ₹2 per 1,000 characters; STT ₹0.49/min | See below |
| Gemini PDFs | 50 MB and 1,000 pages | No blocker |
| Gemini quotas | Not published per model; shown in AI Studio | Enable billing and check in phase 0 |

**Main finding:** all five government pages failed from this fetcher. This is the largest external risk, and it's why the Mumbai VM, fetch tiers, prepared library and upload path exist.

**Fetch test, 31 October 2026:** from a home connection in India, not yet from the VM, 8 of 14 official PDFs downloaded with TLS verification on. Failures: one TLS verification error (pmkisan.gov.in), one 403 (mha.gov.in), one 404, and three timeouts (pmgsy.nic.in, nskfdc.nic.in, socialjustice.gov.in).

**Hindi text layer finding:** the PMAY-G Hindi booklet has a corrupted text layer on a Unicode font, such as `ग्ामीीण` for `ग्रामीण`, with doubled vowel signs on 36 of 40 pages. Replacement-character and legacy-font checks don't catch this, so task 2.4 must. Gemini OCR read a sample page correctly.

**Gemini quota, 31 October 2026:** the API key is on the Free Tier. `gemini-3.6-flash` allows 20 requests a day and `gemini-embedding-2` and `gemini-3.5-flash-lite` hit per-minute limits, so a 40-page Hindi PDF needed three runs to finish its OCR. Task 0.3 requires billing to be on before judging.

**OCR on a real scan, 31 October 2026:** on a 6-page scanned UP Police circular, all three Gemini models refused page 3 with `RECITATION`, because it quotes the BNSS word for word. Government documents quote laws often, so expect this in judging; the OpenAI fallback needs a key to cover it. `gemini-3.5-flash-lite` also swapped real words, such as `अभियुक्तों` for `अभियोगों`, while numbers stayed correct, so the default `OCR_MODEL` moved to `gemini-3.5-flash`, which read all 16 test words correctly. It allows only 20 requests a day on the Free Tier, so it needs billing. Hindi OCR output still needs checking by a reader.

**Connection limit:** Supabase's session pooler allows 15 clients, and they filled up after hard-kill tests, stopping the backend from starting. Use the transaction pooler on port 6543.

**Sarvam cost estimate:** a 1,500-character explainer costs about ₹3 to translate and ₹1.50 to speak with v4-flash, or ₹4.50 per language, excluding GST. The free ₹100 covers roughly 20 runs before testing and retries, hence the ₹500 top-up.

## 2. Design review

| # | Attack on the design | Severity | Resolution |
|---|---|---|---|
| 1 | Government sites block us during live judging | Critical | Fetch tiers, prepared library with real provenance, upload path |
| 2 | Hindi PDFs extract as garbage because of legacy fonts, and quotes "verify" against it | Critical | Garble detection routes those pages to OCR |
| 3 | Verifier passes a real quote that doesn't support the claim | High | Numeric check plus entailment; only `ENTAILED` passes |
| 4 | LLM wrongly rejects correct claims and the card ends up empty | High | Measure in evaluation; tune prompts on labelled documents |
| 5 | OCR errors break exact quote matching | High | Fuzzy threshold for OCR clauses only, labelled in the UI |
| 6 | Criteria don't fit the rule grammar ("as decided by the district officer") | High | `Unevaluable` leads to `CANNOT_DETERMINE`, never a guess |
| 7 | Missing profile data becomes a false rejection | High | Three-valued logic |
| 8 | Document is outdated or superseded | High | Issue date, warning, single-document scope stated openly |
| 9 | Translation changes ₹2.5 lakh or a deadline | High | Numeric guard, then flag and withhold audio |
| 10 | Translation is correct but too formal for ordinary citizens | Medium | Simplify in English first; test `modern-colloquial` in `mayura:v1` |
| 11 | Long PDF exhausts budget or time | High | Page limit, range selection, budget, labelled partial result |
| 12 | A judge pastes a non-government or hostile URL | High | SSRF guard, PDF validation, triage stop |
| 13 | Prompt injection inside a PDF | Medium | Data wrapping, no tools, fixed schema, verification |
| 14 | Several judges at once hit rate limits | Medium | 3 concurrent runs, visible queue, shared limiter |
| 15 | Network drops during the demo | Medium | SSE resume, polling, server-side runs, phone hotspot |
| 16 | The VM dies | Medium | Quick Compose rebuild, rehearsed laptop standby |
| 17 | Scanned pages have no clause coordinates | Medium | Page-level highlight with quote |
| 18 | Citizen's personal data leaks | High | Memory-only profile, no logging. Voice still reaches Sarvam, so disclose it and ask for no names or IDs |
| 19 | **Checkpoints silently save profile values to Postgres** | High | **Found while writing the LLD.** Profile lives outside graph state, and phase 4 and 6 tasks check the tables |
| 20 | **Script or audio repeats a citizen's values, storing them indirectly** | High | **Found while writing the LLD.** Scripts state criteria, never the citizen's values |
| 21 | **`interrupt()` re-runs a node on resume and duplicates rows or LLM calls** | Medium | **Found while writing the LLD.** Idempotent nodes with upserts |
| 22 | **A misheard voice answer changes the eligibility outcome** | High | **Found while writing the LLD.** Parsed value is always confirmed |
| 23 | Judge says "this is dummy data" | Critical | No seeded app data, visible provenance, live pick by the judge, labelled evaluation data in `tests/` |
| 24 | Judge says "this is a pre-existing project" | Critical | Only design docs in the repo at H0, no application code before it, frequent commits |
| 25 | One member can't explain part of the code | Critical | Handovers at hours 24 and 32, and mock questions |
| 26 | Plan is too big for 2 people | **Critical** | Gates, cut list, early deployment, Hindi flow by hour 24 |
| 27 | Looks like a generic "chat with PDF" | High | Demo leads with rejection and retry, clause links and abstention |
| 28 | Wrong advice harms a real citizen | High | "Appears to meet" wording, official source link, not-legal-advice notice |
| 29 | Judge says "this demo is pre-recorded" | Critical | Live public URL, judge picks the document, no canned outputs in the app, video shown only as the submission video |
| 30 | AI coding tools are ruled "unauthorised assistance" | Critical | Ask organisers in task 0.1 and follow their ruling before writing more code |

**Still open:** items 4 and 10 can only be measured on the real system (by hour 30), and item 1 can only be settled from the VM (by hour 3).

## 3. Failure matrix

Run on the public URL in phase 6. Each case must end with a clear message and no crash.

| Area | Cases |
|---|---|
| Input | Dead URL, HTML page, non-PDF renamed `.pdf`, encrypted PDF, 60 MB file, 300-page PDF, blank PDF, private IP URL, repeated submit |
| Content | Non-policy PDF, scanned Hindi, legacy-font Hindi, bilingual, table-only eligibility, injected instructions |
| Reasoning | Question not answered by the document, incomplete profile, contradictory answers, impossible values such as age 300 |
| Voice | Mic denied, silence, noise, 25-second cutoff, wrong language spoken, iPhone Safari recording |
| Providers | Invalid Gemini key, invalid OpenAI key, invalid Sarvam key, simulated 429, simulated 402 |
| Infrastructure | Backend restart during a run, browser refresh during a run, 3G throttling, 5 runs at once |

## 4. Evaluation

Hand-label 3-4 real documents, kept under `backend/tests/eval/`. Report the measured numbers in the deck, whatever they turn out to be.

| Metric | Target |
|---|---|
| Claims with valid citations | 100% |
| Numbers preserved through translation | 100% |
| Invented facts in demo documents | Zero |
| Precision and recall of extracted facts | Measure and report |
| Eligibility accuracy, about 20 written test profiles | Measure and report |
| Correct abstention, about 10 questions the documents don't answer | Measure and report |
| Time to first rights card | Under 60 seconds for a 30-page digital PDF |
| Time to first audio | Under 2 minutes after answers are complete |

## 5. Verdict

**Go, on Problem 1.** No finding breaks the design, but several changed it: hosting moved to Mumbai, myScheme is no longer a main source, fetch tiers and the prepared library were added, legacy-font detection became essential, and profiles were moved out of graph state.

The biggest remaining risk is build time. The hour-24 gate is the real test: a complete Hindi flow on the public URL matters more than any later feature.
