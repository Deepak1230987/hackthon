"""Measure a running Haq deployment with real documents, and re-check what it returns.

    PYTHONPATH=backend python scripts/measure_live.py --out results.json

Needs pydantic and rapidfuzz, for the number and quote checks shared with the backend. It starts
three runs and asks 13 questions on each. Those are real calls that use provider credit, and they
count towards the per-IP run limit.

Everything is measured from outside, over the public API, and quotes and numbers are checked again
here rather than taking the backend's word for them. The question lists are written by hand, and
whether an out-of-scope question really is out of scope is a judgement a reader should check.
"""

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter

from rapidfuzz.fuzz import partial_ratio

from app.claims.verifier import OCR_MATCH_THRESHOLD, _comparable
from app.documents.normalize import normalize
from app.voice.guard import numbers_match

POLL_S = 2
CONNECT_RETRIES = 5
RUN_DEADLINE_S = 900
FINISHED = ("completed", "partial", "failed")

# A written test profile, not a person. The API holds these in memory only, and they're never
# included in the results.
PROFILE = {
    "age": 15,
    "gender": "female",
    "state": "Delhi",
    "annual_income_inr": 150000,
    "occupation": "student",
    "social_category": "st",
    "land_holding_hectares": 0,
    "is_bpl": True,
    "is_student": True,
    "has_disability": False,
}

# Library documents are chosen by title because their ids belong to one deployment's database.
DOCUMENTS = [
    ("Scholarship Schemes for SC/ST/OBC Students", "hi"),
    ("PM's Scholarship Scheme for Dependent Wards", "hi"),
    ("Pre-Matric Scholarship for ST Students", "mr"),
]

# None of the three documents is about these.
OUT_OF_SCOPE = [
    "What is the fine for riding a motorcycle without a helmet?",
    "What is the capital of France?",
    "How much crop insurance does a farmer get per hectare?",
    "What is the monthly old age pension for a widow in Kerala?",
    "How do I apply for a new passport?",
    "What is the GST rate on restaurant food?",
    "What is the interest rate on a Mudra loan?",
    "How many free LPG cylinders does the Ujjwala scheme give?",
    "क्या इस योजना में घर बनाने के लिए सब्सिडी मिलती है?",
    "What is the minimum support price of wheat this year?",
]
# Each of the three documents covers these in some form.
IN_SCOPE = [
    "Who is eligible for this scholarship?",
    "How much money does a student get?",
    "What documents are needed to apply?",
]


