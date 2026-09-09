---
name: company-research
description: Produce a multi-lens due-diligence report on a company — combining a research analyst's view (market, competitors, leadership, news), a quant's view (financial metrics, growth/risk data), a senior full-stack engineer's view (tech stack, engineering practices, product quality signals), and a security researcher's view (passive/OSINT-only exposure and hygiene signals) — and turn every finding into a concrete, pitchable "problem + suggested fix." Use this whenever the user wants to research, analyze, size up, do due diligence on, or find opportunities/problems/weaknesses in a company or organization for purposes like a consulting pitch, cold outreach, investment research, competitive analysis, or a pre-sales brief. Also trigger on requests to find a company's "exploits," "vulnerabilities," "weaknesses," or "problems" — this skill handles that safely as passive, defensive OSINT and reframes it as a fixable-opportunity list, never as an attack plan.
---

# Company Research Report

You are producing one report that looks at a company through four professional
lenses, and every section ends in the same place: a list of concrete problems
or opportunities the user could bring to the company (e.g. as a consulting
pitch, sales angle, or investment thesis), each paired with a suggested fix.

This is **outward-facing research using public information only** — think
"sharp analyst doing homework before a meeting," not "operating on the
company's systems." Read the Guardrails section before you touch the security
lens; it is the part most likely to be misread as an invitation to do
something intrusive, and it explicitly isn't.

## 1. Get the essentials from the user

Before researching, make sure you know:
- **Company name and/or domain.** If ambiguous (common name, multiple
  entities), confirm which one.
- **Why they want the report**, if not obvious (pitching consulting/dev
  services, evaluating as an investment, competitive research, sales
  prospecting, curiosity). This shapes emphasis — e.g. an investment thesis
  leans harder on the quant section, a dev-services pitch leans on the
  engineering section — but always produce all four lenses unless the user
  explicitly asks you to drop one.
- **Any scope limits** — e.g. "public company only, skip the security
  section" or "just the tech stack." Respect them.

Don't block on this if the request is already clear (name + obvious intent);
just ask if something is genuinely ambiguous.

## 2. Research methodology, lens by lens

