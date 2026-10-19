"""Eligibility rule engine + semantic ranking.

Two independent signals are combined:

1. Rule engine  - hard criteria from the scheme's own eligibility block are
                  checked one by one against the user profile. Every check
                  produces a human-readable reason, which is what the UI shows
                  as "why you are eligible".
2. Semantic rank - a TF-IDF cosine similarity between the user's free-text
                  query and the scheme text, implemented in pure Python so
                  the project has no ML dependency.

A scheme is only recommended if it clears the rule engine. The semantic score
re-orders the schemes that survive, so a chat query like "I cannot afford my
daughter's college fees" pushes education schemes to the top.
"""

from .data import EDUCATION_RANK
from .search import SearchIndex, tokenise  # noqa: F401

STOPWORDS = set("""
a an the and or but if of for to in on at by with from is am are was were be
been being do does did have has had i me my mine we us our you your he she it
they them their this that these those as so not no yes can could would should
will shall may might must there here what which who whom how when where why
want need get got give please help me sir madam very much any some all
money amount rs rupees scheme government india per year also
""".split())


# --------------------------------------------------------------------------
# Rule engine
# --------------------------------------------------------------------------

def _check_age(e, p, reasons, blockers):
    age = p.get("age")
    lo, hi = e.get("age_min"), e.get("age_max")
    if lo is None and hi is None:
        return
    if age is None:
        reasons.append("Age criteria apply — confirm your age")
        return
    if lo is not None and age < lo:
        blockers.append("Minimum age is %d, you are %d" % (lo, age))
        return
    if hi is not None and age > hi:
        blockers.append("Maximum age is %d, you are %d" % (hi, age))
        return
    if lo is not None and hi is not None:
        reasons.append("Your age %d is within the %d-%d range" % (age, lo, hi))
    elif lo is not None:
        reasons.append("You are %d, above the minimum age of %d" % (age, lo))
    else:
        reasons.append("You are %d, within the upper age limit of %d" % (age, hi))


def _check_income(e, p, reasons, blockers):
    cap = e.get("income_max")
    if cap is None:
        return
    income = p.get("income")
    if income is None:
        reasons.append("An income ceiling of Rs %s applies" % f"{cap:,}")
        return
    if income > cap:
        blockers.append("Income ceiling is Rs %s, yours is Rs %s"
                        % (f"{cap:,}", f"{income:,}"))
        return
    reasons.append("Your annual income of Rs %s is within the Rs %s ceiling"
                   % (f"{income:,}", f"{cap:,}"))


def _check_gender(e, p, reasons, blockers, soft=False):
    allowed = e.get("gender", ["any"])
    if "any" in allowed:
        return True
    g = p.get("gender")
    if not g:
        reasons.append("Meant for: %s applicants" % ", ".join(allowed))
        return True
    if g.lower() not in allowed:
        if not soft:
            blockers.append("Open only to %s applicants" % ", ".join(allowed))
        return False
    reasons.append("Reserved for %s applicants" % ", ".join(allowed))
    return True


def _check_category(e, p, reasons, blockers, soft=False):
    allowed = e.get("social_category", ["any"])
    if "any" in allowed:
        return True
    c = p.get("social_category")
    if not c:
        reasons.append("Meant for %s category applicants" % "/".join(allowed).upper())
        return True
    if c.lower() not in allowed:
        if not soft:
            blockers.append("Open only to %s category" % "/".join(allowed).upper())
        return False
    reasons.append("You belong to the %s category this scheme targets" % c.upper())
    return True


def _check_occupation(e, p, reasons, blockers):
    allowed = e.get("occupation", ["any"])
    if "any" in allowed:
        return
    occ = (p.get("occupation") or "").lower()
    if not occ:
        reasons.append("Intended for: %s" % ", ".join(allowed))
        return
    if occ not in allowed:
        # Treat 'unemployed'/'student' loosely — many schemes list both.
        blockers.append("Meant for %s, your occupation is %s"
                        % (", ".join(allowed), occ))
        return
    reasons.append("Your occupation (%s) matches this scheme" % occ)


