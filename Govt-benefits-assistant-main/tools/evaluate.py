"""Measure retrieval and eligibility accuracy.

    python tools/evaluate.py

Two things are measured:

**Retrieval** — 24 scenarios written the way a citizen would actually
describe their problem, each labelled with the scheme ids a correct system
should surface. Reported as Recall@5, Recall@10 and MRR. The current BM25
pipeline is compared against the plain TF-IDF cosine the project used first,
so the gain from BM25, bigrams and synonym expansion is visible rather than
asserted.

**Eligibility** — profiles paired with schemes they must and must not match,
checking the rule engine directly. Any regression here is a correctness bug,
not a ranking preference, so this section must stay at 100%.
"""

import math
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.data import load_schemes                      # noqa: E402
from engine.matcher import evaluate as check_eligibility   # noqa: E402
from engine.matcher import recommend                       # noqa: E402
from engine.search import SearchIndex, STOPWORDS           # noqa: E402
import re                                                  # noqa: E402

# --------------------------------------------------------------- baseline


class TfidfIndex:
    """The original retrieval: unigram TF-IDF cosine, no synonyms."""

    def __init__(self, schemes):
        self.tf, self.df = {}, Counter()
        for s in schemes:
            toks = [w for w in re.findall(r"[a-z]+", s["_text"].lower())
                    if len(w) > 2 and w not in STOPWORDS]
            counts = Counter(toks)
            self.tf[s["id"]] = counts
            for t in counts:
                self.df[t] += 1
        self.n = max(len(schemes), 1)
        self.vec = {sid: self._v(c) for sid, c in self.tf.items()}

    def _idf(self, t):
        return math.log((self.n + 1) / (self.df.get(t, 0) + 1)) + 1.0

    def _v(self, counts):
        v = {t: (1 + math.log(c)) * self._idf(t) for t, c in counts.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def score(self, query):
        toks = [w for w in re.findall(r"[a-z]+", query.lower())
                if len(w) > 2 and w not in STOPWORDS]
        if not toks:
            return {}
        q = self._v(Counter(toks))
        out = {}
        for sid, d in self.vec.items():
            tot = sum(q[t] * d[t] for t in q if t in d)
            if tot > 0:
                out[sid] = tot
        if not out:
            return {}
        top = max(out.values())
        return {k: v / top for k, v in out.items()}


# -------------------------------------------------------------- scenarios
# (free text the user types, profile they have given, acceptable scheme ids)

RETRIEVAL_CASES = [
    ("my father needs a heart operation and we cannot afford the hospital bill",
     {"state": "Telangana", "age": 72},
     {"pmjay", "vay-vandana", "ts-aarogyasri"}),
    ("I have to get my mother admitted to hospital but we have no money",
     {"state": "Kerala", "age": 45},
     {"pmjay", "kl-karunya-arogya"}),
    ("my family cannot pay my engineering college fees",
     {"state": "Telangana", "age": 19, "gender": "female"},
     {"aicte-pragati", "ts-epass", "nsp-post-matric-obc", "nsp-post-matric-scst"}),
    ("I want a scholarship to continue school after 10th",
     {"state": "Bihar", "age": 16},
     {"nmms", "nsp-post-matric-scst", "nsp-post-matric-obc", "pm-yasasvi"}),
    ("we live in a mud hut in the village and the roof leaks",
     {"state": "Odisha", "area": "rural"},
     {"pmay-g"}),
    ("I rent a room in the city and want help buying a flat",
     {"state": "Maharashtra", "area": "urban"},
     {"pmay-u"}),
    ("I lost my job and I am a graduate looking for work",
     {"state": "Karnataka", "age": 23},
     {"ka-yuva-nidhi", "pm-internship", "pmkvy"}),
    ("I want free skill training so I can get a job",
     {"state": "Jharkhand", "age": 20, "area": "rural"},
     {"pmkvy", "ddu-gky"}),
    ("I sell vegetables on a cart and need money to buy stock",
     {"state": "Maharashtra", "area": "urban"},
     {"pm-svanidhi", "pmmy-mudra"}),
    ("I want to start a small tailoring business from home but have no capital",
     {"state": "Gujarat", "age": 27, "gender": "female"},
     {"pmmy-mudra", "pm-vishwakarma", "pmegp", "standup-india"}),
    ("I am a farmer and I need money at the start of the season for seeds",
     {"state": "Telangana", "occupation": "farmer"},
     {"pm-kisan", "kcc", "ts-rythu-bharosa"}),
    ("my crop was destroyed by floods",
     {"state": "Odisha", "occupation": "farmer"},
     {"pmfby"}),
    ("I am 65 and have no income after retiring, is there any monthly pension",
     {"state": "Karnataka", "age": 65},
     {"nsap-ignoaps"}),
    ("I am 30 and want to save for a pension when I am old",
     {"state": "Delhi", "age": 30},
     {"apy", "shram-yogi-maandhan", "nps-traders"}),
    ("my husband died and I have no way to feed my children",
     {"state": "Uttar Pradesh", "age": 42, "gender": "female"},
     {"nsap-ignwps", "nfsa-ration"}),
    ("we do not have a ration card and there is not enough food at home",
     {"state": "Jharkhand"},
     {"nfsa-ration"}),
    ("I cannot walk after polio and I need a wheelchair",
     {"state": "Bihar", "age": 29, "disability": True},
     {"adip", "udid", "nsap-igndps"}),
    ("I am blind and want a disability certificate",
     {"state": "Assam", "age": 25, "disability": True},
     {"udid", "adip"}),
    ("my daughter is getting married next month and we cannot afford it",
     {"state": "Telangana", "gender": "female", "age": 22},
     {"ts-kalyana-lakshmi"}),
    ("I am pregnant and not able to work, is there any help",
     {"state": "Rajasthan", "gender": "female", "age": 26},
     {"pmmvy", "jsy"}),
    ("I want to open a savings account for my baby girl",
     {"state": "Gujarat", "gender": "female"},
     {"sukanya", "gj-namo-lakshmi", "mahila-samman"}),
    ("we still cook on firewood and want a gas connection",
     {"state": "Bihar", "gender": "female", "area": "rural"},
     {"ujjwala"}),
    ("my electricity bill is very high, can I put solar panels on my roof",
     {"state": "Gujarat"},
     {"pm-surya-ghar"}),
    ("I work as a daily wage labourer and want some work near my village",
     {"state": "Chhattisgarh", "area": "rural", "occupation": "labourer"},
     {"mgnrega", "e-shram"}),
]

ELIGIBILITY_CASES = [
    # (profile, scheme id, must be eligible?)
    ({"age": 72, "state": "Telangana"}, "vay-vandana", True),
    ({"age": 55, "state": "Telangana"}, "vay-vandana", False),
    ({"age": 30, "gender": "male"}, "aicte-pragati", False),
    ({"age": 19, "gender": "female", "income": 400000,
      "education": "engineering"}, "aicte-pragati", True),
    ({"age": 19, "gender": "female", "income": 1200000,
      "education": "engineering"}, "aicte-pragati", False),
    ({"age": 45, "state": "Karnataka"}, "ts-kalyana-lakshmi", False),
    ({"age": 22, "gender": "female", "state": "Telangana",
      "income": 150000}, "ts-kalyana-lakshmi", True),
    ({"age": 25, "state": "Bihar", "area": "urban"}, "pmay-g", False),
    ({"age": 25, "state": "Bihar", "area": "rural"}, "pmay-g", True),
    ({"age": 45, "occupation": "farmer"}, "apy", False),
    ({"age": 35, "occupation": "farmer"}, "apy", True),
    ({"age": 29, "disability": False}, "nsap-igndps", False),
    ({"age": 29, "disability": True}, "nsap-igndps", True),
    ({"age": 26, "gender": "male", "state": "Karnataka",
      "education": "undergraduate", "occupation": "unemployed"},
     "ka-yuva-nidhi", True),
    ({"age": 26, "gender": "male", "state": "Kerala",
      "education": "undergraduate", "occupation": "unemployed"},
     "ka-yuva-nidhi", False),
    ({"age": 40, "occupation": "salaried"}, "pm-kisan", False),
]


def run_retrieval(schemes, index, label, mode="end2end"):
    """mode 'index' ranks by the search index alone, isolating retrieval
    quality from the eligibility engine and the tier ordering. mode
    'end2end' measures what the user actually sees."""
    hits5 = hits10 = 0
    rr = 0.0
    misses = []
    for query, profile, expected in RETRIEVAL_CASES:
        if mode == "index":
            scored = index.score(query)
            ids = [sid for sid, _ in
                   sorted(scored.items(), key=lambda kv: -kv[1])[:10]]
        else:
            ranked = recommend(schemes, index, profile, query=query, limit=10)
            ids = [r["scheme"]["id"] for r in ranked]
        top5, top10 = ids[:5], ids[:10]
        ok5 = bool(expected & set(top5))
        hits5 += ok5
        hits10 += bool(expected & set(top10))
        rank = next((i + 1 for i, s in enumerate(ids) if s in expected), None)
        rr += 1.0 / rank if rank else 0.0
        if not ok5:
            misses.append((query, ids[:3]))
    n = len(RETRIEVAL_CASES)
    print("%-22s Recall@5 %5.1f%%   Recall@10 %5.1f%%   MRR %.3f"
          % (label, 100 * hits5 / n, 100 * hits10 / n, rr / n))
    return misses


def run_eligibility(schemes):
    by_id = {s["id"]: s for s in schemes}
    passed, failures = 0, []
    for profile, sid, should in ELIGIBILITY_CASES:
        scheme = by_id.get(sid)
        if not scheme:
            failures.append((sid, "scheme missing from dataset"))
            continue
        status, reasons, blockers = check_eligibility(scheme, profile)
        got = status in ("eligible", "likely")
        if got == should:
            passed += 1
        else:
            failures.append((sid, "expected %s, got %s (%s)"
                             % ("eligible" if should else "not eligible",
                                status, "; ".join(blockers) or "no blocker")))
    n = len(ELIGIBILITY_CASES)
    print("Eligibility rules     %d/%d correct (%.0f%%)" % (passed, n, 100 * passed / n))
    for sid, why in failures:
        print("   FAIL %-24s %s" % (sid, why))
    return not failures


def main():
    schemes = load_schemes()
    print("Dataset: %d schemes (%d with verified rules, %d from the corpus)\n"
          % (len(schemes), sum(1 for s in schemes if s["verified"]),
             sum(1 for s in schemes if not s["verified"])))

    tfidf, bm25 = TfidfIndex(schemes), SearchIndex(schemes)

    print("Search index alone, over %d citizen-worded scenarios"
          % len(RETRIEVAL_CASES))
    run_retrieval(schemes, tfidf, "  TF-IDF (baseline)", mode="index")
    run_retrieval(schemes, bm25, "  BM25 + synonyms", mode="index")

    print("\nFull pipeline (search + eligibility engine + tiers)")
    run_retrieval(schemes, tfidf, "  TF-IDF (baseline)")
    misses = run_retrieval(schemes, bm25, "  BM25 + synonyms")

    print()
    ok = run_eligibility(schemes)

    if misses:
        print("\nStill missing in the top 5:")
        for query, top in misses:
            print("  %-58s -> %s" % (query[:58], ", ".join(t[:28] for t in top)))

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
