"""Rule-based NLU: pulls profile fields out of a sentence the user typed.

This is deliberately dependency-free. It handles the phrasings Indian users
actually type, including Hinglish, lakh/crore amounts and common occupation
words. If an LLM key is configured, app.py will let the LLM refine whatever
this extractor could not find — but the system works fully without it.
"""

import re

from .data import STATES, OCCUPATIONS

# ---------------------------------------------------------------- age

AGE_PATTERNS = [
    # "I am 34", "he is 72", "my father is 72", "she's 19", "age 45"
    r"\b(?:i\s*am|i'm|im|he\s*is|he's|she\s*is|she's|age\s*(?:is)?|aged|umar|vayasu)\s*(\d{1,3})\b",
    r"\b(?:father|mother|husband|wife|son|daughter|brother|sister|parent|"
    r"grandfather|grandmother|dad|mom|uncle|aunt)\b[^.\d]{0,20}(\d{1,3})\b",
    r"\b(\d{1,3})\s*(?:years?|yrs?|saal|year)\s*old\b",
    r"\b(\d{1,3})\s*(?:years?|yrs?)\s*(?:of\s*age)\b",
]

# ---------------------------------------------------------------- income

INCOME_WORDS = r"(?:income|earn(?:ing|s)?|salary|kamata|kamati|make|earns)"
NUM = r"(\d+(?:[.,]\d+)?)"


def _to_rupees(amount, unit, period):
    value = float(str(amount).replace(",", ""))
    unit = (unit or "").lower()
    if unit in ("lakh", "lakhs", "lac", "lacs", "l"):
        value *= 100000
    elif unit in ("crore", "crores", "cr"):
        value *= 10000000
    elif unit in ("thousand", "k"):
        value *= 1000
    period = (period or "").lower()
    if period in ("month", "monthly", "per month", "a month", "pm", "mahina"):
        value *= 12
    return int(round(value))


def extract_income(text):
    t = text.lower()
    unit = r"(lakhs?|lacs?|crores?|cr|thousand|k)?"
    period = r"(?:\s*(?:per|a|every|/)\s*(month|year|annum|monthly|yearly)|\s*(monthly|yearly|pm|pa))?"

    patterns = [
        INCOME_WORDS + r"[^\d]{0,25}(?:rs\.?|rupees|inr|₹)?\s*" + NUM + r"\s*" + unit + period,
        r"(?:rs\.?|rupees|inr|₹)\s*" + NUM + r"\s*" + unit + period + r"[^.]{0,20}" + INCOME_WORDS,
    ]
    # A bare amount counts as income only when a money unit makes it
    # unambiguous ("around 1.2 lakh a year"), never a bare number, so that
    # "he is 72" is not mistaken for an income.
    patterns.append(r"(?:rs\.?|rupees|inr|₹)?\s*" + NUM +
                    r"\s*(lakhs?|lacs?|crores?|cr|thousand|k)\b" + period)

    for pat in patterns:
        m = re.search(pat, t)
        if m:
            groups = list(m.groups())
            amount, u = groups[0], groups[1]
            p = next((g for g in groups[2:] if g), None)
            if not u and not p and float(amount.replace(",", "")) < 100:
                # "income 3" almost certainly means 3 lakh.
                u = "lakh"
            return _to_rupees(amount, u, p)
    return None


# ---------------------------------------------------------------- gender

# Only self-referential words. A relative's gender is not the applicant's:
# "my husband passed away" describes a widow, not a man.
GENDER_HINTS = {
    "female": ["woman", "women", "female", "girl", "lady", "widow",
               "housewife", "aurat", "mahila", "bride", "she", "her"],
    "male": ["man", "male", "boy", "aadmi", "purush", "he", "his"],
    "transgender": ["transgender", "trans", "third gender"],
}

# Phrases that reveal the speaker's own gender indirectly. Checked first.
GENDER_CONTEXT = [
    (r"\bmy husband\b|\bwidow(?:ed)?\b|\bi am pregnant\b|\bmy pregnancy\b", "female"),
    (r"\bmy wife\b|\bwidower\b", "male"),
]

# ---------------------------------------------------------------- category

CATEGORY_HINTS = {
    "sc": ["scheduled caste", " sc ", "sc category", "dalit"],
    "st": ["scheduled tribe", " st ", "st category", "tribal", "adivasi"],
    "obc": ["obc", "other backward", "backward class", " bc ", "ebc"],
    "minority": ["minority", "muslim", "christian", "sikh", "buddhist",
                 "parsi", "jain"],
    "ews": ["ews", "economically weaker"],
    "general": ["general category", "open category"],
}

# ---------------------------------------------------------------- occupation

