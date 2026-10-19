"""Turn the scraped .txt corpus into the structured JSON the app uses.

    python tools/ingest.py /path/to/archive-folder -o data/schemes/dataset.json

The corpus is web-scraped: one folder per state plus a `central` folder, each
holding loose .txt files with advertising script tags, navigation blobs,
duplicated articles and no consistent field labels. This script does four
things:

1. cleans the page furniture out of each file,
2. drops exact and near-duplicate articles,
3. splits the remaining text into sections by heading,
4. reads machine-checkable eligibility rules out of those sections.

Whatever it cannot read confidently is left out of the rule block and kept as
free text under `other_criteria`, so the app shows it to the user instead of
silently guessing.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.data import STATES  # noqa: E402

FOLDER_TO_STATE = {
    "andhra-pradesh": "Andhra Pradesh", "arunachal-pradesh": "Arunachal Pradesh",
    "assam": "Assam", "bihar": "Bihar", "chandigarh": "Chandigarh",
    "chhattisgarh": "Chhattisgarh", "delhi": "Delhi", "goa": "Goa",
    "gujarat": "Gujarat", "haryana": "Haryana",
    "himachal-pradesh": "Himachal Pradesh", "jammu-kashmir": "Jammu and Kashmir",
    "jharkhand": "Jharkhand", "karnataka": "Karnataka", "kerala": "Kerala",
    "madhya-pradesh": "Madhya Pradesh", "maharashtra": "Maharashtra",
    "manipur": "Manipur", "meghalaya": "Meghalaya", "mizoram": "Mizoram",
    "nagaland": "Nagaland", "odisha": "Odisha", "puducherry": "Puducherry",
    "punjab": "Punjab", "rajasthan": "Rajasthan", "sikkim": "Sikkim",
    "tamilnadu": "Tamil Nadu", "telangana": "Telangana", "tripura": "Tripura",
    "uttar-pradesh": "Uttar Pradesh", "uttarakhand": "Uttarakhand",
    "west-bengal": "West Bengal", "ladakh": "Ladakh",
    "lakshadweep": "Lakshadweep",
}

# --------------------------------------------------------------- cleaning

JUNK_LINE = re.compile(
    r"^\s*(\(?adsbygoogle|window\.adsbygoogle|<script|</script|"
    r"table of contents\s*$|share this|tweet|whatsapp|facebook|"
    r"click here to|read more\s*$|advertisement\s*$|also read)",
    re.I)

# The scraped pages open with a run-together list of their own headings.
TOC_BLOB = re.compile(r"^[A-Z][^\s].{80,}$")


def clean(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\(adsbygoogle[^\n]*", "", text)
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or JUNK_LINE.match(line):
            continue
        out.append(line)

    # Drop a leading table-of-contents blob: a very long line with no spaces
    # after punctuation, sitting in the first three lines.
    while len(out) > 1 and TOC_BLOB.match(out[0]) and \
            len(re.findall(r"[a-z][A-Z]", out[0])) >= 3:
        out.pop(0)
    return out


# --------------------------------------------------------------- sections

HEADING_KEYS = [
    ("eligibility", r"eligib|who can apply|beneficiar|criteria|qualif"),
    ("benefits", r"benefit|assistance|amount|features|salient|what you get|"
                 r"financial help|subsidy"),
    ("documents", r"document|papers required|certificates required"),
    ("process", r"how to apply|application (process|procedure)|registration "
                r"(process|procedure)|apply online|steps to"),
    ("objective", r"objective|aim|purpose|about|introduction|overview"),
    ("deadline", r"last date|deadline|important dates|closing date"),
]


def is_heading(line):
    """Scraped headings are short lines with no terminal punctuation."""
    if len(line) > 90 or line.endswith((".", ";", ",")):
        return False
    return len(line.split()) <= 12


def sectionise(lines):
    sections = {"_intro": []}
    current = "_intro"
    for line in lines:
        low = line.lower()
        matched = None
        if is_heading(line):
            for key, pattern in HEADING_KEYS:
                if re.search(pattern, low):
                    matched = key
                    break
        # A labelled inline field ("Official Website: https://…").
        inline = re.match(r"^([A-Za-z /&()-]{3,40}):\s*(.+)$", line)
        if inline:
            label, value = inline.group(1).lower(), inline.group(2)
            for key, pattern in HEADING_KEYS:
                if re.search(pattern, label):
                    sections.setdefault(key, []).append(value)
                    matched = "__inline__"
                    break
            if matched == "__inline__":
                continue
        if matched:
            current = matched
            sections.setdefault(current, [])
            continue
        if is_heading(line) and current != "_intro":
            # A heading we don't recognise ends the section we were in.
            # Without this, a page's "Reservation" or "Photo Gallery"
            # heading keeps dumping lines into `eligibility`.
            current = "_other"
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


# ------------------------------------------------------------- extraction

NUM_WORD = r"(\d+(?:[.,]\d+)?)"
UNIT = r"\s*(lakhs?|lacs?|crores?|thousand)?"


def to_rupees(amount, unit, monthly=False):
    v = float(str(amount).replace(",", ""))
    u = (unit or "").lower()
    if u.startswith(("lakh", "lac")):
        v *= 100000
    elif u.startswith("crore"):
        v *= 10000000
    elif u.startswith("thousand"):
        v *= 1000
    if monthly:
        v *= 12
    return int(round(v))


def extract_age(text):
    t = text.lower()
    lo = hi = None
    m = re.search(r"\b(?:between\s+)?(\d{1,2})\s*(?:to|-|–|and)\s*(\d{1,2})\s*"
                  r"(?:years?|yrs?)\b", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 0 < a < b <= 100:
            return a, b
    m = re.search(r"\b(?:above|over|minimum(?:\s+age)?(?:\s+of)?|at least|more than)"
                  r"\s*(\d{1,2})\s*(?:years?|yrs?)", t)
    if m:
        lo = int(m.group(1))
    m = re.search(r"\b(?:below|under|less than|up ?to|maximum(?:\s+age)?(?:\s+of)?"
                  r"|not more than)\s*(\d{1,2})\s*(?:years?|yrs?)", t)
    if m:
        hi = int(m.group(1))
    if lo and hi and lo >= hi:
        return None, None
    return (lo if lo and lo < 100 else None), (hi if hi and hi <= 100 else None)


INCOME_CTX = r"(?:annual|yearly|family|household|total)?\s*income[^.\n]{0,60}?"


def extract_income_cap(text):
    t = text.lower()
    patterns = [
        INCOME_CTX + r"(?:less than|below|up ?to|not exceed(?:ing)?|maximum of|"
                     r"under|within)\s*(?:rs\.?|inr|₹)?\s*" + NUM_WORD + UNIT,
        r"(?:rs\.?|inr|₹)\s*" + NUM_WORD + UNIT +
        r"[^.\n]{0,25}(?:or less|per annum|annually)[^.\n]{0,25}income",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if not m:
            continue
        monthly = bool(re.search(r"per month|monthly|a month", t[m.start():m.end() + 30]))
        value = to_rupees(m.group(1), m.group(2), monthly)
        if 10000 <= value <= 5000000:      # reject page numbers and budgets
            return value
    return None


GENDER_RULES = [
    (r"\bonly (?:for )?(?:women|girls|female)|\bwomen only|exclusively for women|"
     r"\bfor (?:the )?(?:women|girl child|girls|widows|unmarried girls)\b|"
     r"\bwoman (?:head|beneficiar)", ["female"]),
    (r"\bonly (?:for )?(?:men|male)\b", ["male"]),
    (r"\btransgender\b", ["transgender"]),
]

CATEGORY_RULES = [
    (r"\bsc\s*/\s*st\b|\bscheduled caste[s]? (?:and|&|/) scheduled tribe", ["sc", "st"]),
    (r"\bscheduled caste\b|\bsc candidates?\b|\bdalit\b", ["sc"]),
    (r"\bscheduled tribe\b|\bst candidates?\b|\btribal\b|\badivasi\b", ["st"]),
    (r"\bobc\b|\bother backward class|\bbackward class\b", ["obc"]),
    (r"\bminorit(?:y|ies)\b", ["minority"]),
    (r"\bews\b|\beconomically weaker section", ["ews"]),
]

OCCUPATION_RULES = [
    (r"\bfarmer|\bagricultur|\bkisan|\bcultivator|\bryot\b", "farmer"),
    (r"\bstudent|\bschool going|\bpursuing (?:a )?(?:course|degree)", "student"),
    (r"\bunemployed|\bjob seeker|\bberozgar", "unemployed"),
    (r"\bweaver|\bhandloom", "weaver"),
    (r"\bfisher(?:man|men|folk)|\bfisheries", "fisherman"),
    (r"\bartisan|\bcraftsm|\bhandicraft", "artisan"),
    (r"\bstreet vendor|\bhawker", "street vendor"),
    (r"\blabour|\blabor|\bdaily wage|\bworkman|\bmazdoor", "labourer"),
    (r"\bconstruction worker|\bbuilding (?:and other )?construction", "construction worker"),
    (r"\bentrepreneur|\bmicro enterprise|\bsmall business|\bmsme\b|\bshop ?keeper", "business"),
    (r"\bself[- ]employ", "self employed"),
    (r"\bdairy|\banimal husbandry|\bcattle", "dairy"),
    (r"\bpensioner|\bretired\b", "retired"),
]

DISABILITY_RE = re.compile(
    r"\bdivyang|\bdisabilit(?:y|ies)\b|\bdifferently[- ]abled|\bhandicapped|"
    r"\bpwd\b|\bphysically challenged|\bvisually impaired|\bhearing impaired", re.I)

RURAL_RE = re.compile(r"\brural\b|\bvillage|\bgram(?:in|\s+panchayat)\b", re.I)
URBAN_RE = re.compile(r"\burban\b|\bcity\b|\bmunicipal|\btown\b", re.I)

URL_RE = re.compile(r"https?://[^\s,;)\]}'\"]+")

CATEGORY_TAGS = [
    ("health", r"health|hospital|medical|treatment|insurance|arogya|disease"),
    ("education", r"school|college|scholarship|student|education|tuition|fee"),
    ("housing", r"hous|awas|awaas|shelter|dwelling|2 ?bhk"),
    ("agriculture", r"farm|crop|agricultur|kisan|irrigat|rythu|soil"),
    ("employment", r"employment|job|rozgar|wage|skill|training|placement"),
    ("women", r"women|girl|mahila|widow|maternity|pregnan|kanya|beti"),
    ("pension", r"pension|old age|senior citizen|vay|vridh"),
    ("credit", r"loan|credit|mudra|interest subvention|margin money"),
    ("disability", r"divyang|disabilit|differently abled|handicap"),
    ("food", r"ration|food|foodgrain|pds\b|anna|nutrition"),
    ("energy", r"electricity|solar|lpg|gas connection|power|bijli|ujjwala"),
    ("water", r"water|jal|tap connection|sanitation|toilet"),
    ("business", r"enterprise|startup|business|entrepreneur|msme|industry"),
    ("social security", r"insurance|bima|social security|provident|welfare fund"),
]


def guess_categories(title_blurb, full_text):
    """Tag from the scheme's name and summary first. Tagging off the whole
    page produced four tags for every scheme, because scraped pages link to
    every other scheme on the site."""
    head, body = title_blurb.lower(), full_text.lower()
    scored = []
    for name, pat in CATEGORY_TAGS:
        score = 3 * len(re.findall(pat, head)) + len(re.findall(pat, body))
        if score >= 4:
            scored.append((score, name))
    scored.sort(reverse=True)
    return [n for _, n in scored[:3]] or ["general"]


def build_eligibility(sections, full_text, state):
    elig_text = " ".join(sections.get("eligibility", []))
    # Fall back to the whole document when there is no eligibility section,
    # but never read gender or category rules out of the whole document —
    # a passing mention of "women" in an objective is not a gender rule.
    scoped = elig_text or ""
    wide = full_text

    e = {}
    lo, hi = extract_age(scoped or wide)
    if lo:
        e["age_min"] = lo
    if hi:
        e["age_max"] = hi

    cap = extract_income_cap(scoped or wide)
    if cap:
        e["income_max"] = cap

    title_blurb = sections.get("_title_blurb", "")
    if isinstance(title_blurb, list):
        title_blurb = " ".join(title_blurb)
    # A rule is only trusted when the eligibility text states it, or the
    # scheme's own name and summary make it the point of the scheme.
    for pat, value in GENDER_RULES:
        if re.search(pat, scoped, re.I) or re.search(pat, title_blurb, re.I):
            e["gender"] = value
            break
    for pat, value in CATEGORY_RULES:
        hits = len(re.findall(pat, scoped, re.I))
        if hits >= 2 or re.search(pat, title_blurb, re.I):
            e["social_category"] = value
            break

    occs = []
    for pat, value in OCCUPATION_RULES:
        if value in occs:
            continue
        if re.search(pat, title_blurb, re.I) or \
                len(re.findall(pat, scoped, re.I)) >= 2:
            occs.append(value)
    if occs and len(occs) <= 3:
        e["occupation"] = occs

    if DISABILITY_RE.search(title_blurb) or (
            scoped and len(DISABILITY_RE.findall(scoped)) >= 2):
        e["disability_required"] = True

    basis = title_blurb + " " + scoped
    rural = bool(RURAL_RE.search(basis))
    urban = bool(URBAN_RE.search(basis))
    if rural != urban:
        e["area"] = ["rural"] if rural else ["urban"]

    if state:
        e["states"] = [state]

    bullets = [b.strip(" -•\t") for b in sections.get("eligibility", [])
               if 25 < len(b) < 260
               and not is_heading(b)
               and not re.search(r"https?://|content source|reference link", b, re.I)]
    if bullets:
        e["other_criteria"] = bullets[:8]
    return e


def title_of(lines):
    for line in lines[:4]:
        if 6 <= len(line) <= 140 and not line.lower().startswith("http"):
            return re.sub(r"\s+", " ", line).strip(" -–:")
    return None


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:70] or "scheme"


def sentences(lines, limit):
    text = " ".join(lines)
    text = re.sub(r"\s+", " ", text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for p in parts:
        if len(out) + len(p) > limit:
            break
        out += (" " if out else "") + p
    return out.strip() or text[:limit].strip()


def parse_file(path, folder):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    lines = clean(raw)
    if len(" ".join(lines)) < 200:
        return None

    title = title_of(lines)
    if not title:
        return None

    sections = sectionise(lines)
    full = " ".join(lines)
    state = FOLDER_TO_STATE.get(folder)

    urls = URL_RE.findall(full)
    gov = next((u for u in urls if re.search(r"\.gov\.in|\.nic\.in|gov\.in", u)), None)

    summary = sentences(sections.get("objective") or sections.get("_intro") or lines, 300)
    benefits = sentences(sections.get("benefits", []), 400)
    title_blurb = title + " " + summary
    sections["_title_blurb"] = title_blurb

    docs = [d.strip(" -•\t") for d in sections.get("documents", [])
            if 4 < len(d) < 120][:10]
    process = [p.strip(" -•\t") for p in sections.get("process", [])
               if 10 < len(p) < 260][:8]
    deadline = sentences(sections.get("deadline", []), 120) or "Not stated in the source"

    return {
        "id": ("%s-%s" % (folder, slug(title)))[:80],
        "name": title,
        "level": "central" if folder == "central" else "state",
        "state": state,
        "ministry": "Government of %s" % state if state else "Government of India",
        "categories": guess_categories(title_blurb, full),
        "summary": summary,
        "benefits": benefits or summary,
        "eligibility": build_eligibility(sections, full, state),
        "documents": docs,
        "process": process,
        "deadline": deadline,
        "official_link": gov or "",
        "source_link": "" if gov else (urls[0] if urls else ""),
        "keywords": " ".join(sorted(set(re.findall(r"[a-z]{4,}", full.lower()))))[:1200],
        "source": "corpus",
        "source_file": os.path.join(folder, os.path.basename(path)),
    }


def normalise_title(t):
    t = re.sub(r"[^a-z0-9 ]", " ", t.lower())
    return " ".join(t.split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="folder holding central/ and the state folders")
    ap.add_argument("-o", "--out", default="data/schemes/dataset.json")
    args = ap.parse_args()

    records, seen_hash, seen_title = [], set(), {}
    stats = Counter()

    for folder in sorted(os.listdir(args.root)):
        fdir = os.path.join(args.root, folder)
        if not os.path.isdir(fdir):
            continue
        for fname in sorted(os.listdir(fdir)):
            if not fname.endswith(".txt"):
                continue
            path = os.path.join(fdir, fname)
            stats["files"] += 1

            digest = hashlib.md5(open(path, "rb").read()).hexdigest()
            if digest in seen_hash:
                stats["dup_exact"] += 1
                continue
            seen_hash.add(digest)

            rec = parse_file(path, folder)
            if not rec:
                stats["too_short"] += 1
                continue

            key = (rec["level"], rec["state"], normalise_title(rec["name"]))
            if key in seen_title:
                # Keep whichever version has more extracted structure.
                old = seen_title[key]
                if len(json.dumps(rec)) > len(json.dumps(old)):
                    records[records.index(old)] = rec
                    seen_title[key] = rec
                stats["dup_title"] += 1
                continue
            seen_title[key] = rec
            records.append(rec)
            stats["kept"] += 1

            e = rec["eligibility"]
            for field in ("age_min", "age_max", "income_max", "gender",
                          "social_category", "occupation", "area"):
                if field in e:
                    stats["rule_" + field] += 1
            if rec["official_link"]:
                stats["has_link"] += 1
            if rec["documents"]:
                stats["has_docs"] += 1

    # Ensure ids are unique after slugging.
    used = Counter()
    for r in records:
        used[r["id"]] += 1
        if used[r["id"]] > 1:
            r["id"] = "%s-%d" % (r["id"], used[r["id"]])

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=1)

    print("Wrote %d schemes to %s" % (len(records), args.out))
    for k in sorted(stats):
        print("  %-22s %d" % (k, stats[k]))


if __name__ == "__main__":
    main()
