# Deploying this for free, and getting it found

Two separate problems. Hosting is easy; being findable in search is the part
that needs the app to be built a certain way, which is why the crawlable
pages described below exist.

---

## 1. Put it online

The app is a plain Flask WSGI application with one dependency at runtime
(`flask`) plus `gunicorn` to serve it. No database, no build step, no
background worker. That makes it deployable on essentially every free tier.

### Render — recommended

Free web service, HTTPS included, deploys on every push to GitHub.
`render.yaml` in this folder already describes the service, so Render reads
it and you barely have to fill anything in.

1. Push this folder to a **public** GitHub repository.
2. Sign in at render.com with GitHub, choose **New → Blueprint**, pick the
   repo. Render reads `render.yaml`.
3. First deploy takes a few minutes. You get
   `https://<name>.onrender.com`.
4. Go to the service's **Environment** tab and set `SITE_URL` to that exact
   URL, then redeploy. This matters — `sitemap.xml` and the canonical tags
   need the absolute domain or search engines discount them.

**The one real catch:** a free Render service sleeps after 15 minutes with no
traffic, and the next visitor waits roughly 30–50 seconds for it to wake.
That is survivable for a project demo and poor for a public service. Do not
solve it with a cron job that pings the service every ten minutes — that is
circumventing the limit the free tier is built on, and Render can suspend the
account for it. Either accept the cold start, or use the next option.

### PythonAnywhere — if you want it always awake

Free tier, Python-native, and it does **not** sleep. The trade-offs are 100
CPU-seconds per day and no custom domain, so you live at
`yourname.pythonanywhere.com`.

100 CPU-seconds sounds tiny but suits this app: startup builds the search
index in about 0.25s and a query costs about 2.5ms, so the cap is roughly
tens of thousands of searches a day. You will hit the disk or bandwidth
limits long before the CPU one.

1. Sign up, open a **Bash console**, `git clone` your repo.
2. `mkvirtualenv --python=python3.12 gba && pip install -r requirements.txt`
3. **Web** tab → *Add a new web app* → Manual configuration → Python 3.12.
4. Point *Source code* at the repo folder, set the virtualenv path, and edit
   the WSGI file to:

   ```python
   import sys
   path = '/home/<yourname>/govt-benefits-assistant'
   if path not in sys.path:
       sys.path.insert(0, path)
   from app import app as application
   ```
5. Add `SITE_URL=https://<yourname>.pythonanywhere.com` in the Web tab's
   environment variables, then **Reload**.

Note the free plan blocks outbound network calls. This app makes none, so it
is unaffected — but it does rule out adding a translation API later.

### Others worth knowing

- **Hugging Face Spaces** — free, stays warm, public by default. Good if you
  later add a model.
- **Fly.io** — no longer has a usable free tier for new accounts; it asks for
  a card and bills from the start.
- **Vercel / Netlify** — built for static sites and serverless functions. A
  long-lived Flask process with an in-memory index is the wrong shape, and
  Vercel's Hobby plan forbids anything with a business purpose.

---

## 2. Make it findable in search

A search engine cannot fill in your form and cannot run the chat. If the site
were only the single-page app, Google would index exactly one page saying
"Find the schemes you are eligible for" — and nobody searches that.

So the app also serves plain, server-rendered pages:

| Route | What it is |
|---|---|
| `/scheme/<id>` | One page per scheme — 1,294 of them — with benefits, criteria, documents, process and the official link |
| `/schemes` | Hub linking every state |
| `/schemes/<state>`, `/schemes/central` | Every scheme in that state, so a crawler reaches each page by following links |
| `/sitemap.xml` | All 1,325 URLs |
| `/robots.txt` | Allows everything except `/api/` |

Each scheme page carries a unique `<title>` and meta description, a canonical
link, and `GovernmentService` structured data (schema.org JSON-LD) naming the
provider and the area served. The home page declares `hreflang` for all 23
languages.

That is the whole point: people do not search for your project, they search
for *"PM Awas Yojana eligibility"* or *"Telangana Kalyana Lakshmi documents
required"*. Each of those queries now has a page on your site that answers it
directly and links onward to the recommender.

### After deploying

1. **Google Search Console** — add the property, verify with the HTML meta
   tag or DNS, then submit `https://<your-url>/sitemap.xml` under *Sitemaps*.
2. **Bing Webmaster Tools** — same, and it imports straight from Search
   Console.
3. Use *URL Inspection* on a handful of scheme pages and request indexing to
   prime the crawl.

Realistically: expect a few days before anything is indexed and weeks before
it ranks for anything competitive. A new domain with no inbound links starts
from nothing. Linking it from your college project page, your GitHub README
and your LinkedIn gives the crawler a reason to come back.

### If you get a custom domain

A `.in` domain is cheap and `github.com/education/pack` sometimes includes a
free one for students. Point it at Render in the service's **Custom Domain**
tab (free plan allows this), update `SITE_URL`, redeploy, and add the new
domain as a separate property in Search Console.

---

## 3. Before it is genuinely public

Right now this is sized for a demo. Three things to change if real citizens
will use it:

- **Chat sessions live in a dict in `app.py`.** With `--workers 2` a user's
  follow-up answer can land on the other worker, which has no memory of the
  conversation. For a demo, run `--workers 1`. For real traffic, move
  `SESSIONS` into Redis or a small table.
- **The corpus data is from 2020.** Every scheme page shows it alongside a
  link to the official site, which is the honest way to publish it, but say
  so in the footer if strangers will read it.
- **No rate limiting.** Add `flask-limiter` on `/api/chat` before you post
  the link anywhere public.