OCCUPATION_HINTS = {
    "farmer": ["farmer", "farming", "agriculture", "cultivat", "kisan",
               "rythu", "crop", "my land", "paddy", "cotton field"],
    "labourer": ["labour", "labor", "daily wage", "coolie", "mazdoor",
                 "manual work", "construction site"],
    "construction worker": ["construction worker", "mason", "building work"],
    "student": ["student", "studying", "i study", "college", "school",
                "pursuing", "b.tech", "btech", "degree course", "intermediate"],
    "unemployed": ["unemployed", "no job", "without a job", "jobless",
                   "lost my job", "looking for a job", "berozgar", "no work",
                   "cannot find work", "can't find work"],
    "self employed": ["self employed", "self-employed", "own work",
                      "freelance", "work for myself"],
    "business": ["business", "shop owner", "my shop", "enterprise", "startup",
                 "trader", "entrepreneur", "dukaan"],
    "shopkeeper": ["shopkeeper", "kirana", "grocery store"],
    "salaried": ["salaried", "private job", "i work at", "employee",
                 "office job", "company job"],
    "artisan": ["artisan", "craftsman", "craftswoman", "handicraft", "handmade", "craft work"],
    "weaver": ["weaver", "handloom", "weaving", "loom"],
    "fisherman": ["fisherman", "fishing", "fisher", "matsya"],
    "street vendor": ["street vendor", "hawker", "footpath", "push cart",
                      "thela", "roadside stall", "cart", "sell vegetables",
                      "vegetable cart", "fruit cart", "roadside"],
    "domestic worker": ["domestic worker", "house help", "maid", "housemaid"],
    "homemaker": ["housewife", "homemaker", "grihini"],
    "retired": ["retired", "pensioner"],
    "tailor": ["tailor", "tailoring", "stitching", "sewing", "darzi", "boutique"],
    "carpenter": ["carpenter"],
    "blacksmith": ["blacksmith", "lohar"],
    "potter": ["potter", "kumhar"],
    "dairy": ["dairy", "milk business", "cattle", "buffalo"],
}

# ---------------------------------------------------------------- education

EDUCATION_HINTS = {
    "postgraduate": ["m.tech", "mtech", "post graduate", "postgraduate", "msc",
                     "mba", "master", "pg "],
    "engineering": ["b.tech", "btech", "b.e ", "engineering"],
    "undergraduate": ["graduate", "graduation", "degree", "b.sc", "bsc",
                      "b.com", "bcom", "b.a", "bca", "bba", "college"],
    "diploma": ["diploma", "polytechnic"],
    "iti": ["iti "],
    "class 12": ["12th", "class 12", "intermediate", "inter ", "+2", "puc"],
    "class 11": ["11th", "class 11"],
    "class 10": ["10th", "class 10", "ssc ", "matric"],
    "class 9": ["9th", "class 9"],
    "class 8": ["8th", "class 8"],
    "primary": ["primary school"],
    "none": ["never went to school", "not educated", "illiterate",
             "no education"],
}

# ---------------------------------------------------------------- misc

AREA_HINTS = {
    "rural": ["village", "rural", "gaon", "panchayat", "my village"],
    "urban": ["city", "urban", "town", "municipal", "metro"],
}

DISABILITY_HINTS = ["disabled", "disability", "handicap", "divyang",
                    "blind", "deaf", "wheelchair", "amputee", "polio",
                    "physically challenged", "visually impaired"]

NO_DISABILITY_HINTS = ["no disability", "not disabled"]


_HINT_RE_CACHE = {}


def _hint_re(hint):
    """Whole-word matcher. Substring matching is wrong here: 'the roof'
    contains 'he ', and 'village' contains 'n'."""
    if hint not in _HINT_RE_CACHE:
        _HINT_RE_CACHE[hint] = re.compile(
            r"\b" + re.escape(hint.strip()).replace(r"\ ", r"\s+") + r"\b")
    return _HINT_RE_CACHE[hint]


def _first_hint(text, mapping):
    t = text.lower()
    best, best_pos, best_len = None, len(t) + 1, 0
    for key, hints in mapping.items():
        for h in hints:
            m = _hint_re(h).search(t)
            if not m:
                continue
            # Earliest match wins; on a tie the longer, more specific hint wins.
            if m.start() < best_pos or (m.start() == best_pos and len(h) > best_len):
                best, best_pos, best_len = key, m.start(), len(h)
    return best