def call(api: str, method: str, path: str, body: dict | None = None, timeout: int = 180) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        api + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    for attempt in range(CONNECT_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError:
            # The connection never opened, so the server hasn't seen this request.
            if attempt == CONNECT_RETRIES - 1:
                raise
            time.sleep(POLL_S)
    raise AssertionError("unreachable")


def check_citations(claims: list[dict], clauses: list[dict]) -> dict:
    """Whether each quote really is in the clauses it cites, using the backend's own OCR threshold."""
    by_id = {clause["id"]: clause for clause in clauses}
    valid = 0
    invalid = []
    for claim in claims:
        cited = [by_id.get(clause["id"]) for clause in claim["clauses"]]
        if not cited or None in cited:
            invalid.append(claim["id"])
            continue
        quote = _comparable(normalize(claim["quote"]))
        source = _comparable(" ".join(normalize(clause["text"]) for clause in cited))
        if any(clause["extraction"] == "ocr" for clause in cited):
            found = partial_ratio(quote, source) >= OCR_MATCH_THRESHOLD
        else:
            found = quote in source
        if found:
            valid += 1
        else:
            invalid.append(claim["id"])
    return {"claims": len(claims), "valid": valid, "invalid_ids": invalid}


def check_sentences(sentences: list[dict]) -> dict:
    translated = [s for s in sentences if s["translated_text"]]
    # Withheld sentences never reach the citizen, so only what can be heard counts here.
    spoken = [s for s in translated if s["audio_path"]]
    changed = [s["id"] for s in spoken if not numbers_match(s["source_text"], s["translated_text"])]
    return {
        "sentences": len(sentences),
        "translated": len(translated),
        "with_audio": len(spoken),
        "guard_status": Counter(s["guard_status"] for s in sentences),
        "spoken_with_changed_number_ids": changed,
        "without_source_claim": sum(1 for s in sentences if not s["claim_ids"]),
    }


def ask_all(api: str, run_id: str, result: dict) -> None:
    result["qa"] = []
    for kind, questions in (("out_of_scope", OUT_OF_SCOPE), ("in_scope", IN_SCOPE)):
        for question in questions:
            started = time.monotonic()
            try:
                reply = call(api, "POST", f"/v1/runs/{run_id}/qa", {"question": question})
            except urllib.error.HTTPError as exc:
                result["qa"].append({"kind": kind, "question": question, "http_error": exc.code})
                continue
            result["qa"].append(
                {
                    "kind": kind,
                    "question": question,
                    "abstained": reply["abstained"],
                    "answer_en": reply["answer_en"],
                    "language": reply["language"],
                    "citations": len(reply["citations"]),
                    "seconds": round(time.monotonic() - started, 1),
                }
            )


def measure(api: str, document: dict, language: str, result: dict, lock: threading.Lock, save) -> None:
    started = time.monotonic()
    run_id = call(api, "POST", f"/v1/library/{document['id']}/runs", {"language": language})["run_id"]
    result.update(
        run_id=run_id, title=document["title"], pages=document["page_count"],
        scanned=document["is_scanned"], language=language,
    )  # fmt: skip
    first_claim = rights_card = last_answer = first_audio = None
    answered = 0
    view: dict = {}
    while time.monotonic() - started < RUN_DEADLINE_S:
        view = call(api, "GET", f"/v1/runs/{run_id}")
        now = time.monotonic()
        nodes = {e["payload"].get("node") for e in view["events"] if e["type"] == "node_finished"}
        if first_claim is None and view["claims"]:
            first_claim = now - started
        if rights_card is None and "verify" in nodes and "compile_rules" in nodes:
            rights_card = now - started
        if first_audio is None and any(e["type"] == "sentence_ready" for e in view["events"]):
            first_audio = now - (last_answer if last_answer else started)
        if view["status"] == "waiting_input" and view["question"]:
            name = view["question"]["name"]
            body = {"answers": {name: PROFILE[name]}} if name in PROFILE else {"skip": [name]}
            call(api, "POST", f"/v1/runs/{run_id}/answers", body)
            answered += 1
            last_answer = time.monotonic()
        elif view["status"] in FINISHED:
            break
        time.sleep(POLL_S)

    events = Counter(e["type"] for e in view["events"])
    rejected = Counter(
        e["payload"].get("reason") for e in view["events"] if e["type"] == "claim_rejected"
    )
    nodes_ms = Counter()
    for event in view["events"]:
        if event["type"] == "node_finished":
            nodes_ms[event["payload"]["node"]] += event["payload"]["duration_ms"]
    clauses = call(api, "GET", f"/v1/documents/{view['document']['id']}/clauses")["clauses"]
    result.update(
        status=view["status"],
        error=view["error"],
        total_seconds=round(time.monotonic() - started, 1),
        seconds_to_first_verified_claim=first_claim and round(first_claim, 1),
        seconds_to_rights_card=rights_card and round(rights_card, 1),
        seconds_to_first_audio_after_answers=first_audio and round(first_audio, 1),
        questions_answered=answered,
        verdict=(view["verdict"] or {}).get("outcome") if view["verdict"] else None,
        verdict_raw=view["verdict"],
        not_stated=view["not_stated"],
        claims_rejected=sum(rejected.values()),
        rejection_reasons=rejected,
        retries=events["retry"],
        failovers=events["failover"],
        rules_compiled=next(
            (e["payload"]["count"] for e in view["events"] if e["type"] == "rules_compiled"), None
        ),
        node_seconds={node: round(ms / 1000, 1) for node, ms in nodes_ms.items()},
        citations=check_citations(view["claims"], clauses),
        speech=check_sentences(view["sentences"]),
    )
    with lock:
        save()
    if view["status"] in ("completed", "partial"):
        ask_all(api, run_id, result)
        with lock:
            save()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="https://haq.southindia.cloudapp.azure.com")
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", help="Measure only documents whose title contains this")
    args = parser.parse_args()

    documents = [d for d in DOCUMENTS if not args.only or args.only in d[0]]
    library = call(args.api, "GET", "/v1/library")["documents"]
    results: list[dict] = [{} for _ in documents]
    lock = threading.Lock()

    def save() -> None:
        with open(args.out, "w", encoding="utf-8") as out:
            json.dump(results, out, ensure_ascii=False, indent=1)

    threads = []
    for slot, (prefix, language) in zip(results, documents, strict=True):
        document = next(d for d in library if d["title"].startswith(prefix))

        def work(document=document, language=language, slot=slot) -> None:
            try:
                measure(args.api, document, language, slot, lock, save)
            except Exception as exc:  # A failed run is a result too, and must not lose the others.
                slot["script_error"] = repr(exc)
                with lock:
                    save()

        threads.append(threading.Thread(target=work))
        threads[-1].start()
    for thread in threads:
        thread.join()
    save()
    json.dump(results, sys.stdout, ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()
