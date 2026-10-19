"""AI-Powered Government Benefits Assistant — Flask application.

Run:
    pip install flask
    python app.py
    open http://127.0.0.1:5000
"""

import os
import re
import uuid

from flask import (Flask, Response, abort, jsonify, redirect,
                   render_template, request, url_for)

from engine import chat as chat_engine
from engine import i18n
from engine.data import (EDUCATION_LEVELS, OCCUPATIONS, SOCIAL_CATEGORIES,
                         STATES, dataset_stats, load_schemes)
from engine.matcher import SemanticIndex, recommend

app = Flask(__name__)

SCHEMES = load_schemes()
INDEX = SemanticIndex(SCHEMES)
SESSIONS = {}          # in-memory chat sessions: swap for Redis/DB in prod
BY_ID = {s["id"]: s for s in SCHEMES}

# Set SITE_URL on the host so sitemap.xml and the canonical tags carry the
# real domain. Without it the app still works; search engines just get
# relative links, which they handle less well.
SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")


def absolute(path):
    return (SITE_URL + path) if SITE_URL else path

print("Loaded %d schemes (%d central, %d state)"
      % (len(SCHEMES),
         sum(1 for s in SCHEMES if s["level"] == "central"),
         sum(1 for s in SCHEMES if s["level"] == "state")))


def clean_profile(raw):
    """Coerce whatever the client sent into a well-typed profile."""
    p = {}
    for key in ("gender", "occupation", "education", "social_category",
                "area", "state"):
        val = (raw.get(key) or "").strip()
        if val:
            p[key] = val if key == "state" else val.lower()

    for key in ("age", "income"):
        val = raw.get(key)
        if val not in (None, "", "null"):
            try:
                p[key] = int(float(str(val).replace(",", "")))
            except (TypeError, ValueError):
                pass

    dis = raw.get("disability")
    if dis in (True, "true", "yes", "1", 1):
        p["disability"] = True
    elif dis in (False, "false", "no", "0", 0):
        p["disability"] = False
    return p


def serialise(result):
    s = result["scheme"]
    return {
        "id": s["id"],
        "name": s["name"],
        "level": s["level"],
        "state": s["state"],
        "ministry": s["ministry"],
        "categories": s["categories"],
        "summary": s["summary"],
        "benefits": s["benefits"],
        "documents": s["documents"],
        "process": s["process"],
        "deadline": s["deadline"],
        "link": s["official_link"],
        "source_link": s.get("source_link", ""),
        "verified": bool(s.get("verified")),
        "other_criteria": s["eligibility"]["other_criteria"],
        "status": result["status"],
        "reasons": result["reasons"],
        "blockers": result.get("blockers", []),
        "score": result["score"],
    }


# --------------------------------------------------------------------- pages

@app.route("/")
def index():
    lang = request.args.get("lang", "en")
    return render_template(
        "index.html",
        t=i18n.strings(lang),
        lang=lang,
        rtl=lang in i18n.RTL,
        languages=i18n.LANGUAGES,
        states=STATES,
        occupations=OCCUPATIONS,
        categories=SOCIAL_CATEGORIES,
        education=EDUCATION_LEVELS,
        stats=dataset_stats(SCHEMES),
    )


