# Haq: Handover and Mock Judge Questions

**Related documents:** [High-level design](HLD.md) · [Low-level design](LLD.md) · [Evaluation](EVALUATION.md)

For task 7.4. Each member should be able to answer every question below alone, with the file open. Take turns: one reads the question, the other answers without looking, then checks the code.

## 1. The data flow, in order

Each step is a node in [build.py](../backend/app/graph/build.py), run in this order. An event is written after each one, and that's what the live trace shows.

| Node | What it does | Who decides | File |
|---|---|---|---|
| `acquire` | Fetches or receives the PDF, checks the URL and the file, records where it came from | Code | [acquire.py](../backend/app/graph/nodes/acquire.py), [ssrf.py](../backend/app/acquisition/ssrf.py) |
| `parse` | Reads text with positions, and sends garbled or scanned pages to OCR | Code, LLM for OCR | [parse.py](../backend/app/graph/nodes/parse.py), [garble.py](../backend/app/documents/garble.py) |
| `segment` | Splits pages into clauses and embeds them | Code | [segment.py](../backend/app/graph/nodes/segment.py) |
| `triage` | Stops if this isn't a policy document | LLM | [triage.py](../backend/app/graph/nodes/triage.py) |
| `extract` | Writes claims, each with a quote and the clauses it cites | LLM | [extract.py](../backend/app/graph/nodes/extract.py) |
| `verify` | Checks quote and numbers in code, then entailment. Failures go back to `extract`, at most twice | Code first, then LLM | [verify.py](../backend/app/graph/nodes/verify.py), [verifier.py](../backend/app/claims/verifier.py) |
| `compile_rules` | Turns eligibility claims into a rule tree. Anything that won't fit becomes `Unevaluable` | LLM writes, code validates | [compile_rules.py](../backend/app/graph/nodes/compile_rules.py) |
| `evaluate` | Works out the verdict with three-valued logic, and pauses to ask the citizen | Code only | [evaluate.py](../backend/app/graph/nodes/evaluate.py), [interpreter.py](../backend/app/eligibility/interpreter.py) |
| `script` | Writes plain sentences, each tied to verified claims | LLM, code validates | [script.py](../backend/app/graph/nodes/script.py) |
| `translate` | Sarvam translates each sentence, with the LLM as fallback | LLM | [translate.py](../backend/app/graph/nodes/translate.py) |
| `guard` | Compares numbers in code, then checks meaning. Failures go back to `translate` | Code first, then LLM | [guard.py](../backend/app/graph/nodes/guard.py), [voice/guard.py](../backend/app/voice/guard.py) |
| `tts` | Speaks only sentences that passed | Code calls Sarvam | [tts.py](../backend/app/graph/nodes/tts.py) |

Q&A runs after this, outside the graph, in [qa.py](../backend/app/api/qa.py). It uses the same `check_claim` as the rights card.

## 2. Mock questions

### Authenticity

**Is this pre-existing or dummy data?**
Only the design documents predate the code, and the git history shows it. Library entries are rows made by sending real documents through the same pipeline, with their source URLs shown. Fakes exist only under `backend/tests/`, and [test_no_test_imports.py](../backend/tests/unit/test_no_test_imports.py) fails if application code imports them. Offer to run a PDF the judge picks.

**Was the demo video staged?**
The video records the running system. Rejections and retries come from real runs, so they differ from run to run.

### The core idea

**What stops the LLM from making up a fact?**
Three checks must all pass before a claim is shown. The quote must be in the cited clause: exact for native text, or at least 92% similar for OCR, where numbers must still match exactly. Every number in the claim must be in the quote. Then an LLM must judge the claim `ENTAILED` by its sources. `_verified_claims` in [runs.py](../backend/app/api/runs.py) returns only verified claims, so nothing else can reach the browser.

**Why not trust the entailment check alone?**
It's an LLM and can be wrong. Code checks run first and no LLM can overrule them. A claim the model skips counts as not entailed.

**A correct quote can still be misread. Are you claiming there are no errors?**
No. Entailment catches most of it, but it isn't proof. That's why every claim links to its clause, the wording is "appears to meet", and the app shows a not-legal-advice notice and the official source.

