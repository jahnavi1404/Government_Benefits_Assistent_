"""The chat agent.

Flow: the user describes a problem in their own words. The agent extracts
whatever profile fields it can, decides which missing field would most change
the answer, asks for exactly that one, and stops asking once it has enough to
give a trustworthy list. Then it recommends.

State lives in a plain dict so the caller can keep it in a session, a DB row,
or anywhere else.
"""

from . import nlu
from .matcher import recommend

MAX_QUESTIONS = 4

QUESTIONS = {
    "state": "Which state do you live in? Some of the best schemes are run by state governments, so this changes the list a lot.",
    "age": "How old is the person who needs help? Many schemes have age limits.",
    "gender": "Is the applicant male, female or transgender? Several schemes are reserved for women.",
    "income": "Roughly what is the family's total annual income? An approximate figure is fine, for example 1.5 lakh.",
    "occupation": "What does the applicant do for a living? For example farmer, daily wage worker, student, shopkeeper, or currently unemployed.",
    "social_category": "Which social category does the family fall under: general, OBC/BC, SC, ST, EWS or minority? This decides eligibility for a lot of schemes.",
    "area": "Is the home in a village (rural) or in a town or city (urban)?",
    "education": "What is the highest class or course the applicant has completed?",
    "disability": "Does the applicant have a certified disability? Yes or no.",
}

# Which fields matter most, given what the user seems to be asking about.
TOPIC_PRIORITY = {
    "health":    ["state", "age", "income", "disability"],
    "education": ["state", "age", "social_category", "income", "education", "gender"],
    "housing":   ["state", "area", "income", "social_category"],
    "job":       ["state", "age", "education", "occupation", "gender"],
    "business":  ["state", "age", "social_category", "gender", "occupation"],
    "farming":   ["state", "occupation", "age", "area"],
    "women":     ["state", "age", "income", "area"],
    "pension":   ["state", "age", "gender", "income", "disability"],
    "food":      ["state", "area", "income"],
    "general":   ["state", "age", "gender", "income", "occupation", "social_category"],
}

TOPIC_WORDS = {
    "health":    ["hospital", "treatment", "surgery", "medical", "illness", "sick",
                  "disease", "operation", "cancer", "medicine", "health", "doctor"],
    "education": ["school", "college", "fees", "scholarship", "study", "student",
                  "education", "course", "tuition", "admission", "degree", "books"],
    "housing":   ["house", "home", "rent", "shelter", "roof", "hut", "kutcha",
                  "housing", "flat", "construct"],
    "job":       ["job", "work", "employment", "unemployed", "salary", "hiring",
                  "internship", "placement", "training", "skill"],
    "business":  ["business", "loan", "shop", "startup", "enterprise", "capital",
                  "machine", "stall", "vendor"],
    "farming":   ["farm", "crop", "land", "seed", "irrigation", "harvest",
                  "tractor", "fertiliser", "fertilizer", "cattle", "agriculture"],
    "women":     ["woman", "women", "girl", "daughter", "marriage", "pregnant",
                  "widow", "mother", "maternity"],
    "pension":   ["pension", "old age", "retire", "elderly", "senior citizen"],
    "food":      ["ration", "food", "grain", "rice", "hungry", "meals"],
}


def detect_topic(text):
    t = (text or "").lower()
    best, best_hits = "general", 0
    for topic, words in TOPIC_WORDS.items():
        hits = sum(1 for w in words if w in t)
        if hits > best_hits:
            best, best_hits = topic, hits
    return best


def new_session():
    return {
        "profile": {},
        "asked": [],
        "pending": None,      # field we just asked about
        "topic": "general",
        "query": "",
        "turns": 0,
        "done": False,
    }


def _next_field(session):
    order = TOPIC_PRIORITY.get(session["topic"], TOPIC_PRIORITY["general"])
    profile = session["profile"]
    for field in order:
        if profile.get(field) in (None, "") and field not in session["asked"]:
            return field
    return None