Use `WebSearch` and `WebFetch` throughout. Cite what you find — every claim in
the final report should be traceable to a source (a URL, filing, or "inferred
from X"). Where you can't verify something, say so and mark it a hypothesis,
not a fact.

### Lens 1 — Research Analyst (business & market)

Goal: understand what the company does, who it competes with, and where the
narrative is heading.

Look for:
- Official "About," leadership/team, and investor-relations pages
- Recent news and press releases (last 6–12 months) — product launches,
  layoffs, executive departures, lawsuits, regulatory action, partnerships
- Competitors and market positioning (who else serves this market, how the
  company differentiates)
- Funding history / ownership (Crunchbase-style rounds, IPO status, parent
  company) and headcount trends (LinkedIn company page growth, job board
  volume) as a proxy for momentum
- Customer sentiment: reviews on G2/Capterra/Trustpilot, Glassdoor for
  employee sentiment, Reddit/Hacker News discussion threads
- Strategic risk signals: dependence on a single customer/platform/API,
  pending litigation, regulatory exposure, leadership turnover, over-reliance
  on one product line

### Lens 2 — Quant (financials & metrics)

Goal: find data-driven red flags, not just narrative.

For **public companies**: pull from SEC EDGAR full-text search
(https://www.sec.gov/cgi-bin/srqsb or efts.sec.gov full-text search) or
finance sites (stockanalysis.com, macrotrends.net) — revenue trend,
gross/operating margin trend, cash burn vs. runway, debt load and maturities,
insider buying/selling (Form 4 filings), guidance vs. actuals, valuation
multiples vs. peers.

For **private companies**: exact financials usually aren't public, so use
proxies and say clearly that they're proxies — funding round size/frequency
and the time between rounds (slowing rounds = a signal), reported valuation
vs. revenue multiples in press coverage, hiring velocity (job postings over
time) as a growth proxy, pricing-page changes over time via the Wayback
Machine (web.archive.org) as a signal of unit-economics pressure, and
review-site sentiment trend as a churn proxy.

In both cases, look for **mismatches**: growth narrative vs. hiring freezes,
premium positioning vs. discounting signals, "we're profitable" claims vs.
visible cash-burn indicators.

### Lens 3 — Senior Full-Stack Engineer (product & engineering)

Goal: infer the technical reality behind the marketing site — what they're
built on, how they operate it, and where it's likely to break or be
expensive to run.

Techniques (all passive, all just normal requests a browser would make):
- `WebFetch` the main site and note response headers (`Server`,
  `X-Powered-By`, cache headers), obvious framework fingerprints in page
  source (meta generator tags, JS bundle names, CSS class conventions), and
  response latency/page weight as a rough performance signal
- Check `robots.txt` and `sitemap.xml` for structure and staging/internal
  paths accidentally left crawlable
- Careers page: engineering job postings are a goldmine — they list the
  actual stack ("Kubernetes," "Kafka," "Go," "React," "Postgres," "Terraform")
  far more honestly than marketing pages do; note if postings mention
  legacy-system pain, "modernization," or migrations in progress
  (signals a rewrite is underway or overdue)
- Public GitHub org, if any: look at repo activity — last commit dates,
  open issue/PR backlog age, whether CI is green, dependency staleness
  (old lockfiles, EOL language/framework versions), how they respond to
  external contributions
- Engineering blog posts (architecture write-ups, postmortems) — postmortems
  in particular are a direct admission of what broke and why
- Public status page (often status.<domain> or a statuspage.io/atlassian
  instance) — incident frequency and MTTR over the last 6–12 months
- API docs, if public — versioning discipline, deprecation handling, rate
  limit design, auth model, error-message quality (all signal engineering
  maturity)
- App store reviews (iOS/Android) for a mobile product — recurring
  complaints about crashes, slowness, or specific broken flows are extremely
  concrete engineering-debt evidence
- Stack Overflow / dev forum tags naming the company's product — recurring
  developer complaints about their API/SDK

### Lens 4 — Security Researcher (passive, defensive OSINT only)

Read **Guardrails** below first — this lens has hard limits. Within them,
look for:

- **Certificate transparency logs** (e.g. `crt.sh?q=<domain>` via WebFetch) —
  reveals subdomains, which can show forgotten staging/dev/admin
  environments, acquisitions not yet folded into the main brand, or a wider
  attack surface than the main site suggests. Listing a subdomain's
  *existence* is fine; do not probe what's running on it beyond, at most, a
  single normal page request to the main site of that subdomain.
- **Security headers and TLS posture of the main public site only** — a
  single normal `WebFetch`/HEAD-equivalent request to check for HSTS, CSP,
  `X-Frame-Options`, cookie flags, and certificate validity/expiry. This is
  the same request a browser makes visiting the page; it's not a scan.
- **Known CVEs in the disclosed tech stack** — cross-reference software/
  versions you found via headers or job postings (e.g. "runs WordPress 5.x,"
  "uses an old Elasticsearch version per a job posting") against NVD/public
  CVE databases. This tells you what's *plausibly* exposed, not what
  definitely is — say so explicitly, don't claim confirmed exploitability
  you haven't (and won't) verify.
- **Public breach history** — news coverage of past incidents, and
  HaveIBeenPwned's public domain-breach lookup, for a track record.
- **Accidentally indexed sensitive material** — search-engine queries only
  (e.g. `site:<domain> filetype:env`, `site:pastebin.com "<company>"
  password`) to see *whether search engines have indexed something they
  shouldn't have*. If a search result suggests exposed credentials, internal
  docs, or similar: **do not open, download, or use it.** Note only that the
  search result exists (title/URL/snippet as shown by the search engine) and
  flag it as urgent, with a recommendation to have the company's security
  team (or their bug bounty program, if any) take it down — don't
  characterize its contents beyond what the search snippet already shows.
- **Bug bounty / responsible disclosure program** — check HackerOne/Bugcrowd
  and the company's own `security.txt`/`/.well-known/security.txt`. Note
  whether one exists; if the user (or someone they work with) ever wants to
  report something found here, that's the legitimate channel.

### What this lens is explicitly NOT

- No port scanning, vulnerability scanners, fuzzers, or any tool that sends
  abnormal/malformed/high-volume traffic (nmap, nuclei, sqlmap, Burp active
  scans, etc.)
- No login attempts, credential stuffing, or testing whether guessed/leaked
  credentials work
- No accessing, downloading, or exfiltrating anything found exposed — even
  if it's technically reachable, treat it as off-limits and flag it instead
- No targeting anything beyond the company's own public-facing domains
  (no probing third-party vendors, partners, or individual employees)
- If at any point what's being asked for drifts from "OSINT report" toward
  "actually test whether this works" or "help me get into X," stop and say
  plainly that's outside what this skill does, and that active testing
  requires the company's explicit written authorization (i.e., a real
  pentest engagement) — that's a different, much narrower thing than this
  report.

