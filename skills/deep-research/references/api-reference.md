# AMiner Public API Reference

The catalog below mirrors the `aminer-academic-search` skill: same endpoints, same names, same prices. That skill's `references/api-catalog.md` is the authoritative parameter documentation — read it when you need a field this page does not describe. Do not invent endpoints, and do not call an endpoint that is not in this table.

- Base URL: `https://datacenter.aminer.cn/gateway/open_platform`
- Auth header: `Authorization: ${AMINER_API_KEY}`, plus `X-Platform: openclaw`
- Every call goes through `scripts/aminer_open.py`. Parameters not listed for an API are rejected before any network access.
- Prices are estimates in CNY per attempted call; check current AMiner documentation for changes.

Machine-readable registry (names, methods, prices, accepted parameters):

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --list-apis
```

## Paper APIs

| Name | Method and path | Required / one-of | Optional | Price |
| --- | --- | --- | --- | ---: |
| `paper_search` | GET `/api/paper/search` | `title` | `page`, `size` | Free |
| `paper_info` | POST `/api/paper/info` | `ids` | — | Free |
| `paper_search_pro` | GET `/api/paper/search/pro` | one of `title`, `keyword`, `abstract`, `author`, `org`, `venue` | `order`, `page`, `size` | ¥0.01 |
| `paper_qa_search_pro` | POST `/api/v3/paper/qa/searchPro` | one of `query`, `cursor`, `authors`, `author_ids`, `organizations`, `organization_ids`, `venues`, `venue_ids`, `all_terms`, `any_terms`, `paper_ids`, `dois` | `query_type`, `year_from`, `year_to`, `year_values`, `min_citations`, `max_citations`, `exclude_terms`, `search_in`, `languages`, `language_preference`, `has_abstract`, `has_chinese_title`, `exclude_paper_ids`, `sort` | ¥0.70 |
| `paper_qa_search` | POST `/api/paper/qa/search` | one of `query`, `topic_high`, `title`, `doi`, `author_id`, `org_id`, `venue_ids` | `use_topic`, `topic_middle`, `topic_low`, `year`, `sci_flag`, `n_citation_flag`, `force_citation_sort`, `force_year_sort`, `author_terms`, `org_terms`, `size`, `offset` | ¥0.05 |
| `paper_detail` | GET `/api/paper/detail` | `id` | — | ¥0.01 |
| `paper_relation` | GET `/api/paper/relation` | `id` | — | ¥0.10 |
| `paper_list_by_keywords` | GET `/api/paper/list/citation/by/keywords` | `keywords` | `page`, `size` | ¥0.10 |
| `paper_detail_by_condition` | GET `/api/paper/platform/allpubs/more/detail/by/ts/org/venue` | `year`, `venue_id` | `org_id`, `page`, `size` | ¥0.20 |

Paper search routing:

1. **Topic or multi-filter search → `paper_qa_search_pro`.** This is the default. Page size is fixed at 10; do not send `size`. Paginate by reading `data.next_cursor` and sending a body that carries `cursor` only. `sort` is `relevance` / `balanced` / `recent` / `citation`. The response only carries `paper_id`, `title`, `title_zh`, `authors[].name`, `year` — use `paper_detail` when a full abstract or keywords matter. It parses free text with a server-side LLM, so it is the slowest endpoint in the catalog (~5 s measured, against the shared 30 s timeout), and `aminer_open.py` does **not** retry it automatically because it is billed (see below).
2. **Known title → `paper_search`** (free) to get the ID, then `paper_detail`.
3. **Structured filter on author / org / venue / keyword with citation or year ordering → `paper_search_pro`** (¥0.01) — 70× cheaper than Pro when the query is already structured, which after a scout it usually is. Its `keyword` field matches a single controlled term and `title` / `abstract` match a short phrase; a sentence returns `"msg": "no data"` and is still billed.
4. **Legacy `paper_qa_search` only** when `topic_high` / `topic_middle` / `topic_low` OR-AND structure is explicitly required. `query` and the topic fields are mutually exclusive.
5. Batch cheap metadata with free `paper_info` (`ids` array); never loop `paper_detail` for bulk triage. A slice is truncated at roughly 190 characters — it identifies a paper, it does not report its findings. And `paper_detail` is the AMiner ceiling, not the reading ceiling — the full text lives outside this API (see §Open-access fulltext).

### `query_type` on `paper_qa_search_pro`

| Value | Runs an LLM | Behaviour |
| --- | --- | --- |
| `auto` (default) | Yes | Parses free text into topic, filters, translation and sort intent. Also recognises a full DOI, arXiv id, 24-hex paper id, or a quoted title. |
| `topic` | No | Searches `title` / `title_zh` / `keywords` / `abstract` literally. |
| `keywords` | No | Keyword fields only. |
| `title` | No | Title only. |
| `identifier` | No | `query` must be a complete DOI / arXiv id / 24-hex paper id. |

**Use `auto` — query mode — as the default.** Measured at about 5 s per call against about 0.4 s for the non-LLM modes; you buy recall with that latency, and it stays well inside the uniform 30 s timeout.

Drop to `topic` when you need a term matched verbatim, and **pin the concept with `all_terms` when you do**. Literal matching drifts: a multi-concept phrase gets pulled toward whichever term dominates the index. Measured on one subject:

| Query | Mode | Result |
| --- | --- | --- |
| `"efficient large language model architecture mixture of experts long context"` | `topic` | ten long-context papers, zero on MoE |
| `"mixture of experts sparse activation in large language models"` | `auto` | ten MoE-on-LLM papers, two of them surveys |
| `"sparse expert routing…"` + `all_terms:["mixture of experts"]` | `topic` | ten MoE routing papers; `total` went from `gte 10000` to `eq 1058` |

`auto` has one property that does not go away in either mode: it normalises differently-worded questions to the same parsed topic, so two probes that differ only in phrasing return the same papers. Separate probes by object and structured filter, never by rewording — the two MoE queries above did, and returned 19 distinct papers out of 20.

### Steering a query that drifts

These are in the allowlist and are the actual instruments for "change the retrieval axis":

| Field | Use |
| --- | --- |
| `all_terms` | every result must contain these — the fix for a probe that wandered into another field |
| `any_terms` | at least one must appear — widens a narrow topic without changing its object |
| `exclude_terms` | drop the vocabulary that hijacked the probe (`["segmentation","retinopathy"]`) |
| `search_in` | restrict matching to given fields |
| `language_preference`, `has_chinese_title` | reach the Chinese corpus; an English topic phrase silently excludes it |
| `venues`, `year_from` / `year_to` / `year_values`, `min_citations` | narrow a `gte 10000` field into a slice worth reading |

### Response signals worth reading

`aminer_open.py` hoists these onto each result so you do not have to dig into `data.data`:

- `warnings[]` — `QUERY_CONDITION_IGNORED` means an explicit condition overrode the parsed one, so the query that ran is not the query you sent. Also `FACET_DEGRADED`, `CURSOR_UNAVAILABLE`, `CITATION_FLOOR_UNSUPPORTED`.
- `total` — `{"value": N, "relation": "eq" | "gte" | "unknown"}`. A large `gte` means your ten results are a thin slice of a broad field; a small `eq` means you have nearly all of it. `references/research-loop.md` states what each case obliges you to do.
- `may_have_been_billed` — on a failed **paid** call, the request may have been served and charged even though the response never arrived. Every endpoint shares a 30 s timeout, but paid ones default to a single attempt (`--retries 1`): a retried timeout can bill twice while the ledger, which only counts cost on success, records nothing. Reconcile with `evidence.py spend --api <name> --cny <price>`.

Known blind spot: on zero results the service may relax a non-explicit year or citation filter and report it as `QUERY_RELAXED_*`, but those codes are internal and are not returned to the open platform. A `year_from` you sent can therefore be dropped without any visible signal — say so in the report's Limitations when a year range matters to the conclusion.

## Scholar APIs

| Name | Method and path | Required | Price |
| --- | --- | --- | ---: |
| `person_search` | POST `/api/person/search` | one of `name`, `org`, `org_id` | Free |
| `person_detail` | GET `/api/person/detail` | `id` | ¥1.00 |
| `person_figure` | GET `/api/person/figure` | `id` | ¥0.50 |
| `person_paper_relation` | GET `/api/person/paper/relation` | `id` | ¥1.50 |
| `person_patent_relation` | GET `/api/person/patent/relation` | `id` | ¥1.50 |
| `person_project` | GET `/api/project/person/v3/open` | `id` | ¥1.50 |

Disambiguate with free `person_search` first: organization, interests, and name variants must agree before any paid scholar call. A full scholar profile (detail + figure + papers + patents + projects) costs about ¥6.00 and therefore needs user confirmation — ask which sub-modules are actually needed.

## Institution APIs

| Name | Method and path | Required | Price |
| --- | --- | --- | ---: |
| `org_search` | POST `/api/organization/search` | `orgs` | Free |
| `org_disambiguate` | POST `/api/organization/na` | `org` | ¥0.01 |
| `org_disambiguate_pro` | POST `/api/organization/na/pro` | `org` | ¥0.05 |
| `org_detail` | POST `/api/organization/detail` | `ids` | ¥0.01 |
| `org_person_relation` | GET `/api/organization/person/relation` | `org_id` | ¥0.50 |
| `org_paper_relation` | GET `/api/organization/paper/relation` | `org_id` | ¥0.10 |
| `org_patent_relation` | GET `/api/organization/patent/relation` | `id` | ¥0.10 |

Free `org_search` first; escalate to `org_disambiguate_pro` only when aliases or nested affiliations stay ambiguous.

## Venue APIs

| Name | Method and path | Required | Price |
| --- | --- | --- | ---: |
| `venue_search` | POST `/api/venue/search` | `name` | Free |
| `venue_detail` | POST `/api/venue/detail` | `id` | ¥0.20 |
| `venue_paper_relation` | POST `/api/venue/paper/relation` | `id` | ¥0.10 |

## Patent APIs

| Name | Method and path | Required | Price |
| --- | --- | --- | ---: |
| `patent_search` | POST `/api/patent/search` | `query` | Free |
| `patent_info` | GET `/api/patent/info` | `id` | Free |
| `patent_detail` | GET `/api/patent/detail` | `id` | ¥0.01 |

`patent_search` accepts only `query` / `page` / `size` — no sort or filter parameters, unlike `paper_search_pro`'s citation / year ordering; relevance is the channel's only order. Quality priority is therefore host-side: widen the pool (`size` up to 100, paginate) and screen by tier once `patent_detail` has run (see the research loop's quality-screening rule).

## Chains that work

- Topic review: `paper_qa_search_pro` → free `paper_info` triage → selected `paper_detail` → at most three `paper_relation`.
- Known paper: `paper_search` → `paper_detail` → optional `paper_relation`.
- Scholar: `person_search` → confirm identity → only the paid scholar calls the question needs.
- Institution: `org_search` (or `org_disambiguate_pro`) → the one or two relation APIs that matter.
- Venue year scan: `venue_search` → `venue_paper_relation`, or `paper_detail_by_condition` when year plus venue detail is the point.
- Patent landscape (industry-report tasks only — see `research-loop.md` §Patents). Patents are mandatory for an industry report but are not pre-assigned to fixed sections; the chains below are common uses, not a checklist — retrieve wherever patents strengthen the analysis:
  - Technology ownership / evolution: `patent_search` (free) by tech term → free `patent_info` triage → `patent_detail` (¥0.01) for the few a claim leans on → the Google Patents original for those few (see §Open-access fulltext).
  - Enterprise portfolio: `org_search` (free) → `org_patent_relation` (¥0.10) for a named org's full portfolio. `patent_detail` also persists each patent's `assignee`, so a per-assignee chart assembles straight from the ledger once the detail calls have run; for a named org's exhaustive set, `org_patent_relation` keeps the org dimension intact.
  - Filing-trend evolution: `patent_search` across year windows (free) → free `patent_info` triage → `patent_detail` for the patents a chart will use (`evidence.py` coerces `app_year`/`pub_year` and `app_date`/`pub_date` into an integer `year`, so the chart assembles from the ledger).
- Generic patent lookup (any task): `patent_search` → free `patent_info`, then `patent_detail` only for the few that matter.

## Entity URLs (always attach)

- Paper: `https://www.aminer.cn/pub/{paper_id}`
- Scholar: `https://www.aminer.cn/profile/{scholar_id}`
- Patent: `https://www.aminer.cn/patent/{patent_id}`
- Venue: `https://www.aminer.cn/open/journal/detail/{venue_id}`

