# Haq: Submission

Text for the Learning Platform form. Replace anything in square brackets.

**Team:** Deepak Kumar Singh and Shivansh

**Problem:** Problem 1, Multilingual Policy, Rights & Scheme Explainer

**Live app:** https://hackthon-rust-gamma.vercel.app

**GitHub:** https://github.com/Deepak1230987/hackthon

**Deck:** [public deck link]

**Demo video (2-3 minutes):** [public video link]

**Social post (optional):** [link]

## Problem and audience

Government notifications and welfare policies decide what people can claim, but they're long, legalistic, often scanned, and often not in the reader's language. A chatbot can summarise one, but it can also invent a rule or an amount, and the reader can't tell. Haq is for citizens with low literacy or limited English, small business owners, and the field workers who explain schemes to them.

## Solution

Haq turns a real government PDF into a spoken explanation in Hindi or Marathi. Every sentence links to the clause it came from. A claim is shown only after code finds its quote in the cited clause and its numbers in the quote, and an LLM judges that the source supports it. Eligibility is calculated by code from rules compiled from verified claims, and numbers are compared again after translation. A question the document doesn't support gets "This document does not say".

## Architecture

A Next.js frontend on Vercel talks over REST and SSE to a FastAPI and LangGraph backend, in Docker on an Azure VM. Supabase holds documents, clauses, checkpoints and audio. OpenAI and Gemini provide the LLM, OCR and embeddings with failover, and Sarvam provides speech and translation. Diagrams are in the README.

## Measured results

On 3 real government PDFs through the live system: 92 of 92 shown claims passed a separate citation re-check, 58 of 58 spoken sentences kept their numbers, and 29 of 30 off-topic questions got an abstention. Time to first audio was 40 to 65 seconds after answers. Known problems: 2 of 3 eligibility verdicts were false rejections, 3 of 9 on-topic questions got a false abstention, and precision and recall haven't been measured. Details are in `docs/EVALUATION.md`.

## Before you submit

- [ ] Live URL opens in incognito and on a phone
- [ ] Deck and video open in incognito, without a sign-in
- [ ] Video shows the running system and the public URL
- [ ] Both members have gone through `docs/HANDOVER.md`
- [ ] Both members are eligible: IIT, NIT, IIIT or BITS students graduating in 2027 or later
- [ ] Confirmation saved, then tag the submitted commit: `git tag submitted && git push origin submitted`