## 3. Guardrails (apply across all four lenses, not just security)

- **Public sources only.** Never suggest or attempt to access anything
  behind a login, paywall, or access control the user doesn't already have.
- **Attribute everything.** Every finding needs a source or a clearly marked
  "inference from X" — this report is meant to be defensible if the company
  pushes back on a claim.
- **Don't invent numbers.** If financials aren't public, say "not publicly
  disclosed" and use qualitative signals instead of guessing at figures.
- **Frame as opportunity, not accusation.** The report exists so the user can
  bring value to the company, not to embarrass it. Even sharp findings should
  read as "here's a gap and here's how I'd close it," not "you screwed up."
- **No harassment/targeting of individuals.** Leadership bios and public
  professional history are fair game; personal information about employees
  unrelated to the company's business risk is not.
- If the company or context makes you think this is about a competitor
  intelligence operation aimed at causing harm, retaliation, or anything
  other than legitimate research/outreach, ask the user directly what the
  report is for before proceeding.

## 4. Output structure

Write the report as a single markdown document (or an Artifact if the user
would benefit from a shareable, nicely formatted page — offer that if the
report is long or clearly meant to be shared/pitched). Use this structure:

```
# [Company Name] — Research & Opportunity Report
_Prepared [date] · Sources: public web research only_

## Executive Summary
3–6 bullets: the highest-impact, most credible opportunities across all four
lenses, ranked by (impact × how fixable/pitchable it is). This is what a
busy reader sees first.

## 1. Business & Market
[Narrative: what they do, market position, competitors, momentum]
### Opportunities
- **Problem:** ...
  **Evidence:** [source]
  **Why it matters:** ...
  **Suggested fix:** ...
  **Confidence:** High / Medium / Low

## 2. Financial & Quantitative Signals
[Narrative + any tables of metrics you found]
### Opportunities
(same format as above)

## 3. Technology & Engineering
[Narrative: inferred stack, engineering maturity signals]
### Opportunities
(same format as above)

## 4. Security & Data Protection (passive OSINT)
[Narrative: what passive recon showed]
### Opportunities
(same format as above — and if anything urgent/sensitive was found via
search-engine indexing, flag it clearly at the top of this section with a
recommendation to report it through the company's official channel, per the
Guardrails above)

## Sources
[List every URL/source used]
```

Every "Opportunity" entry must have a concrete, specific **Suggested fix** —
"improve security" is not acceptable, "publish a `security.txt`, add CSP
headers to the main site, and take down the indexed `.env.bak` file at
`/backup/.env.bak`" is. Specificity is what makes this pitchable.

If a lens turns up nothing substantive (e.g. a very small or very private
company with little public footprint), say so plainly in that section rather
than padding it with generic filler.

## 5. Depth calibration

Default to a thorough report (aim for real research across all four lenses,
not a handful of search results). If the user asks for something quick
("just give me a fast read on X"), do a lighter pass but keep the same
structure — fewer opportunities per section, but still sourced and still
actionable.