def _check_education(e, p, reasons, blockers):
    allowed = e.get("education", ["any"])
    if "any" in allowed:
        return
    edu = (p.get("education") or "").lower()
    if not edu:
        reasons.append("Education requirement: %s" % ", ".join(allowed))
        return
    if edu in allowed:
        reasons.append("Your education level (%s) qualifies" % edu)
        return
    # Allow a higher level to satisfy a lower requirement where ranked.
    # "Higher level satisfies lower" holds for a minimum-qualification rule
    # ("8th pass or above"), not for a scheme aimed at a school class — a
    # B.Tech student is not eligible for a class 8 scholarship.
    user_rank = EDUCATION_RANK.get(edu)
    req_ranks = [EDUCATION_RANK[a] for a in allowed if a in EDUCATION_RANK]
    open_ended = any(r >= EDUCATION_RANK["iti"] for r in req_ranks)
    if open_ended and user_rank is not None and req_ranks and user_rank >= min(req_ranks):
        reasons.append("Your education level (%s) meets the requirement" % edu)
        return
    blockers.append("Education requirement is %s" % ", ".join(allowed))


def _check_area(e, p, reasons, blockers):
    allowed = e.get("area", ["rural", "urban"])
    if set(allowed) >= {"rural", "urban"}:
        return
    area = (p.get("area") or "").lower()
    if not area:
        reasons.append("Applies to %s areas" % "/".join(allowed))
        return
    if area not in allowed:
        blockers.append("Applies only to %s areas" % "/".join(allowed))
        return
    reasons.append("You live in a %s area, which this scheme covers" % area)


def _check_state(e, s, p, reasons, blockers):
    allowed = e.get("states", ["all"])
    if "all" in allowed:
        if s["level"] == "central":
            reasons.append("Central scheme, available across India")
        return
    state = (p.get("state") or "").lower()
    if not state:
        reasons.append("State scheme for %s" % ", ".join(a.title() for a in allowed))
        return
    if state not in allowed:
        blockers.append("Available only in %s"
                        % ", ".join(a.title() for a in allowed))
        return
    reasons.append("You are in %s, where this state scheme applies" % state.title())


def _check_disability(e, p, reasons, blockers):
    if not e.get("disability_required"):
        return
    if p.get("disability") is True:
        reasons.append("You reported a disability, which this scheme requires")
    elif p.get("disability") is False:
        blockers.append("Requires a certified disability of the notified degree")
    else:
        reasons.append("Requires a certified disability")


def evaluate(scheme, profile):
    """Return (status, reasons, blockers).

    status is 'eligible', 'likely' (criteria exist but profile is incomplete)
    or 'not_eligible'.
    """
    e = scheme["eligibility"]
    reasons, blockers = [], []

    _check_age(e, profile, reasons, blockers)
    _check_income(e, profile, reasons, blockers)
    _check_occupation(e, profile, reasons, blockers)
    _check_education(e, profile, reasons, blockers)
    _check_area(e, profile, reasons, blockers)
    _check_state(e, scheme, profile, reasons, blockers)
    _check_disability(e, profile, reasons, blockers)

    if e.get("category_or_gender"):
        # Either the social category OR the gender condition is enough.
        soft_reasons, soft_blockers = [], []
        ok_g = _check_gender(e, profile, soft_reasons, soft_blockers, soft=True)
        ok_c = _check_category(e, profile, soft_reasons, soft_blockers, soft=True)
        if ok_g or ok_c:
            reasons.extend(soft_reasons)
        else:
            blockers.append("Open to %s applicants or the %s category"
                            % (", ".join(e["gender"]),
                               "/".join(e["social_category"]).upper()))
    else:
        _check_gender(e, profile, reasons, blockers)
        _check_category(e, profile, reasons, blockers)

    if blockers:
        return "not_eligible", reasons, blockers

    # Did the user actually supply the fields this scheme cares about?
    needed = []
    if e.get("age_min") or e.get("age_max"):
        needed.append("age")
    if e.get("income_max"):
        needed.append("income")
    if "any" not in e["occupation"]:
        needed.append("occupation")
    if "any" not in e["social_category"]:
        needed.append("social_category")
    if "any" not in e["education"]:
        needed.append("education")
    if "any" not in e["gender"]:
        needed.append("gender")
    if set(e["area"]) != {"rural", "urban"}:
        needed.append("area")
    if e.get("disability_required"):
        needed.append("disability")
    missing = [f for f in needed if profile.get(f) in (None, "")]

    if not scheme.get("verified") and scheme.get("_rule_count", 0) <= UNVERIFIED_MAX_RULES:
        # Nothing here was checkable beyond which state it belongs to.
        return "unverified", reasons, blockers
    return ("likely" if missing else "eligible"), reasons, blockers