def _enough(session):
    """Enough information to give a list worth trusting?"""
    p = session["profile"]
    filled = sum(1 for k in ("state", "age", "gender", "income", "occupation",
                             "social_category", "area", "education")
                 if p.get(k) not in (None, ""))
    if len(session["asked"]) >= MAX_QUESTIONS:
        return True
    # State decides which half of the dataset is even applicable, so always
    # ask for it before answering, however much else the user volunteered.
    if not p.get("state") and "state" not in session["asked"]:
        return False
    return filled >= 4


def step(session, message, schemes, index):
    """Advance the conversation by one user message.

    Returns a dict: {reply, questions_asked, profile, results (or None), done}
    """
    session["turns"] += 1
    message = (message or "").strip()

    # If we asked about a specific field, try to read the answer as that field.
    if session.get("pending"):
        field = session["pending"]
        value = nlu.extract_answer(message, field)
        if value == "__skip__":
            session["profile"][field] = None
        elif value is not None:
            session["profile"][field] = value
        session["pending"] = None

    # Always also scan the message for anything else the user volunteered.
    found = nlu.extract(message, session["profile"])
    session["profile"].update(found)

    # Keep a rolling free-text query for the semantic search.
    if len(message.split()) > 3:
        session["query"] = (session["query"] + " " + message).strip()[-600:]
    if session["turns"] == 1 or session["topic"] == "general":
        session["topic"] = detect_topic(session["query"] or message)

    # Ask one more question, or answer.
    if not _enough(session):
        field = _next_field(session)
        if field:
            session["asked"].append(field)
            session["pending"] = field
            ack = _acknowledge(found, session["turns"])
            return {
                "reply": (ack + " " if ack else "") + QUESTIONS[field],
                "field": field,
                "profile": session["profile"],
                "results": None,
                "done": False,
            }

    session["done"] = True
    results = recommend(schemes, index, session["profile"],
                        query=session["query"], limit=12)
    return {
        "reply": _summary(session, results),
        "field": None,
        "profile": session["profile"],
        "results": results,
        "done": True,
    }


def _acknowledge(found, turn):
    if turn == 1:
        return "Thanks for explaining."
    if not found:
        return "Got it."
    labels = {
        "state": "state", "age": "age", "income": "income",
        "occupation": "occupation", "gender": "gender",
        "social_category": "category", "area": "area",
        "education": "education", "disability": "disability status",
    }
    names = [labels[k] for k in found if k in labels]
    if not names:
        return "Got it."
    return "Noted your " + ", ".join(names) + "."


def _summary(session, results):
    p = session["profile"]
    bits = []
    if p.get("gender") and p.get("age"):
        bits.append("a %s applicant aged %s" % (p["gender"], p["age"]))
    elif p.get("age"):
        bits.append("an applicant aged %s" % p["age"])
    elif p.get("gender"):
        bits.append("a %s applicant" % p["gender"])
    if p.get("occupation"):
        occ = p["occupation"]
        bits.append("currently unemployed" if occ == "unemployed"
                    else "working as a %s" % occ)
    if p.get("area"):
        bits.append("in a %s area" % p["area"])
    if p.get("state"):
        bits.append("in %s" % p["state"])
    who = ", ".join(bits) if bits else "what you have told me"

    if not results:
        return ("I could not find a scheme in the dataset that matches %s. "
                "Try describing the problem differently, or use the profile "
                "form so I can check every criterion." % who)

    n_central = sum(1 for r in results if r["scheme"]["level"] == "central")
    n_state = len(results) - n_central
    parts = ["Based on %s, here is what you look eligible for." % who]
    if n_state:
        parts.append("%d central and %d state scheme%s are listed below, "
                     "strongest match first."
                     % (n_central, n_state, "s" if n_state != 1 else ""))
    else:
        parts.append("%d scheme%s listed below, strongest match first."
                     % (n_central, "s" if n_central != 1 else ""))
    parts.append("Open any card to see why you qualify, the documents you "
                 "need and the official link to apply.")
    return " ".join(parts)