**Why does eligibility not use an LLM?**
So the same answers always give the same verdict, and we can test it. The LLM only translates criteria into a rule tree. [fields.py](../backend/app/eligibility/fields.py) rejects a rule with an unknown field or a threshold that isn't in the verified claim, and such a rule becomes `Unevaluable`.

**What does three-valued logic get you?**
A missing answer is unknown, not false. So someone who hasn't answered isn't wrongly rejected, and a criterion we can't evaluate gives "can't determine", not a guess.

**What happens if translation changes ₹2.5 lakh?**
`numbers_match` parses numbers in both texts, in any script or format, and compares them. On failure it retries. A sentence that keeps failing is flagged, and its audio is never made.

**How do you handle a question the document doesn't answer?**
The answer goes through the same checks, and any failure gives a fixed "This document does not say". The API returns `abstained: true`, and no citation. A provider failure gives a different error, because nobody has found that the document is silent.

### Hard cases

**What about Hindi PDFs whose text layer is garbage?**
[garble.py](../backend/app/documents/garble.py) detects them, including a case we found on the PMAY-G booklet: a Unicode font with doubled vowel signs, on 36 of 40 pages. Those pages go to OCR. See the [stress test](STRESS_TEST.md).

**What if a government site blocks you during judging?**
Plain HTTP, then a Playwright browser, then a clear message offering upload or the library. All 5 government pages failed in our first test, which is why those exist.

**A judge pastes `http://169.254.169.254/`. What happens?**
[ssrf.py](../backend/app/acquisition/ssrf.py) resolves the address and rejects private ranges. It's covered by [test_ssrf.py](../backend/tests/unit/test_ssrf.py).

**What about prompt injection inside a PDF?**
Document text is wrapped as data by `as_data`, the extraction nodes have no tools, and output must fit a fixed schema. Even if an injection succeeds, a made-up claim still fails verification. This reduces the risk, but doesn't remove it.

**OpenAI is down mid-run. What then?**
The [gateway](../backend/app/providers/gateway.py) retries, opens a circuit, and fails over to Gemini, shown in the trace. Claims that can't be checked are never shown, and the run ends as partial.

**The server restarts mid-run. What's lost?**
LangGraph checkpoints in Postgres let the run resume, through `runner.recover()`. Profile answers are lost on purpose, because they're only held in memory, so the citizen is asked again.

### Privacy

**Where is a citizen's income stored?**
In backend memory only, in [store.py](../backend/app/profiles/store.py), for up to an hour. Not in graph state, so not in checkpoints. Scripts state the criteria, never the citizen's values.

**Does voice leave your system?**
Yes. Recordings go to Sarvam and aren't stored by Haq. The UI says so and asks people not to say names or ID numbers.

### Limits and honesty

**What are your accuracy numbers?**
Read them from [EVALUATION.md](EVALUATION.md), including what wasn't measured. Don't round up, and don't quote precision or recall unless the hand-labelling has been done.

**Have you found bugs you haven't fixed?**
Yes. A rule for one group, such as "male wards up to 25", can reject people outside that group, and this gave false rejections on 2 of 3 verdicts we checked. Q&A can also say "does not say" when the document does answer. Both are in [EVALUATION.md](EVALUATION.md).

**What doesn't it do?**
One document at a time. It doesn't know whether a document has been replaced by a newer one, it doesn't file applications, and it isn't legal advice. Hindi and Marathi only in the app. Hindi and Marathi quality still needs a native reader's check.

**How would it scale?**
Today it's one VM with three concurrent runs, and the rest queue. Next is a work queue with separate workers, then WhatsApp and IVR, then multi-document retrieval with version tracking. See [HLD section 11](HLD.md#11-scalability-path).

**Why LangGraph?**
Loops, pauses and checkpoints are built in, and a run must pause for a citizen's answer and survive a restart.

**Why a VM and not serverless?**
Runs last minutes, use a browser, and hold profiles in memory.

**What did AI tools do on this project?**
Answer exactly as your organisers' ruling requires (task 0.1). Don't improvise this one.

## 3. Things to fix in your own answers

The design documents were written before the build, and some details moved. Trust the code and the [README](../README.md) over them on these:

- The VM is on Azure in South India, not Mumbai.
- `.env.example` makes OpenAI the primary LLM, with Gemini as the fallback. Embeddings stay on Gemini.
- The app offers Hindi and Marathi. The API also accepts Bengali and English.