def extract_state(text):
    t = " " + text.lower() + " "
    aliases = {
        "telangana": "Telangana", "hyderabad": "Telangana",
        "warangal": "Telangana", "karimnagar": "Telangana",
        "andhra": "Andhra Pradesh", "vijayawada": "Andhra Pradesh",
        "visakhapatnam": "Andhra Pradesh", "vizag": "Andhra Pradesh",
        "bangalore": "Karnataka", "bengaluru": "Karnataka",
        "mumbai": "Maharashtra", "pune": "Maharashtra", "nagpur": "Maharashtra",
        "chennai": "Tamil Nadu", "coimbatore": "Tamil Nadu",
        "kolkata": "West Bengal", "bengal": "West Bengal",
        "lucknow": "Uttar Pradesh", "kanpur": "Uttar Pradesh",
        "patna": "Bihar", "jaipur": "Rajasthan", "bhopal": "Madhya Pradesh",
        "indore": "Madhya Pradesh", "ahmedabad": "Gujarat",
        "surat": "Gujarat", "kochi": "Kerala", "trivandrum": "Kerala",
        "bhubaneswar": "Odisha", "guwahati": "Assam",
        "chandigarh": "Chandigarh", "new delhi": "Delhi",
    }
    for state in sorted(STATES, key=len, reverse=True):
        if " " + state.lower() + " " in t:
            return state
    for alias, state in aliases.items():
        if " " + alias + " " in t:
            return state
    return None


def extract_age(text):
    t = text.lower()
    for pat in AGE_PATTERNS:
        m = re.search(pat, t)
        if m:
            age = int(m.group(1))
            if 0 < age < 120:
                return age
    return None


def extract(text, existing=None):
    """Return the profile fields found in `text`, without overwriting
    anything already present in `existing`."""
    existing = existing or {}
    found = {}
    t = text.lower()

    def put(key, value):
        if value not in (None, "") and not existing.get(key):
            found[key] = value

    put("age", extract_age(text))
    put("income", extract_income(text))
    put("state", extract_state(text))
    gender = None
    for pattern, value in GENDER_CONTEXT:
        if re.search(pattern, t):
            gender = value
            break
    put("gender", gender or _first_hint(t, GENDER_HINTS))
    put("social_category", _first_hint(t, CATEGORY_HINTS))
    put("occupation", _first_hint(t, OCCUPATION_HINTS))
    put("education", _first_hint(t, EDUCATION_HINTS))
    put("area", _first_hint(t, AREA_HINTS))

    if any(h in t for h in NO_DISABILITY_HINTS):
        put("disability", False)
    elif any(h in t for h in DISABILITY_HINTS):
        put("disability", True)

    return found


def extract_answer(text, field):
    """Interpret a short reply given to a specific follow-up question."""
    t = text.strip().lower()
    if t in ("skip", "don't know", "dont know", "na", "n/a", "-", "pass"):
        return "__skip__"

    if field == "age":
        m = re.search(r"\b(\d{1,3})\b", t)
        return int(m.group(1)) if m and 0 < int(m.group(1)) < 120 else extract_age(t)
    if field == "income":
        inc = extract_income(t)
        if inc is not None:
            return inc
        if extract_age(t) is not None:
            return None          # "I am 40" is an age, not forty rupees
        m = re.search(NUM + r"\s*(lakhs?|lacs?|crores?|thousand|k)?", t)
        if m:
            value = float(m.group(1).replace(",", ""))
            unit = m.group(2)
            if not unit and value < 1000:
                return None      # too ambiguous to guess
            return _to_rupees(m.group(1), unit,
                              "month" if "month" in t else None)
        return None
    if field == "state":
        return extract_state(t) or (t.title() if t.title() in STATES else None)
    if field == "gender":
        for pattern, value in GENDER_CONTEXT:
            if re.search(pattern, t):
                return value
        return _first_hint(t, GENDER_HINTS) or (
            t if t in ("male", "female", "transgender") else None)
    if field == "social_category":
        if t in ("sc", "st", "obc", "bc", "ews", "general", "minority"):
            return "obc" if t == "bc" else t
        return _first_hint(t, CATEGORY_HINTS)
    if field == "occupation":
        return _first_hint(t, OCCUPATION_HINTS) or (
            t if t in OCCUPATIONS else None)
    if field == "education":
        return _first_hint(t, EDUCATION_HINTS)
    if field == "area":
        return _first_hint(t, AREA_HINTS)
    if field == "disability":
        # Whole words only: "village" must not be read as "n" for no.
        words = set(re.findall(r"[a-z']+", t))
        if words & {"yes", "y", "haan", "ha", "hai", "yeah", "yep", "true"}:
            return True
        if words & {"no", "n", "nope", "nahi", "none", "false"}:
            return False
        if any(h in t for h in DISABILITY_HINTS):
            return True
    return None
