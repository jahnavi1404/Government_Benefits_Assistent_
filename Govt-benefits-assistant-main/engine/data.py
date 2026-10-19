"""Loads every scheme JSON file in data/schemes/ and normalises it.

Drop any number of .json files into data/schemes/ — they are all merged.
Each file must contain a JSON list of scheme objects. Missing keys are
filled with safe defaults, so a partially-filled dataset still works.
"""

import json
import os
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(HERE), "data", "schemes")

# Canonical Indian states and union territories.
STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal", "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir",
    "Ladakh", "Lakshadweep", "Puducherry",
]

OCCUPATIONS = [
    "farmer", "labourer", "student", "unemployed", "self employed", "business",
    "salaried", "artisan", "weaver", "fisherman", "street vendor",
    "domestic worker", "construction worker", "shopkeeper", "homemaker",
    "retired", "dairy", "carpenter", "tailor", "blacksmith", "potter",
]

SOCIAL_CATEGORIES = ["general", "obc", "sc", "st", "minority", "ews"]

EDUCATION_LEVELS = [
    "none", "primary", "upper primary", "class 8", "class 9", "class 10",
    "class 11", "class 12", "iti", "diploma", "undergraduate", "engineering",
    "postgraduate",
]

# Order matters: used to compare "at least this level".
EDUCATION_RANK = {level: i for i, level in enumerate(EDUCATION_LEVELS)}

DEFAULT_ELIGIBILITY = {
    "age_min": None,
    "age_max": None,
    "income_max": None,
    "gender": ["any"],
    "occupation": ["any"],
    "education": ["any"],
    "social_category": ["any"],
    "area": ["rural", "urban"],
    "states": ["all"],
    "disability_required": False,
    "category_or_gender": False,
    "other_criteria": [],
}


def _norm_list(value, fallback):
    if value is None:
        return list(fallback)
    if isinstance(value, str):
        value = [value]
    cleaned = [str(v).strip().lower() for v in value if str(v).strip()]
    return cleaned or list(fallback)


def normalise(scheme):
    """Fill in defaults so downstream code never has to guard for missing keys."""
    s = dict(scheme)
    s.setdefault("id", s.get("name", "unknown").lower().replace(" ", "-")[:60])
    s.setdefault("name", "Untitled scheme")
    s.setdefault("level", "central")
    s.setdefault("state", None)
    s.setdefault("ministry", "")
    s.setdefault("summary", "")
    s.setdefault("benefits", "")
    s.setdefault("deadline", "Not specified")
    s.setdefault("official_link", "")
    s.setdefault("documents", [])
    s.setdefault("process", [])
    s.setdefault("keywords", "")
    s.setdefault("source", "curated")
    s.setdefault("source_link", "")
    s["categories"] = _norm_list(s.get("categories"), ["general"])

    e = dict(DEFAULT_ELIGIBILITY)
    e.update(s.get("eligibility") or {})
    e["gender"] = _norm_list(e.get("gender"), ["any"])
    e["occupation"] = _norm_list(e.get("occupation"), ["any"])
    e["education"] = _norm_list(e.get("education"), ["any"])
    e["social_category"] = _norm_list(e.get("social_category"), ["any"])
    e["area"] = _norm_list(e.get("area"), ["rural", "urban"])
    e["states"] = _norm_list(e.get("states"), ["all"])
    e["disability_required"] = bool(e.get("disability_required"))
    e["category_or_gender"] = bool(e.get("category_or_gender"))
    e["other_criteria"] = list(e.get("other_criteria") or [])

    # A state scheme implicitly restricts itself to its own state.
    if s["level"] == "state" and s.get("state") and e["states"] == ["all"]:
        e["states"] = [s["state"].lower()]

    s["eligibility"] = e

    # How much of this record the rule engine can actually check. A corpus
    # record whose only rule is its own state cannot be verified against a
    # profile, and must not be presented as if it had been.
    checkable = [k for k in ("age_min", "age_max", "income_max") if e.get(k)]
    for k in ("gender", "occupation", "education", "social_category"):
        if "any" not in e[k]:
            checkable.append(k)
    if e.get("disability_required"):
        checkable.append("disability")
    if set(e["area"]) != {"rural", "urban"}:
        checkable.append("area")
    s["_rule_count"] = len(checkable)
    s["verified"] = (s["source"] == "curated")

    # One blob of text used by the semantic search.
    s["_text"] = " ".join([
        s["name"], s["summary"], s["benefits"], s["keywords"],
        " ".join(s["categories"]), " ".join(e["other_criteria"]),
        " ".join(e["occupation"]), s.get("state") or "",
    ]).lower()
    return s


def load_schemes(data_dir=DATA_DIR):
    schemes, seen = [], set()
    files = sorted(glob.glob(os.path.join(data_dir, "*.json")))
    for path in files:
        with open(path, "r", encoding="utf-8") as fh:
            try:
                payload = json.load(fh)
            except json.JSONDecodeError as exc:
                raise ValueError("%s is not valid JSON: %s" % (path, exc))
        if isinstance(payload, dict):
            payload = payload.get("schemes", [])
        for raw in payload:
            s = normalise(raw)
            if s["id"] in seen:          # later files win on duplicate ids
                schemes = [x for x in schemes if x["id"] != s["id"]]
            seen.add(s["id"])
            schemes.append(s)
    return schemes


def dataset_stats(schemes):
    states = sorted({s["state"] for s in schemes if s["state"]})
    cats = sorted({c for s in schemes for c in s["categories"]})
    return {
        "total": len(schemes),
        "central": sum(1 for s in schemes if s["level"] == "central"),
        "state": sum(1 for s in schemes if s["level"] == "state"),
        "states_covered": states,
        "categories": cats,
    }
