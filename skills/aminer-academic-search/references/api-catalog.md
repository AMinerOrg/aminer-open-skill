# AMiner Open Platform API Complete Reference

**Base URL**: `https://datacenter.aminer.cn/gateway/open_platform`  
**Authentication**: All endpoints should default to `Authorization: ${AMINER_API_KEY}` and include `X-Platform` (current host: `claude-code` / `cursor` / `codex` / `openclaw`; `unknown` if it cannot be determined) in the request headers.  
**Skill identity** (required on every call; missing headers should be logged as `unknown`, never rejected): `X-Skill-Name: aminer-academic-search`, `X-Skill-Version` = this skill's `SKILL.md` frontmatter `version`. The gateway can aggregate API volume by name × version × platform × path.  
**Token**: Log in to the [Console](https://open.aminer.cn/open/board?tab=control) to generate one, then export it as `AMINER_API_KEY`.

---

## Table of Contents

- [Paper APIs (9)](#paper-apis)
- [Scholar APIs (6)](#scholar-apis)
- [Institution APIs (7)](#institution-apis)
- [Journal APIs (3)](#journal-apis)
- [Patent APIs (3)](#patent-apis)
- [Experiment APIs (1)](#experiment-apis)

---

## Paper APIs

### Choosing among the four search endpoints

They overlap heavily on output — all four now return the same screening fields (`first_author`/`authors`, `venue_name`, `year`, `n_citation_bucket`), so **output is no longer a reason to pick one**. Decide on two observable facts instead: is the query string a phrase or a sentence, and how many results do you need.

| | Accepts | Only it can do | Hard limit | Cost |
|---|---|---|---|---|
| Paper Search | Phrase | It is free | `title` only; ≤20/page; no filters or sort | Free |
| Paper Search Pro | Phrase, per field | 100/page + hard sort; cheapest bulk | Sentence → 0, still billed | ¥0.01 |
| Paper QA Search | Phrase or sentence | Weighted `topic_high/middle/low`; `sci_flag`; `offset` to 10000 | No ranges, no boolean exclusion | ¥0.05 |
| Paper QA Search Pro | Sentence | Semantic parsing; year/citation ranges; `all/any/exclude`; best precision | Fixed 10/page, ¥0.30 per page | ¥0.30 |

1. **Sentence?** Only the two QA endpoints parse it; the other two return 0 (and Paper Search Pro bills for that 0).
2. **More than 10 results?** Do not use QA Search Pro — 100 results costs ¥3.00 there versus ¥0.01 on Paper Search Pro. **300×.**

Spend ¥0.30 on QA Search Pro only for: a sentence query, a range filter, a boolean exclusion, or precision-first. Otherwise drop down.

---

### 1. Paper Search

- **URL**: `GET /api/paper/search`
- **Price**: Free
- **Description**: Phrase match against the `title` field. Free, so it is the first thing to try for any **phrase** query — it is not limited to titles you already know: a short controlled phrase (`retrieval augmented generation`) returns thousands of on-topic hits. It cannot parse a sentence (returns 0) and offers no filters or sort, so escalate when you need those.
- **Pick it when**: the query is a phrase and you need ≤20 results with no filtering.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| page | number | Yes | Page number (current online definition says it starts at 1) |
| size | number | No | Items per page, maximum 20 |
| title | string | Yes | Paper title |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Paper ID |
| title | Paper title |
| title_zh | Paper title (Chinese) |
| doi | DOI |
| first_author | First author |
| n_citation_bucket | Citation bucket (see note below) |
| venue_name | Venue title |
| year | Publication year |
| total | Total count |

> **Citation bucket values.** The official docs describe the buckets as `0` / `1-10` / `11-50` / `51-200` / `200-1000` / `1000-5000` / `5000+`, but the live API emits the boundary-exclusive form `201-1000` and `1001-5000`. Match on both spellings; never parse a bucket into an exact citation count.

**curl Example:**
```bash
curl -X GET \
  'https://datacenter.aminer.cn/gateway/open_platform/api/paper/search?page=1&size=10&title=Looking+at+CTR+Prediction+Again%3A+Is+Attention+All+You+Need' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0'
```

---

### 2. Paper Search Pro

- **URL**: `GET /api/paper/search/pro`
- **Price**: ¥0.01/call
- **Description**: Fielded literal matching across title / keyword / abstract / author / org / venue, with a hard sort. The **cheapest way to pull volume**: 100 results per call for ¥0.01. Matching is literal — a full sentence returns `"msg": "no data"` **and is still billed**; `keyword` wants one controlled term, `title`/`abstract` a two- or three-word phrase.
- **Pick it when**: the query is already a structured filter, or you need more than 20 results.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| page | number | No | Page number (starts at 0) |
| size | number | No | Items per page, maximum 100 |
| title | string | No | Title keyword |
| keyword | string | No | Keyword |
| abstract | string | No | Abstract keyword |
| author | string | No | Author name |
| org | string | No | Institution name |
| venue | string | No | Journal name |
| order | string | No | Sort field: `year` (descending by year) or `n_citation` (descending by citations); omit for composite ranking |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Paper ID |
| title | Title (English) |
| title_zh | Title (Chinese) |
| doi | DOI |
| first_author | First author |
| n_citation_bucket | Citation bucket (same values as Paper Search) |
| venue_name | Venue title |
| year | Publication year |
| total | Total count |

**curl Example:**
```bash
curl -X GET \
  'https://datacenter.aminer.cn/gateway/open_platform/api/paper/search/pro?title=transformer&author=Vaswani&order=n_citation&page=0&size=5' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0'
```

---

### 3. Paper QA Search

- **URL**: `POST /api/paper/qa/search`
- **Price**: ¥0.05/call
- **Description**: Accepts either a sentence (via `query`, keywords extracted server-side) or weighted structured topics. Two things only this endpoint can do: **three-tier weighted nested AND/OR** (`topic_high`/`topic_middle`/`topic_low`) and **deep paging** (`size` ≤ 100 with `offset` ≤ 10000 — 100 results for ¥0.05, which Pro's 10-per-page cursor cannot match). It has no year/citation ranges and no boolean exclusion.
- **Pick it when**: you need weighted topic tiers, `sci_flag`, or cheap deep paging.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| use_topic | boolean | Yes | When `true`, searches with topic fields and/or keywords extracted from `query`; when `false`, only `title`/`doi` are read and `query` is ignored. Set `true` for any `query` or topic search. |
| topic_high | string | No | Valid when use_topic=true; keywords that must match (AND logic). Nested array format: `[["termA","termB"],["termC"]]` — outer AND, inner OR. |
| topic_middle | string | No | Strongly boosted terms; same format as topic_high. |
| topic_low | string | No | Weakly boosted terms; same format as topic_high. |
| title | []string | No | Title query; the only text field read when use_topic=false. |
| doi | string | No | Exact DOI query. |
| year | []number | No | Year filter array. |
| sci_flag | boolean | No | Return SCI papers only. |
| n_citation_flag | boolean | No | Boost papers with high citation counts. |
| size | number | No | Maximum number of results to return, maximum 100. |
| offset | number | No | Offset, maximum 10000. |
| force_citation_sort | boolean | No | Sort entirely by citation count. |
| force_year_sort | boolean | No | Sort entirely by year. |
| author_terms | []string | No | Author name query; OR relationship within array; include multiple variants. |
| org_terms | []string | No | Institution name query; OR relationship within array. |
| author_id | []string | No | Author entity ID filter; accepts single ID or ID list. OR relationship with author_terms when both are provided. |
| org_id | []string | No | Institution entity ID filter; accepts single ID or ID list. OR relationship with org_terms when both are provided. |
| venue_ids | []string | No | Conference/journal ID list filter. |
| query | string | No | Raw natural language question (slower); system auto-extracts keywords. Takes precedence over topic_high when both are provided. Only effective with use_topic=true; with `false` it is silently ignored and the call returns 403 "no data". |

**Response Fields:**

| Field | Description |
|--------|------|
| code | Status code |
| message / msg | Status text |
| data | Paper list |
| id | Paper ID |
| title | Paper title |
| title_zh | Title (Chinese) |
| doi | DOI |
| first_author | First author |
| n_citation_bucket | Citation bucket (same values as Paper Search); omitted for uncited papers |
| venue_name | Venue title |
| year | Publication year |
| total | Total count |

**curl Example (natural language Q&A):**
```bash
curl -X POST \
  'https://datacenter.aminer.cn/gateway/open_platform/api/paper/qa/search' \
  -H 'Content-Type: application/json;charset=utf-8' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0' \
  -d '{"use_topic": true, "query": "deep learning protein structure prediction", "size": 10, "sci_flag": true}'
```

**curl Example (structured keywords):**
```bash
curl -X POST \
  'https://datacenter.aminer.cn/gateway/open_platform/api/paper/qa/search' \
  -H 'Content-Type: application/json;charset=utf-8' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0' \
  -d '{
    "use_topic": true,
    "topic_high": "[[\\"transformer\\",\\"self-attention\\"],[\\"protein folding\\"]]",
    "topic_middle": "[[\"AlphaFold\"]]",
    "sci_flag": true,
    "force_citation_sort": true,
    "size": 10
  }'
```

> **Narrow but not obsolete.** Reach for this when you need weighted topic tiers, `sci_flag`, or 100 results at depth for ¥0.05. For a plain sentence query use Paper QA Search Pro; for a plain phrase query use the free Paper Search or ¥0.01 Paper Search Pro.

---

### 3b. Paper QA Search Pro

> **Highest quality, highest price (¥0.30 — 30× Paper Search Pro).** Not a blanket default: spend it only when the query is a sentence, needs a range filter or boolean exclusion, or precision is the explicit requirement.

- **URL**: `POST /api/paper/qa/searchPro`
- **Price**: ¥0.30/call
- **Description**: The only endpoint that genuinely parses natural language, and the highest-precision retrieval of the four. Adds year/citation **ranges**, `all_terms`/`any_terms`/`exclude_terms` booleans, `search_in` scoping, and `sort` modes. Page size is fixed at **10** (not client-configurable) and each cursor page costs another ¥0.30, so it is the wrong tool for volume.
- **Pick it when** you can name one of: a sentence query, a range filter, a boolean exclusion, or precision-first (the user wants accuracy, or a cheaper endpoint already came back off-topic). Otherwise drop to `paper_search_pro` — 30× cheaper.

> **Path change.** The canonical path is now `/api/paper/qa/searchPro`. The old `/api/v3/paper/qa/searchPro` still resolves as a legacy alias, but new code should use the non-`v3` path.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| query | string | No | Search text, max 500. Required when `query_type` is not `auto`. |
| query_type | string | No | `auto` / `topic` / `keywords` / `title` / `identifier`. Default `auto`. |
| cursor | string | No | Pagination cursor (16–256 chars). On next page, request body may contain **only** `cursor`. |
| authors | []string | No | Author names; OR within list; max 100 |
| author_ids | []string | No | Author IDs; OR with `authors` |
| organizations | []string | No | Organization names; OR within list |
| organization_ids | []string | No | Organization IDs; OR with `organizations` |
| venues | []string | No | Venue names, e.g. `["NeurIPS"]` |
| venue_ids | []string | No | Venue IDs; OR with `venues` |
| year_values | []number | No | Exact years; mutually exclusive with `year_from`/`year_to` |
| year_from | number | No | Start year (inclusive) |
| year_to | number | No | End year (inclusive); must be ≥ `year_from` |
| languages | []string | No | Hard language filter, e.g. `["en","zh"]` |
| language_preference | string | No | Soft preference boost: `zh` / `en` |
| has_chinese_title | boolean | No | Require / forbid Chinese title |
| has_abstract | boolean | No | Require / forbid abstract |
| min_citations | number | No | Minimum citation count (inclusive) |
| max_citations | number | No | Maximum citation count (inclusive) |
| all_terms | []string | No | All terms must match; max 20 |
| any_terms | []string | No | At least one term must match |
| exclude_terms | []string | No | Exclude if any term matches |
| search_in | string | No | Scope for all/any/exclude only: `all` / `title` / `title_keywords` / `abstract` |
| paper_ids | []string | No | Restrict to paper IDs |
| exclude_paper_ids | []string | No | Exclude paper IDs |
| dois | []string | No | DOI filter |
| sort | string | No | `relevance` / `balanced` / `recent` / `citation` |

**Response Fields (open-platform envelope):**

| Field | Description |
|--------|------|
| success | Whether the call succeeded |
| code | HTTP-style status: 200/400/410/500/502/503/504 |
| message / msg | Status text; success often `"success"` or empty |
| data | Business payload; usually `null` on failure |
| data.items | Paper list (card view, compact fields only) |
| data.items[].paper_id | Paper ID |
| data.items[].title | Title (English/original) |
| data.items[].title_zh | Title (Chinese) |
| data.items[].authors[].name | Author English name |
| data.items[].authors[].name_zh | Author Chinese name |
| data.items[].n_citation_bucket | Citation bucket (same values as Paper Search) |
| data.items[].venue_name | Venue title |
| data.items[].year | Publication year (may be omitted) |
| data.total.value | Hit count estimate |
| data.total.relation | `eq` / `gte` / `unknown` |
| data.next_cursor | Next-page cursor; null/omitted when no more pages |
| data.warnings | Business warnings (`code` / `message`) |

**Notes:**
- Page size is fixed at 10; do **not** send `size` / `view` / `facets` / internal debug flags.
- Pagination: first page → read `next_cursor` → next page body is `{"cursor":"..."}` only.
- Always append paper URL: `https://www.aminer.cn/pub/{paper_id}`.

**curl Example:**
```bash
curl -X POST \
  'https://datacenter.aminer.cn/gateway/open_platform/api/paper/qa/searchPro' \
  -H 'Content-Type: application/json;charset=utf-8' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0' \
  -d '{
    "query": "大模型比较新的高引论文",
    "query_type": "auto",
    "sort": "balanced",
    "year_from": 2024,
    "min_citations": 30
  }'
```

**curl Example (next page):**
```bash
curl -X POST \
  'https://datacenter.aminer.cn/gateway/open_platform/api/paper/qa/searchPro' \
  -H 'Content-Type: application/json;charset=utf-8' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0' \
  -d '{"cursor":"<NEXT_CURSOR_FROM_PREVIOUS_RESPONSE>"}'
```

---

### 4. Paper Info

- **URL**: `POST /api/paper/info`
- **Price**: Free
- **Description**: Batch-retrieve lightweight paper cards by paper ID, including abstract slice, year, venue ID, author list, and author count.

> **Mandatory Parameter Constraints (High Priority)**
> 1. `paper_info` only supports the batch parameter `ids` (array); it does not support a single `paper_id`.
> 2. `paper_detail` only supports the single-paper parameter `id` (string); in the client `raw` function wrapper, the corresponding parameter name is `paper_id`.
> 3. Never pass `ids` to `paper_detail`; doing so will trigger a parameter error (e.g., `unexpected keyword argument 'ids'`).
> 4. If many results are matched and the user has not specified a count, default to querying only the top 10 details to avoid unnecessary costs.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| ids | []string | Yes | Paper ID array, maximum 100 |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Paper ID |
| title | Paper title |
| abstract_slice | Partial abstract |
| authors | Author list (includes `name` / `name_zh`) |
| author_count | Total author count |
| issue | Volume number |
| raw | Journal name |
| venue | Journal info object |
| venue_id | Venue ID |
| year | Publication year |

**curl Example:**
```bash
curl -X POST \
  'https://datacenter.aminer.cn/gateway/open_platform/api/paper/info' \
  -H 'Content-Type: application/json;charset=utf-8' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0' \
  -d '{"ids": ["53e9ab9bb7602d97023e53b2", "53e9a98eb7602d9703e42e5a"]}'
```

**Usage Note:**

`paper_info` is a batch endpoint. Always pass `ids` as an array, even when querying only one paper.

---

### 5. Paper Details

- **URL**: `GET /api/paper/detail`
- **Price**: ¥0.01/call
- **Description**: Retrieve full paper details by paper ID.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| id | string | Yes | Paper ID |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Paper ID |
| title | Title (English) |
| title_zh | Title (Chinese) |
| abstract | Abstract |
| abstract_zh | Abstract (Chinese) |
| authors | Author list (name/name_zh/org/org_zh) |
| doi | DOI |
| issn | ISSN |
| issue | Volume number |
| volume | Issue number |
| year | Year |
| keywords | Keywords |
| keywords_zh | Keywords (Chinese) |
| raw | Journal name |
| venue | Journal info object |

**curl Example:**
```bash
curl -X GET \
  'https://datacenter.aminer.cn/gateway/open_platform/api/paper/detail?id=53e9ab9bb7602d97023e53b2' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0'
```

**Usage Note:**

`paper_detail` is a single-paper endpoint. Pass one `id`; do not pass `ids`.

---

### 6. Paper Citations

- **URL**: `GET /api/paper/relation`
- **Price**: ¥0.10/call
- **Description**: Retrieve the list of papers cited by a given paper ID.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| id | string | Yes | Paper ID |

**Response Fields:**

| Field | Description |
|--------|------|
| _id | Paper ID |
| title | Title |
| cited | Basic info of papers cited by this paper |
| n_citation | Number of times cited |

**curl Example:**
```bash
curl -X GET \
  'https://datacenter.aminer.cn/gateway/open_platform/api/paper/relation?id=53e9ab9bb7602d97023e53b2' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0'
```

---

### 7. Paper Batch Query (Multi-keyword)

- **URL**: `GET /api/paper/list/citation/by/keywords`
- **Price**: ¥0.10/call
- **Description**: Retrieve paper keywords, abstracts, and other information via multiple keywords.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| page | number | Yes | Page number |
| size | number | Yes | Items per page |
| keywords | string | Yes | Keyword array (JSON string format) |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Paper ID |
| title / title_zh | Title (bilingual) |
| abstract / abstract_zh | Abstract (bilingual) |
| keywords / keywords_zh | Keywords (bilingual) |
| doi | DOI |
| year | Year |
| total | Total count |

**curl Example:**
```bash
curl -X GET \
  'https://datacenter.aminer.cn/gateway/open_platform/api/paper/list/citation/by/keywords?page=0&size=10&keywords=%5B%22deep+learning%22%2C%22object+detection%22%5D' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0'
```

---

### 8. Paper Details by Year and Venue

- **URL**: `GET /api/paper/platform/allpubs/more/detail/by/ts/org/venue`
- **Price**: ¥0.20/call
- **Description**: Retrieve paper titles, authors, DOIs, keywords, and other details by publication year and journal.

> **Note**: `venue_id` and `year` must be provided together; providing only `year` returns `null`. Use the **Venue Search** API first to obtain the `venue_id`.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| year | number | Yes | Paper publication year |
| venue_id | string | Yes | Journal ID (obtained via Venue Search; returns null if not provided) |

**Response Fields (main):**

| Field | Description |
|--------|------|
| _id | Paper ID |
| title / title_zh | Title (bilingual) |
| abstract | Abstract |
| authors | Author array (name/org/email/homepage/orc_id/`_id`) |
| doi | DOI |
| issn | ISSN |
| keywords / keywords_zh | Keywords (bilingual) |
| year | Year |
| venue | Journal info |

**curl Example:**
```bash
curl -X GET \
  'https://datacenter.aminer.cn/gateway/open_platform/api/paper/platform/allpubs/more/detail/by/ts/org/venue?year=2023&venue_id=<VENUE_ID>' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0'
```

---

## Scholar APIs

### 9. Scholar Search

- **URL**: `POST /api/person/search`
- **Price**: Free
- **Description**: Search for scholar candidates by name and institution conditions; returns identity, institution, interests, and citation count.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| name | string | No | Scholar name |
| org | string | No | Institution name |
| org_id | []string | No | Institution entity ID array |
| offset | number | No | Starting position (fixed at 0; pagination not supported) |
| size | number | No | Number of results, maximum 10 |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Scholar ID |
| name | Name |
| name_zh | Name (Chinese) |
| org | Institution (English) |
| org_zh | Institution (Chinese) |
| org_id | Institution ID |
| interests | Research interests |
| n_citation | Citation count |
| total | Total count |

**curl Example:**
```bash
curl -X POST \
  'https://datacenter.aminer.cn/gateway/open_platform/api/person/search' \
  -H 'Content-Type: application/json;charset=utf-8' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0' \
  -d '{"name": "Andrew Ng", "size": 5}'
```

---

### 10. Scholar Details

- **URL**: `GET /api/person/detail`
- **Price**: ¥1.00/call
- **Description**: Retrieve complete personal information by scholar ID.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| id | string | Yes | Scholar ID |

**Response Fields:**

| Field | Description |
|--------|------|
| id / person_id | Scholar ID |
| name / name_zh | Name (bilingual) |
| bio / bio_zh | Personal bio (bilingual; not both present simultaneously) |
| edu / edu_zh | Education history (bilingual) |
| orgs / org_zhs | Institution list (English / Chinese) |
| position / position_zh | Title (bilingual) |
| domain | Research domain |
| honor | Honors |
| award | Awards |
| year | Year |

**curl Example:**
```bash
curl -X GET \
  'https://datacenter.aminer.cn/gateway/open_platform/api/person/detail?id=53f3ae78dabfae4b34b0c75d' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0'
```

---

### 11. Scholar Portrait

- **URL**: `GET /api/person/figure`
- **Price**: ¥0.50/call
- **Description**: Retrieve research interests, domains, and structured work/education history.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| id | string | Yes | Scholar ID |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Scholar ID |
| ai_interests | Research interest list |
| ai_domain | Research domain list |
| edus | Structured education history |
| works | Structured work history |

**curl Example:**
```bash
curl -X GET \
  'https://datacenter.aminer.cn/gateway/open_platform/api/person/figure?id=53f3ae78dabfae4b34b0c75d' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0'
```

---

### 12. Scholar Papers

- **URL**: `GET /api/person/paper/relation`
- **Price**: ¥1.50/call
- **Description**: Retrieve a list of papers published by a scholar (ID + title).

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| id | string | Yes | Scholar ID |

**Response Fields:**

| Field | Description |
|--------|------|
| author_id | Scholar ID |
| id | Paper ID |
| title | Paper title |

**curl Example:**
```bash
curl -X GET \
  'https://datacenter.aminer.cn/gateway/open_platform/api/person/paper/relation?id=53f3ae78dabfae4b34b0c75d' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0'
```

---

### 13. Scholar Patents

- **URL**: `GET /api/person/patent/relation`
- **Price**: ¥1.50/call
- **Description**: Retrieve a list of patents associated with a scholar.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| id | string | Yes | Scholar ID |

**Response Fields:**

| Field | Description |
|--------|------|
| patent_id | Patent ID |
| person_id | Scholar ID |
| title | Patent title |
| en | Title (English) |
| zh | Title (Chinese) |

**curl Example:**
```bash
curl -X GET \
  'https://datacenter.aminer.cn/gateway/open_platform/api/person/patent/relation?id=53f3ae78dabfae4b34b0c75d' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0'
```

---

### 14. Scholar Projects

- **URL**: `GET /api/project/person/v3/open`
- **Price**: ¥1.50/call
- **Description**: Retrieve research projects a scholar has participated in (funding amount, dates, source).

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| id | string | No | Scholar ID |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Project ID |
| titles | Project title |
| country | Country |
| project_source | Project source |
| fund_amount | Funding amount |
| fund_currency | Funding currency |
| start_date | Start date |
| end_date | End date |
| total | Total count |

**curl Example:**
```bash
curl -X GET \
  'https://datacenter.aminer.cn/gateway/open_platform/api/project/person/v3/open?id=53f3ae78dabfae4b34b0c75d' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0'
```

---

## Institution APIs

### 15. Org Search

- **URL**: `POST /api/organization/search`
- **Price**: Free
- **Description**: Search for institution IDs and standard names by institution keyword; includes partial aliases for normalization.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| orgs | []string | No | Institution name array |

**Response Fields:**

| Field | Description |
|--------|------|
| aliases | Alias list (partial, usually top 3) |
| org_id | Institution ID |
| org_name | Institution name |
| total | Total count |

**curl Example:**
```bash
curl -X POST \
  'https://datacenter.aminer.cn/gateway/open_platform/api/organization/search' \
  -H 'Content-Type: application/json;charset=utf-8' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0' \
  -d '{"orgs": ["Tsinghua University"]}'
```

---

### 16. Org Details

- **URL**: `POST /api/organization/detail`
- **Price**: ¥0.01/call
- **Description**: Retrieve institution details by institution ID.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| ids | []string | Yes | Institution ID array |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Institution ID |
| name / name_en / name_zh | Institution name (raw/English/Chinese) |
| acronyms | Abbreviation |
| aliases | Alias list |
| details | Detailed institution description |
| type | Institution type (university/enterprise, etc.) |
| location | Geographic location |
| language | Language |
| total | Total count |

**curl Example:**
```bash
curl -X POST \
  'https://datacenter.aminer.cn/gateway/open_platform/api/organization/detail' \
  -H 'Content-Type: application/json;charset=utf-8' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0' \
  -d '{"ids": ["5f71b2091c455f439fe9a7d7"]}'
```

---

### 17. Org Scholars

- **URL**: `GET /api/organization/person/relation`
- **Price**: ¥0.50/call
- **Description**: Retrieve the list of scholars affiliated with an institution (10 results per call).

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| org_id | string | No | Institution ID |
| offset | number | No | Starting position (returns 10 results per call) |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Scholar ID |
| name / name_zh | Scholar name (bilingual) |
| org / org_zh | Institution (bilingual) |
| org_id | Institution ID |
| total | Total count |

**curl Example:**
```bash
curl -X GET \
  'https://datacenter.aminer.cn/gateway/open_platform/api/organization/person/relation?org_id=5f71b2091c455f439fe9a7d7&offset=0' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0'
```

---

### 18. Org Papers

- **URL**: `GET /api/organization/paper/relation`
- **Price**: ¥0.10/call
- **Description**: Retrieve the list of papers published by scholars at an institution (10 results per call).

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| org_id | string | Yes | Institution ID |
| offset | number | Yes | Starting position (returns 10 results per call) |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Paper ID |
| title / title_zh | Title (bilingual) |
| doi | DOI |
| total | Total count |

**curl Example:**
```bash
curl -X GET \
  'https://datacenter.aminer.cn/gateway/open_platform/api/organization/paper/relation?org_id=5f71b2091c455f439fe9a7d7&offset=0' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0'
```

---

### 19. Org Patents

- **URL**: `GET /api/organization/patent/relation`
- **Price**: ¥0.10/call
- **Description**: Retrieve the list of patent IDs owned by an institution; supports pagination with up to 10,000 results per call.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| id | string | Yes | Institution ID |
| page | number | No | Page number (starts at 1) |
| page_size | number | No | Items per page; maximum 10,000 |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Patent ID |
| total | Total count |

**curl Example:**
```bash
curl -X GET \
  'https://datacenter.aminer.cn/gateway/open_platform/api/organization/patent/relation?id=6233173d0a6eb145604733e2&page=1&page_size=100' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0'
```

---

### 20. Org Disambiguation

- **URL**: `POST /api/organization/na`
- **Price**: ¥0.01/call
- **Description**: Retrieve the standardized institution name from an institution string (including abbreviations/aliases).

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| org | string | Yes | Institution name (may include aliases/abbreviations) |

**Response Fields:**

| Field | Description |
|--------|------|
| org_name | Normalized institution name |

**curl Example:**
```bash
curl -X POST \
  'https://datacenter.aminer.cn/gateway/open_platform/api/organization/na' \
  -H 'Content-Type: application/json;charset=utf-8' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0' \
  -d '{"org": "MIT CSAIL"}'
```

---

### 21. Org Disambiguation Pro

- **URL**: `POST /api/organization/na/pro`
- **Price**: ¥0.05/call
- **Description**: Extract the IDs of primary and secondary institutions from an institution string (recommended for workflows).

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| org | string | Yes | Institution name |

**Response Fields:**

| Field | Description |
|--------|------|
| 一级 | Primary institution name |
| 一级ID | Primary institution ID |
| 二级 | Secondary institution name |
| 二级ID | Secondary institution ID |
| Total / total | Total count |

**curl Example:**
```bash
curl -X POST \
  'https://datacenter.aminer.cn/gateway/open_platform/api/organization/na/pro' \
  -H 'Content-Type: application/json;charset=utf-8' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0' \
  -d '{"org": "Department of Computer Science, Tsinghua University"}'
```

---

## Journal APIs

### 22. Venue Search

- **URL**: `POST /api/venue/search`
- **Price**: Free
- **Description**: Search for venue IDs and standard names by venue name; includes aliases and venue type.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| name | string | No | Journal name (supports fuzzy search) |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Journal ID |
| name_en | Journal name (English) |
| name_zh | Journal name (Chinese) |
| aliases | Alias list (partial, usually top 3) |
| venue_type | Venue type: `journal` or `conference` |
| total | Total count |

**curl Example:**
```bash
curl -X POST \
  'https://datacenter.aminer.cn/gateway/open_platform/api/venue/search' \
  -H 'Content-Type: application/json;charset=utf-8' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0' \
  -d '{"name": "tkde"}'
```

---

### 23. Venue Details

- **URL**: `POST /api/venue/detail`
- **Price**: ¥0.20/call
- **Description**: Retrieve ISSN, abbreviation, type, and other details by journal ID.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| id | string | Yes | Journal ID |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Journal ID |
| name / name_en / name_zh | Name (raw/English/Chinese) |
| issn | ISSN |
| eissn | EISSN |
| alias | Alias |
| type | Journal type |

**curl Example:**
```bash
curl -X POST \
  'https://datacenter.aminer.cn/gateway/open_platform/api/venue/detail' \
  -H 'Content-Type: application/json;charset=utf-8' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0' \
  -d '{"id": "<VENUE_ID>"}'
```

---

### 24. Venue Papers

- **URL**: `POST /api/venue/paper/relation`
- **Price**: ¥0.10/call
- **Description**: Retrieve a list of papers for a journal by journal ID (supports year filtering).

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| id | string | Yes | Journal ID |
| offset | number | No | Starting position |
| limit | number | No | Number of results to return |
| year | number | No | Filter by year |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Paper ID |
| title | Paper title |
| year | Year |
| offset | Current offset |
| total | Total count |

**curl Example:**
```bash
curl -X POST \
  'https://datacenter.aminer.cn/gateway/open_platform/api/venue/paper/relation' \
  -H 'Content-Type: application/json;charset=utf-8' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0' \
  -d '{"id": "<VENUE_ID>", "year": 2023, "offset": 0, "limit": 20}'
```

---

## Patent APIs

### 25. Patent Search

- **URL**: `POST /api/patent/search`
- **Price**: Free
- **Description**: Search for patents by title or keyword; returns lightweight trend fields such as first inventor, application year, and publication year.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| query | string | Yes | Query field, such as patent title or keywords |
| page | number | Yes | Page number |
| size | number | Yes | Items per page |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Patent ID |
| title | Patent title (English) |
| title_zh | Patent title (Chinese) |
| inventor_name | First inventor name |
| app_year | Application year |
| pub_year | Publication year |

**curl Example:**
```bash
curl -X POST \
  'https://datacenter.aminer.cn/gateway/open_platform/api/patent/search' \
  -H 'Content-Type: application/json;charset=utf-8' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0' \
  -d '{"page":0,"query":"Si02","size":20}'
```

---

### 26. Patent Info

- **URL**: `GET /api/patent/info`
- **Price**: Free
- **Description**: Retrieve a patent basic card by patent ID, including patent numbers, inventor, country, and basic year fields.

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| id | string | Yes | Patent ID |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Patent ID |
| title / en | Patent title (English) |
| app_num | Application number |
| pub_num | Publication number |
| pub_kind | Publication type |
| inventor | Inventor |
| country | Country |
| sequence | Sequence |
| app_year | Application year |
| pub_year | Publication year |

**curl Example:**
```bash
curl -X GET \
  'https://datacenter.aminer.cn/gateway/open_platform/api/patent/info?id=<PATENT_ID>' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0'
```

---

### 27. Patent Details

- **URL**: `GET /api/patent/detail`
- **Price**: ¥0.01/call
- **Description**: Retrieve full patent details by patent ID (including abstract, filing date, assignee, IPC classification, etc.).

**Request Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| id | string | Yes | Patent ID |

**Response Fields:**

| Field | Description |
|--------|------|
| id | Patent ID |
| title | Patent title |
| abstract | Abstract |
| app_date | Filing date |
| app_num | Application number |
| pub_date | Publication date |
| pub_num | Publication number |
| pub_kind | Publication type |
| assignee | Assignee |
| inventor | Inventor |
| country | Country |
| ipc | IPC classification code |
| ipcr | IPCR classification code |
| cpc | CPC classification code |
| priority | Priority info |
| description | Description |

**curl Example:**
```bash
curl -X GET \
  'https://datacenter.aminer.cn/gateway/open_platform/api/patent/detail?id=<PATENT_ID>' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0'
```

---

## Experiment APIs

### 29. Experiment Search

- **URL**: `POST /api/v3/paper/search/experiment_data/SearchPro`
- **Price**: ¥0.10/call
- **Authentication**: `Authorization: ${AMINER_API_KEY}`, `X-Platform` (current host), plus the two `X-Skill-*` headers above
- **Description**: Retrieve original structured Experiment JSON. Exact filters plus Elasticsearch `search_text`. Use only for explicit experiment-level requests.

**Skill Parameters:**

| Parameter | Type | Required | Description |
|--------|------|------|------|
| paper_id | string | Conditional | Exact paper ID; sent as backend `paper_id` after trim |
| search_text | string | Conditional | ES full-text over experiment text fields below. Free text (paper title, experiment name, etc.) goes here. |
| dataset_name | string | Conditional | Exact `datasets[].name`; sent as backend `dataset` after trim |
| method | string | Conditional | Exact method; sent as backend `method` after trim |
| size | number | No | Added to the backend body only when greater than 0 |

At least one of `paper_id`, `method`, `dataset_name`, or `search_text` must be non-empty.

**`search_text` covers these indexed text fields:**
`paper_title`, `experiment_name`, `research_problem`, `research_problem_description`, `research_goal`, method name/description text, `conclusion`, `limitations`, `key_results`.

**Backend Request Body:**

```json
{
  "paper_id": "",
  "method": "",
  "dataset": "",
  "search_text": ""
}
```

Exact filter fields and `search_text` are always present after trim (empty string when unused). `size` is optional and is added only when greater than 0. Do **not** accept or send a separate `experiment_name` query parameter; put that text in `search_text`.

**Supported Response Shapes:**
- An array of Experiment objects
- `{ "results": [...] }`
- Arrays under `data`, `items`, `experiments`, or `records`
- Any nesting of those supported envelope fields
- A single Experiment object

A single Experiment object is recognized by the presence of `paper_id` or `experiment_name`. Unrecognized responses return a structured `invalid_experiment_response` error and are never silently treated as empty results.

**Common Experiment Fields:**

| Field | Description |
|--------|------|
| paper_id | Source paper ID |
| paper_title | Paper title |
| experiment_name | Experiment name |
| research_problem / research_problem_description | Research problem text |
| research_goal | Research goal |
| methods | Method list; each entry is an object with `name` / `description` (see migration note below) |
| datasets | Dataset objects; `dataset_name` maps to backend `dataset` |
| conclusion / limitations / key_results | Result narrative fields |

> **Method field migration.** Each result now returns `methods` as a list (`[{name, description, ...}]`) instead of the flat `method` / `method_description` pair; some older records may still carry the flat fields. When reading results, take `methods` first and fall back to the flat pair; never flatten a `methods` list into a single `method` string (that silently drops all but the first entry). The backend `method` request filter is unchanged and still takes a single string.

**Matching and Output Rules:**
- `paper_id` / `method` / `dataset` are exact filters; `search_text` is ES full-text. No client-side re-filtering.
- Backend-bound values use trim only and preserve case.
- Success shape: `{ "results": [...] }` with original Experiment objects.
- Do not summarize raw JSON; presentation may list non-empty returned fields only.

**curl Example:**
```bash
curl -X POST \
  'https://datacenter.aminer.cn/gateway/open_platform/api/v3/paper/search/experiment_data/SearchPro' \
  -H 'Content-Type: application/json;charset=utf-8' \
  -H 'Authorization: ${AMINER_API_KEY}' \
  -H 'X-Platform: claude-code' \
  -H 'X-Skill-Name: aminer-academic-search' \
  -H 'X-Skill-Version: 1.4.0' \
  -d '{"paper_id":"<PAPER_ID>","method":"","dataset":"","search_text":"Baseline"}'
```

---

## Appendix: API Pricing Summary

| Category | Free APIs | Paid APIs |
|------|---------|---------|
| Paper | Paper Search, Paper Info | Paper Search Pro(¥0.01), Paper Details(¥0.01), Paper Citations(¥0.10), Paper QA Search(¥0.05), **Paper QA Search Pro(¥0.30)**, Paper Batch Query(¥0.10), By Condition(¥0.20) |
| Scholar | Scholar Search | Scholar Details(¥1.00), Scholar Portrait(¥0.50), Scholar Papers(¥1.50), Scholar Patents(¥1.50), Scholar Projects(¥1.50) |
| Institution | Org Search | Org Details(¥0.01), Org Scholars(¥0.50), Org Papers(¥0.10), Org Patents(¥0.10), Org Disambiguation(¥0.01), Org Disambiguation Pro(¥0.05) |
| Journal | Venue Search | Venue Details(¥0.20), Venue Papers(¥0.10) |
| Patent | Patent Search, Patent Info | Patent Details(¥0.01) |
| Experiment | None | Experiment Search(¥0.10) |

---

## Appendix: Common Error Codes

| Code | Meaning | Recommended Action |
|------|---------|-------------------|
| 401 | Token invalid or expired | Re-generate token at [Console](https://open.aminer.cn/open/board?tab=control) |
| 403 | Insufficient balance or permission denied | Top up account or check token scope |
| 404 | Entity not found | Verify the ID is correct |
| 429 | Rate limit exceeded | Wait a few seconds and retry |
| 500 / 502 / 503 / 504 | Server error (transient) | Retry with exponential backoff (1s → 2s → 4s) |

> For `4xx` errors (except 429), do not retry — fix the request parameters first.

---

## Appendix: Pagination Limits

| API | Constraint |
|-----|-----------|
| `paper_search` | `size` max 20; `page` starts at 1 |
| `paper_search_pro` | `page` starts at 0 |
| `paper_qa_search_pro` | Fixed 10 results/page; use `cursor` / `next_cursor` (cursor-only body on next page) |
| `person_search` | `size` max 10; `offset` fixed at 0 (no pagination) |
| `org_person_relation` | Fixed 10 results per call; use `offset` to paginate |
| `org_paper_relation` | Fixed 10 results per call; use `offset` to paginate |
| `org_patent_relation` | `page_size` max 10,000; `page` starts at 1 |
| `venue_paper_relation` | Use `offset` + `limit` to paginate |
| `paper_info` | `ids` array max 100 items |