def state_slug(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


@app.route("/scheme/<scheme_id>")
def scheme_page(scheme_id):
    """One crawlable page per scheme.

    This is what makes the project findable. A search engine cannot index a
    form, and it cannot run the chat — but it can index 1,294 pages that each
    answer "am I eligible for <scheme>", which is the question people
    actually type into Google.
    """
    scheme = BY_ID.get(scheme_id)
    if not scheme:
        abort(404)
    lang = request.args.get("lang", "en")

    related = [s for s in SCHEMES
               if s["id"] != scheme["id"]
               and (set(s["categories"]) & set(scheme["categories"]))
               and (s["state"] == scheme["state"] or s["level"] == "central")][:6]

    return render_template(
        "scheme.html", t=i18n.strings(lang), lang=lang, rtl=lang in i18n.RTL,
        languages=i18n.LANGUAGES, scheme=scheme, related=related,
        canonical=absolute(url_for("scheme_page", scheme_id=scheme["id"])),
    )


@app.route("/schemes")
@app.route("/schemes/<state>")
def browse(state=None):
    """A plain index page, so every scheme page is reachable by a crawler
    following links rather than only through the sitemap."""
    lang = request.args.get("lang", "en")
    slugs = {state_slug(s): s for s in STATES}
    chosen = slugs.get((state or "").lower())
    if state and not chosen and state != "central":
        abort(404)

    # The unfiltered index would be a 280 KB page. Crawlers and phones both
    # do better with a hub that links the state pages.
    if state is None:
        return render_template(
            "browse.html", t=i18n.strings(lang), lang=lang,
            rtl=lang in i18n.RTL, languages=i18n.LANGUAGES, schemes=[],
            heading="Government schemes by state",
            states=[(s, state_slug(s)) for s in sorted(
                {s["state"] for s in SCHEMES if s["state"]})],
            canonical=absolute("/schemes"))

    if state == "central":
        listed = [s for s in SCHEMES if s["level"] == "central"]
        heading = "Central government schemes"
    elif chosen:
        listed = [s for s in SCHEMES if s["state"] == chosen]
        heading = "Government schemes in %s" % chosen
    else:
        listed = SCHEMES
        heading = "All government schemes"

    listed = sorted(listed, key=lambda s: s["name"])
    return render_template(
        "browse.html", t=i18n.strings(lang), lang=lang, rtl=lang in i18n.RTL,
        languages=i18n.LANGUAGES, schemes=listed, heading=heading,
        states=[(s, state_slug(s)) for s in sorted(
            {s["state"] for s in SCHEMES if s["state"]})],
        canonical=absolute("/schemes" + ("/" + state if state else "")),
    )


@app.route("/robots.txt")
def robots():
    lines = ["User-agent: *", "Allow: /", "Disallow: /api/"]
    if SITE_URL:
        lines.append("Sitemap: %s/sitemap.xml" % SITE_URL)
    return Response("\n".join(lines) + "\n", mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    urls = [absolute("/"), absolute("/schemes")]
    urls += [absolute("/schemes/central")]
    urls += [absolute("/schemes/" + state_slug(s))
             for s in sorted({s["state"] for s in SCHEMES if s["state"]})]
    urls += [absolute("/scheme/" + s["id"]) for s in SCHEMES]

    body = ["<?xml version='1.0' encoding='UTF-8'?>",
            "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"]
    for u in urls:
        body.append("<url><loc>%s</loc></url>" % u)
    body.append("</urlset>")
    return Response("".join(body), mimetype="application/xml")


@app.errorhandler(404)
def not_found(_):
    return redirect(url_for("index"))


# ----------------------------------------------------------------------- api

@app.route("/api/schemes")
def api_schemes():
    """Browse the whole dataset, with optional filters."""
    level = request.args.get("level")
    state = request.args.get("state")
    out = []
    for s in SCHEMES:
        if level and s["level"] != level:
            continue
        if state and s["state"] and s["state"].lower() != state.lower():
            continue
        out.append(serialise({"scheme": s, "status": "eligible",
                              "reasons": [], "score": 0}))
    return jsonify({"count": len(out), "schemes": out})


@app.route("/api/match", methods=["POST"])
def api_match():
    """Structured profile -> ranked schemes."""
    payload = request.get_json(force=True, silent=True) or {}
    profile = clean_profile(payload)
    query = (payload.get("query") or "").strip()

    results, near = recommend(SCHEMES, INDEX, profile, query=query,
                              limit=40, include_near_misses=True)
    return jsonify({
        "profile": profile,
        "count": len(results),
        "results": [serialise(r) for r in results],
        "near_misses": [serialise(r) for r in near],
    })


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """One turn of the conversation."""
    payload = request.get_json(force=True, silent=True) or {}
    sid = payload.get("session_id")
    message = payload.get("message", "")

    if not sid or sid not in SESSIONS:
        sid = uuid.uuid4().hex
        SESSIONS[sid] = chat_engine.new_session()

    out = chat_engine.step(SESSIONS[sid], message, SCHEMES, INDEX)
    return jsonify({
        "session_id": sid,
        "reply": out["reply"],
        "field": out["field"],
        "profile": out["profile"],
        "done": out["done"],
        "results": [serialise(r) for r in (out["results"] or [])],
    })


@app.route("/api/chat/reset", methods=["POST"])
def api_chat_reset():
    sid = (request.get_json(force=True, silent=True) or {}).get("session_id")
    SESSIONS.pop(sid, None)
    return jsonify({"ok": True})


@app.route("/api/stats")
def api_stats():
    return jsonify(dataset_stats(SCHEMES))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # 0.0.0.0 so the same file works locally and on a PaaS container.
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0" if not debug else "127.0.0.1", port=port, debug=debug)
