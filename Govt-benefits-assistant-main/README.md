# AI-Powered Government Benefits Assistant

Finds the central and state welfare schemes a citizen is eligible for, in two
ways: a structured profile form, and a chat where the user describes their
problem in plain language and the assistant asks follow-up questions before
recommending.

## Running it

```bash
pip install flask
python app.py
```

Open http://127.0.0.1:5000

Flask is the only dependency. Everything else — the eligibility engine, the
semantic search, the language handling — is written in the Python standard
library, so there is nothing to install on a lab machine and nothing to break
on a different Python version.

## Deploying it

See `DEPLOY.md`. Short version: push to GitHub, deploy the blueprint on
Render's free tier, set `SITE_URL`, and submit `/sitemap.xml` to Google
Search Console. The app serves 1,294 crawlable scheme pages under
`/scheme/<id>` plus state indexes, which is what makes it findable — a search
engine cannot fill in the form or run the chat.

## How it is put together

```
app.py                  Flask server + JSON API
engine/
  data.py               loads and normalises every dataset file
  search.py             BM25 retrieval with bigrams and synonym expansion
  matcher.py            eligibility rule engine + tiered ranking
  nlu.py                pulls age, income, state, occupation etc. out of free text
  chat.py               the conversational agent (slot filling)
  i18n.py, i18n_extra.py  UI text in 23 languages
data/schemes/*.json     the dataset
tools/ingest.py         converts the scraped .txt corpus into scheme records
tools/evaluate.py       accuracy harness
templates/, static/     the interface
DEPLOY.md               free hosting and search indexing
render.yaml, Procfile   deployment config
```

### The eligibility engine

Every scheme carries a machine-readable `eligibility` block. For each scheme
the engine runs the criteria one at a time against the user's profile and
collects two lists: reasons the user qualifies, and blockers that disqualify
them. One blocker is enough to drop the scheme.

The reasons are what the interface shows under "Why you qualify", so every
recommendation can be traced to a rule rather than a model's opinion. A
result is marked **Eligible** when the profile answered every criterion the
scheme cares about, and **Likely eligible** when a criterion exists but the
user left that field blank.

### Verified rules vs the corpus

The dataset has two kinds of record and the app never blurs them.

**Curated** records (81) carry hand-written, machine-checkable eligibility
rules. These are the only records that can produce an *Eligible* verdict,
because they are the only ones whose criteria the engine actually checked
against the profile.

**Corpus** records (1,213) come from the scraped `.txt` archive. Most are
readable scheme descriptions with no reliably extractable criteria — a page
that says "for the welfare of poor families" cannot be turned into a rule.
Those are marked **Criteria not verified**, ranked in their own tier below
the checked matches, shown only when the user's own words point at them, and
rendered in a separate section with a note telling the user to confirm on the
official page.

The alternative — treating a record with no rules as matching everyone —
would have returned several hundred "eligible" schemes for every profile.
That looks impressive in a demo and is useless to a citizen.

### The search

`search.py` ranks free text with BM25 rather than TF-IDF cosine, over
unigrams and bigrams, with query terms expanded through a domain thesaurus
before scoring. The thesaurus exists because citizens do not use scheme
vocabulary: someone types "I can't pay the hospital bill", never "tertiary
care empanelment". Expanded terms are weighted at 0.45 against 1.0 for what
the user actually typed.

Queries run in about 2 ms over the full 1,294-scheme dataset; startup builds
the index in about a quarter of a second. Still no dependencies.

### The chat agent

`chat.py` keeps a session with a profile, a list of fields already asked, and
a rolling query. Each turn it:

1. reads the reply against the field it last asked about,
2. scans the whole message for anything else volunteered,
3. picks the next most useful missing field — the order depends on the
   detected topic, so a health problem is asked about age and state, while a
   business problem is asked about category and gender,
4. stops asking once it has four useful fields or has asked four questions,
   and recommends.

It never asks for the same field twice, and "skip" is always accepted.

## Accuracy

`python tools/evaluate.py` runs 24 scenarios worded the way a citizen would
describe the problem, each labelled with the schemes a correct system should
surface, plus 16 profile/scheme pairs that test the rule engine directly.

```
Search index alone
  TF-IDF (baseline)    Recall@5  66.7%   Recall@10  83.3%   MRR 0.435
  BM25 + synonyms      Recall@5  83.3%   Recall@10  95.8%   MRR 0.610

Full pipeline (search + eligibility engine + tiers)
  TF-IDF (baseline)    Recall@5  95.8%   Recall@10  95.8%   MRR 0.938
  BM25 + synonyms      Recall@5 100.0%   Recall@10 100.0%   MRR 0.924

Eligibility rules     16/16 correct (100%)
```

The first block isolates retrieval; the second shows what the user sees once
the eligibility engine and tier ordering are applied. The eligibility block
must stay at 100% — a failure there is a correctness bug, not a ranking
preference.

Add your own cases to `RETRIEVAL_CASES` and `ELIGIBILITY_CASES` in
`tools/evaluate.py`. Two rules worth keeping: write the query the way a
citizen would say it, not the way the scheme is titled, and never add a
synonym that names a specific scheme — that inflates the score without
improving the system.

## Ingesting the scraped corpus

```bash
python tools/ingest.py /path/to/archive-folder -o data/schemes/dataset.json
```

