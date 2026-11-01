# Haq: Evaluation

**Related documents:** [Stress test](STRESS_TEST.md) · [Handover](HANDOVER.md)

Measured on 1 November 2026 against the public API with [measure_live.py](../scripts/measure_live.py), which re-checks quotes and numbers itself. These are three real documents, so treat the figures as a small sample. Claude ran the measurement and judged the answers, not a human Hindi or Marathi reader.

## Method

- **Documents:** three digital library PDFs, already parsed, so timings leave out first-time parsing and OCR.
- **Load:** the first document ran alongside two other runs, and the other two ran together.
- **Timing:** from outside, polling every 2 seconds. "Rights card" means rule compilation had finished, just after the card is complete.
- **Profile:** one written test profile, for a 15-year-old female ST student in Delhi with an income of ₹1,50,000.
- **Questions:** 10 off-topic and 3 on-topic, written by hand, on each document.

## Results by document

| Document | Pages | Language | Rights card | First audio after answers | Claims shown | Attempts rejected | Sentences with audio | Verdict |
|---|---|---|---|---|---|---|---|---|
| [PM's Scholarship Scheme](https://swd.hp.gov.in/wp-content/uploads/2024/08/Information-Brochure-2024-25.pdf) | 9 | Hindi | 48.4 s | 65.2 s | 21 | 27 | 21 of 21 | Doesn't meet (**wrong**) |
| [Delhi SC/ST/OBC scholarships](https://scstwelfare.delhi.gov.in/sites/default/files/scstwelfare/circulars-orders/guidelines_scholarship_2024-25.pdf) | 24 | Hindi | 82.9 s | 39.5 s | 48 | 20 | 16 of 21 | Doesn't meet (**wrong**) |
| [Pre-Matric Scholarship for ST](https://scholarships.gov.in/public/schemeGuidelines/guidelines-Pre-matric-ST.pdf) | 12 | Marathi | 36.1 s | 42.1 s | 23 | 18 | 21 of 21 | Can't determine |

## Results against targets

| Metric | Target | Result |
|---|---|---|
| Claims with valid citations | 100% | **92 of 92**, re-checked outside the backend |
| Numbers preserved in spoken sentences | 100% | **58 of 58**. The guard withheld audio for 5 more, all on the Delhi document |
| Sentences with a source claim | 100% | **63 of 63** |
| Abstention on off-topic questions | Report | **29 of 30**. The other was a cited, correct "no" to a Hindi question about a housing subsidy |
| Time to rights card | Under 60 s for 30 pages | **Missed:** 83 s on 24 pages, with two runs at once |
| Time to first audio | Under 2 minutes | **Met:** 40 to 65 s |
| Runs completed | No crash | **5 of 5.** Two early runs lost the script's connection, then finished on the server |
| Provider failovers | Report | 0, so failover wasn't exercised here |
| Precision and recall of facts | Report | **Not measured:** needs hand-labelled documents |
| Accuracy on about 20 profiles | Report | **Not measured.** See the defect below for the 3 verdicts checked |
| Invented facts in demo documents | Zero | **Not established:** valid citations don't prove every claim reads its clause correctly |

Tests at commit `2b63f64`, from a fresh clone: 63 frontend tests and 342 backend tests pass, with 140 integration tests skipped for lack of a local database. CI ran the integration tests on the same commit and passed.

## Defects found

### Eligibility rules for one group can reject everyone else

2 of 3 verdicts were false rejections, so the citizen heard "You do not appear to meet at least one criterion".

- **PM's Scholarship:** "Male wards are eligible up to 25 years of age" failed after the test profile answered that she was female, and it was the only failed rule. The same document says female wards are eligible and receive ₹36,000 a year.
- **Delhi:** a rule about the OBC pre-matric scheme failed for an ST student. The document covers several schemes, and only one needs to fit.

**Cause:** [decide](../backend/app/eligibility/interpreter.py) requires every rule to hold unless the claims share an `alternative_group`, and the rule compiler's prompt doesn't handle conditions that apply to only one group or scheme.

**Status:** not fixed. The stated facts are still correct and cited, but the verdict can't be relied on where a document has separate groups or schemes.

### Q&A can abstain when the document answers

Of 9 on-topic questions, 5 got a useful answer, 3 got "This document does not say", and 1 got a true non-answer: "The clauses do not give one single amount". The false abstentions included "What documents are needed to apply?" on two documents that list them. That wording is also wrong, because nothing has established that the document is silent.

**Status:** not fixed.

## Reproduce it

Each run uses provider credit and counts towards the per-IP run limit.

```sh
pip install pydantic rapidfuzz
PYTHONPATH=backend python scripts/measure_live.py --out results.json
```
