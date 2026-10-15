---
name: scientific-taxonomy
description: >
  Build a hierarchical Markdown taxonomy from scientific-paper titles and complete abstracts.
  Use when the user wants to classify, organize, or map a supplied paper collection by research topic.
  If titles or complete abstracts are missing, first obtain them through an available local PDF-extraction capability or an AMiner search skill/API, then generate the taxonomy.
  Do not use this skill to implement PDF parsing, search for unrelated papers, create folders, or create symbolic links.
metadata:
  version: "1.0.3"
  author: "AMiner"
  contact: "report@aminer.cn"
---

# Scientific Taxonomy

Organize a supplied collection of scientific papers into one coherent topic hierarchy and write the result as Markdown.

## Input readiness

Build the taxonomy from these fields only:

- `paper_id`: optional stable identifier used internally for deduplication and AMiner URL construction. Do not display it in the Markdown paper list.
- `title`: required for every paper.
- `abstract`: the complete abstract, required when it can be retrieved. An `abstract_slice`, snippet, or truncated preview is not a complete abstract.
- `venue`: conference or journal name, required when it can be retrieved.
- `year`: publication year, required when it can be retrieved.
- `aminer_url`: preferred paper link. If absent and a valid AMiner `paper_id` exists, construct `https://www.aminer.cn/pub/{paper_id}`.

Before classifying, check whether the supplied information is sufficient:

1. When the user supplies local PDFs instead of titles and abstracts, invoke an available local PDF-extraction tool or Skill first. Consume its structured title and abstract output; do not implement PDF parsing in this Skill.
2. Treat `abstract_slice`, search snippets, and visibly truncated abstracts as insufficient taxonomy input. For AMiner search results, invoke `aminer-academic-search` and use `paper_detail` with each selected AMiner paper ID to retrieve the complete abstract before classifying. Follow that Skill's authorization, pricing, and high-cost confirmation rules.
3. When a paper is supplied only as a DOI, arXiv ID, URL, or title, use an available AMiner Skill or AMiner API to resolve the paper and retrieve its complete abstract. Prefer a free lookup route for identity resolution, then use full paper details when the free result contains only an abstract slice.
4. Enrich only papers already supplied by the user. Do not add related papers unless the user explicitly asks.
5. Never invent or expand an abstract. If full-abstract retrieval is unavailable or returns no abstract, classify from the verified title and available slice, then record the affected paper titles in a short metadata note without visibly displaying paper IDs.

## Taxonomy method

1. Infer a concise overall topic for the complete collection.
2. Create broad, reusable top-level research areas, then subdivide only where a meaningful distinction exists.
3. Use one semantic dimension within each sibling group, such as research problem, method family, application domain, or data type. Do not mix dimensions arbitrarily at the same level.
4. Consider the full collection when revising any level. For large inputs, read papers in batches but maintain one global taxonomy; do not build independent batch trees and merge them afterward.
5. Assign every paper to exactly one leaf. Do not omit, duplicate, or invent papers.
6. Prefer concise category names in the user's language. Avoid copied paper titles, numbered clusters, and vague labels such as “Other” or “Miscellaneous”.
7. Stop splitting when a category is already coherent or further division would create weak or artificial groups. Five heading levels below the document title is a safety limit, not a target.

## Output

Write one file named `taxonomy.md` in the user's requested location or the current workspace. If file writing is unavailable, return the same Markdown directly. Do not create JSON, directories, copied papers, or symbolic links.

For every paper entry, display metadata in this order:

1. Conference or journal abbreviation.
2. Publication year.
3. Exact paper title as a Markdown hyperlink to its AMiner page.

Use widely recognized venue abbreviations whenever available, such as `ACL`, `ACL SRW`, `EMNLP`, `NAACL`, `COLING`, `KDD`, `CIKM`, `ICML`, `ICLR`, `NeurIPS`, `TACL`, `IEEE BigData`, and `ICDMW`. Remove redundant words such as `Proceedings of` and avoid repeating a year already embedded in the venue name. For journals, use a recognized short title where one exists. Do not invent an uncertain abbreviation; use a concise official venue name instead. If the venue is unavailable after retrieval, write `Venue 未收录`. If the year is unavailable, write `年份未收录`.

Do not render `paper_id` as visible text. The identifier may appear only inside the AMiner hyperlink URL. If no verified AMiner URL can be formed, show the exact title as plain text rather than fabricating a link.

Use this structure:

```markdown
# <Collection topic>

## <Broad research area>

### <Specific topic>

- ACL 2024 — [Exact paper title](https://www.aminer.cn/pub/<paper_id>)
- TACL 2025 — [Another exact paper title](https://www.aminer.cn/pub/<paper_id>)
```

List papers only under leaf headings. Preserve titles exactly and use paper IDs internally to verify identity, uniqueness, and links. Order sibling categories coherently and keep the original paper order within each leaf unless the user asks for another order.

Use complete abstracts only as classification evidence. By default, do not reproduce abstract text in `taxonomy.md`; show only taxonomy headings and paper entries formatted as `venue abbreviation year — linked exact title`.

If metadata remains missing after attempted enrichment, append one blockquote after the taxonomy:

```markdown
> Metadata note: Complete abstracts were unavailable for “Paper title A” and “Paper title B” after retrieval was attempted; these papers were classified from verified titles and available abstract slices.
```

Before finishing, verify that every input paper appears once and only once, every listed paper came from the supplied collection, every title links to the correct AMiner page when a verified link is available, no paper ID is visibly rendered, venue names are shortened where reliable, and every heading accurately summarizes its descendant papers.