The archive is one folder per state plus `central`, holding loose `.txt`
files scraped from scheme websites in 2020. `ingest.py`:

1. strips advertising script tags, navigation blobs and table-of-contents
   runs;
2. drops 80 byte-identical duplicates and near-duplicate articles, keeping
   whichever copy yielded more structure;
3. splits each page into sections by heading, where an *unrecognised* heading
   closes the current section — without that, a page's "Reservation" heading
   kept dumping paragraphs into `eligibility`;
4. reads rules out of those sections, requiring the evidence to be in the
   eligibility text or in the scheme's own name and summary. A passing
   mention of "women" in an objective is not a gender rule.

From 1,524 files it produces 1,213 records: 228 too short to be a scheme
page, 80 exact duplicates, 3 duplicate titles. Rules were extractable for
roughly 370 occupations, 127 areas, 118 age floors, 60 categories and 54
income ceilings — which is why the tier system above exists. Anything the
parser could not read confidently stays as free text under `other_criteria`
and is shown to the user rather than guessed at.

Re-run it whenever you get a fresher corpus; nothing else needs changing.

## Swapping in your own dataset

Drop any number of `.json` files into `data/schemes/`. They are all merged at
startup; if two entries share an `id`, the file loaded later wins. Each file
is a JSON list of objects in this shape — every key except `name` is
optional, and missing keys get safe defaults:

```json
{
  "id": "unique-slug",
  "name": "Scheme name",
  "level": "central",
  "state": null,
  "ministry": "Implementing ministry or department",
  "categories": ["health", "insurance"],
  "summary": "One or two lines a citizen can understand.",
  "benefits": "What the applicant actually receives.",
  "eligibility": {
    "age_min": 18, "age_max": 40,
    "income_max": 250000,
    "gender": ["female"],
    "occupation": ["farmer"],
    "education": ["class 12"],
    "social_category": ["sc", "st"],
    "area": ["rural"],
    "states": ["Telangana"],
    "disability_required": false,
    "category_or_gender": false,
    "other_criteria": ["Free-text conditions the engine shows but cannot check"]
  },
  "documents": ["Aadhaar card"],
  "process": ["Step one", "Step two"],
  "deadline": "Open round the year",
  "official_link": "https://example.gov.in",
  "keywords": "extra words that should match this scheme in chat"
}
```

Notes on the fields:

- Omit a key, or set it to `["any"]` / `null`, and the engine stops checking
  it. A scheme with an empty `eligibility` block matches everyone.
- `states` is only needed for a central scheme that runs in some states. A
  scheme with `"level": "state"` and a `state` value restricts itself.
- `category_or_gender: true` means either condition is enough — Stand-Up
  India, for instance, is open to SC/ST applicants *or* women.
- `other_criteria` is for conditions that cannot be expressed as a rule
  (land ownership, exclusion of income-tax payers). They are shown to the
  user but not enforced.
- `keywords` is the cheapest way to improve chat matching. Add the words a
  citizen would actually use, including in transliteration.

Values are matched case-insensitively. Vocabularies for occupation,
education and social category live in `engine/data.py`; add to those lists if
your dataset uses terms that are not there.

## Languages

The interface ships in all 22 languages of the Eighth Schedule plus English:
Assamese, Bengali, Bodo, Dogri, Gujarati, Hindi, Kannada, Kashmiri, Konkani,
Maithili, Malayalam, Manipuri, Marathi, Nepali, Odia, Punjabi, Sanskrit,
Santali, Sindhi, Tamil, Telugu and Urdu. Urdu, Kashmiri and Sindhi render
right-to-left.

The widely-used languages should read naturally. Bodo, Manipuri, Kashmiri,
Santali and Sanskrit have far less reference material behind them and the
phrasing in those five is worth checking with a speaker before you put this
in front of real users — every key is present, so a correction is a one-line
edit in `engine/i18n_extra.py`.

To add another language, copy the `"en"` block in `engine/i18n.py`, translate
the values, and add the code and label to `LANGUAGES`. Right-to-left scripts
go in the `RTL` set.

Scheme content itself stays in whatever language the dataset is written in.
To translate scheme text too, add per-language dataset files (a
`schemes_hi.json` with the same `id` values) and pick the file matching the
requested language in `load_schemes`.

## The API

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/match` | POST | Profile in, ranked schemes out. Optional `query` for free text. |
| `/api/chat` | POST | One conversation turn. Send `message` and the `session_id` from the previous reply. |
| `/api/chat/reset` | POST | Clear a session. |
| `/api/schemes` | GET | Browse the dataset. Filter with `?level=` and `?state=`. |
| `/api/stats` | GET | Dataset counts. |

Chat sessions are kept in a dictionary in `app.py`. For a deployment that
runs more than one worker, move `SESSIONS` to Redis or a database table.

## About the data

`central.json` and `state.json` hold 81 schemes with hand-written rules.
`dataset.json` holds 1,213 records built from the scraped archive.

Two warnings worth repeating in the report:

- **The corpus was scraped in 2020.** Amounts, income ceilings, deadlines and
  in several cases the schemes themselves have changed since. It is a good
  corpus for demonstrating retrieval and for breadth of coverage; it is not a
  current source of truth.
- **Benefit figures drift fast** even in the curated records, and several
  entries say so in their own text. The official link on each card is the
  authority, which is why every card carries one.