`scripts/evidence.py` fills these in automatically for `paper`, `scholar`, `patent`, and `venue` sources when it has an ID. Institutions and scholar projects have no public AMiner page, so `org` and `project` sources stay link-free — cite them by name, never invent a URL for them.

## Open-access fulltext (outside AMiner)

No endpoint in this catalog returns a paper or patent body — `paper_detail` / `patent_detail` stop at the full abstract. The original, when it is open, is read with the host's own web tools and recorded with `scripts/evidence.py fulltext --source N --url … --via …` (or `--unavailable` when no open copy exists). Resolution order, cheapest signal first:

| Object | Where the original lives | `--via` |
| --- | --- | --- |
| Paper with an arXiv id | `https://arxiv.org/abs/<id>` — the abstract page links HTML, PDF, and TeX source; HTML renders best through a page fetcher, the PDF when the host can parse it | `arxiv-html` / `arxiv-pdf` / `arxiv-tex` |
| Paper without an arXiv id | Search arXiv by exact title (if it lands, the row above applies); then a publisher open-access page (green or gold) | `arxiv-html` / `arxiv-pdf` / `arxiv-tex` / `publisher` / `other` |
| Patent | `https://patents.google.com/patent/<publication-number>` — full claims and description. The number comes from the ledger itself: a `patent_detail` ingest persists `pub_num` / `app_num` / `pub_kind` (see them with `source show`). The two number fields swap places between records — take whichever holds the ~9-digit publication number and build `CN{digits}{pub_kind}`; the 12-digit `YYYY…` value is the application number. No AMiner page visit is needed (they are JS-rendered shells a fetcher cannot read anyway). | `google-patents` |

Fulltext-first rule: a claim that leans on a paper or patent reads the original whenever one is obtainable, and degrades to the abstract only when it is not — with the downgrade recorded, so `check` (`cited_sources_without_fulltext`) can tell "could not" from "did not". These fetches cost nothing against the AMiner budget. The ledger keeps no body text: numbers lifted from the original go in the read's `--note`, which is what the number-provenance check searches. Marking `--unavailable` after a recorded read undoes the read and restores the source's AMiner depth — the correction path when an "open" copy turns out paywalled.