# --------------------------------------------------------------------------
# Recommendation
# --------------------------------------------------------------------------

# Backwards-compatible alias: the index used to be TF-IDF cosine.
SemanticIndex = SearchIndex

STATUS_WEIGHT = {"eligible": 1.0, "likely": 0.72, "unverified": 0.5}

# A record the rule engine cannot check must not be shown as a verdict.
UNVERIFIED_MAX_RULES = 1

# How many of a result page may come from the unchecked corpus.
CORPUS_SLOTS = 5


def recommend(schemes, index, profile, query="", limit=25,
              include_near_misses=False):
    """Rank schemes for a profile, optionally boosted by a free-text query.

    Returns results in tiers. A scheme whose criteria the engine actually
    checked against the profile always outranks one it could only read the
    text of, because only the first kind can honestly be called a match.
    """
    sem = index.score(query) if query else {}

    results, near = [], []
    for s in schemes:
        status, reasons, blockers = evaluate(s, profile)
        if status == "not_eligible":
            if include_near_misses and len(blockers) == 1 and s.get("verified"):
                near.append({"scheme": s, "status": status, "reasons": reasons,
                             "blockers": blockers, "score": 0.0, "semantic": 0.0})
            continue

        sem_score = sem.get(s["id"], 0.0)

        # An unverified record is only worth showing when the user's own words
        # point at it. Never surface one on a blank profile query.
        if status == "unverified" and sem_score < 0.18:
            continue

        base = STATUS_WEIGHT[status]
        e = s["eligibility"]
        # Don't push a scheme that hinges on an attribute the user never
        # claimed (a disability, a caste, a gender) to the top of the list.
        if e.get("disability_required") and profile.get("disability") is not True:
            base *= 0.35
        if "any" not in e["social_category"] and not profile.get("social_category"):
            base *= 0.6
        if "any" not in e["gender"] and not profile.get("gender"):
            base *= 0.6

        specificity = min(len(reasons), 6) / 6.0

        if query:
            score = 0.24 * base + 0.14 * specificity + 0.62 * sem_score
        else:
            score = 0.62 * base + 0.38 * specificity
            if s["level"] == "state" and profile.get("state"):
                score += 0.05

        results.append({
            "scheme": s, "status": status, "reasons": reasons, "blockers": [],
            "score": round(score, 4), "semantic": round(sem_score, 4),
            "tier": 0 if s.get("verified") else 1,
        })

    def rank(r):
        # tier, then verdict strength, then score.
        verdict = {"eligible": 0, "likely": 1, "unverified": 2}[r["status"]]
        return (r["tier"], verdict, -r["score"], r["scheme"]["name"])

    if query:
        results.sort(key=lambda r: (-r["score"], r["scheme"]["name"]))
        relevant = [r for r in results if r["semantic"] > 0.22]
        if len(relevant) >= 4:
            results = relevant
        else:
            on_topic = sorted((r for r in results if r["semantic"] > 0),
                              key=lambda r: -r["semantic"])[:6]
            rest = [r for r in results if r not in on_topic]
            results = on_topic + rest
        # Even with a query, a checked match leads.
        results.sort(key=lambda r: (r["tier"], -r["score"]))
    else:
        results.sort(key=rank)

    # The corpus is 15x the size of the curated set, so a straight tier sort
    # would bury it entirely. Reserve a few slots for the most on-topic
    # corpus entries instead, and let the UI show them in their own section.
    checked = [r for r in results if r["status"] != "unverified"]
    corpus = [r for r in results if r["status"] == "unverified"]
    corpus_slots = min(CORPUS_SLOTS, max(0, limit - 4)) if corpus else 0
    out = checked[:limit - corpus_slots] + corpus[:corpus_slots]

    if include_near_misses:
        near.sort(key=lambda r: r["scheme"]["name"])
        return out, near[:6]
    return out
