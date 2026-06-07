# Glossary File Format (v1)

Omni-Localizer (OL) accepts a user-supplied **glossary** that biases the
LLM toward your terminology during translation. This document specifies
the JSON / YAML file format the `--glossary` flag expects, with examples
and validation rules.

> **Status**: v1 (PR12 + PR13 of the `slim-pipeline-hardening` plan).
> Stable: changes to this format require a new major version.

---

## 1. Top-level shape

A glossary file is a single object with one required key, `terms`,
whose value is an array of entries:

```jsonc
{
  "terms": [
    { "source": "...", "targets": ["...", "..."] },
    { "source": "...", "targets": ["..."] }
    // ...
  ]
}
```

| Field   | Type             | Required | Notes                                                   |
|---------|------------------|----------|---------------------------------------------------------|
| `terms` | array of entries | yes      | Empty array is valid (no terms injected).               |
| `terms[].source`   | non-empty string | yes | The source-language term (case-sensitive).     |
| `terms[].targets`  | array of non-empty strings, length ≥ 1 | yes | One or more target-language equivalents. |

**Validation**: OL validates the file with a strict Pydantic schema
(`extra="forbid"`). Unknown top-level keys or extra entry fields raise
`ValueError` at load time — the CLI exits with a clear error and a
non-zero status. There is no silent fallback.

---

## 2. How OL uses a glossary

When you pass `--glossary path/to/glossary.json` to `translate-md` or
`translate-xliff`, the CLI:

1. **Loads** the file with `Glossary.load(path)` — JSON or YAML
   (decided by file extension; unknown extensions default to JSON).
2. **Validates** the payload against the Pydantic schema.
3. For each trans-unit (XLIFF) or shielded chunk (MD):
   - Computes a relevance score for every term: the count of
     non-overlapping occurrences of `source` in the source text.
   - Sorts by score descending; takes the top **N** terms (default 5,
     configurable via `--glossary-max-terms N`).
   - Injects those terms into the translation prompt as a single
     `Use these terms: src→tgt, src2→tgt2, ...` line.
4. The LLM sees the terms in-context and biases its translation
   toward them. **OL does not rewrite the LLM output** — the
   terminology bias is a prompt-level nudge.

If `source` doesn't appear in the source text, the term is skipped
(ranking is substring-count-based; ties broken by insertion order).

### What about legacy / dict-shaped glossaries?

A previous "legacy" format existed:

```json
{
  "API endpoint": {
    "translation": "API 端点",
    "variants": { ... },
    "confidence": 0.95
  }
}
```

This format is still supported by the **legacy** loader
(`ol_terminology.glossary.load_glossary`) used by `BatchProcessor` and
the RAG path. The **new** v1 format (this doc) is what `--glossary`
expects on the `translate-md` / `translate-xliff` CLI. Both paths
co-exist; tests for the legacy one live in `test_glossary_loader.py`.

---

## 3. Examples

### Example 1 — Minimal single-term glossary

The smallest valid glossary file: one term, one target.

```json
{
  "terms": [
    { "source": "API", "targets": ["API"] }
  ]
}
```

Use case: forcing the LLM to keep the abbreviation "API" untranslated
in languages where it is conventional. Note: the target `"API"` is
intentional — you can pin the exact target string the LLM should use.

### Example 2 — Multi-term software-domain glossary

A typical product team glossary, with one-to-many mappings (the LLM
sees the first target; later targets are reference for context):

```json
{
  "terms": [
    { "source": "API",          "targets": ["API", "应用程序接口"] },
    { "source": "rendering",    "targets": ["渲染"] },
    { "source": "shader",       "targets": ["着色器"] },
    { "source": "pipeline",     "targets": ["管线"] },
    { "source": "compiler",     "targets": ["编译器"] },
    { "source": "endpoint",     "targets": ["端点"] },
    { "source": "middleware",   "targets": ["中间件"] },
    { "source": "kernel",       "targets": ["内核"] },
    { "source": "buffer",       "targets": ["缓冲区"] },
    { "source": "thread",       "targets": ["线程"] },
    { "source": "lock",         "targets": ["锁"] },
    { "source": "queue",        "targets": ["队列"] }
  ]
}
```

Notes:
- `source` matching is **case-sensitive** and **substring-based**. So
  the entry `"source": "API"` matches every occurrence of "API" in the
  source text (e.g., inside "API endpoint" too). If you need to match
  only the standalone abbreviation, set `"source": "API "` (with
  trailing space) or scope the entry to a particular phrasing.
- The order in the `terms` array is the tie-breaker for relevance
  ranking when two terms have the same count.
- Top-5 (or `--glossary-max-terms N`) terms are injected per
  trans-unit; the rest are ignored for that unit.

### Example 3 — YAML form (same data as Example 2)

The loader picks the parser from the file extension. `.yaml` /
`.yml` files use PyYAML's `safe_load`; `.json` uses `json.load`.
Unrecognized extensions default to JSON.

```yaml
terms:
  - source: API
    targets:
      - API
      - 应用程序接口
  - source: rendering
    targets: ["渲染"]
  - source: shader
    targets: ["着色器"]
  # ... (rest as in Example 2)
```

YAML form is useful when your glossary is hand-edited; JSON is the
machine-friendly default. Pick whichever your team prefers — they are
load-equivalent.

---

## 4. CLI flags that affect glossary behavior

These are the user-visible switches on `translate-md` and
`translate-xliff` that interact with the glossary:

| Flag                       | Effect                                                              |
|----------------------------|---------------------------------------------------------------------|
| `--glossary PATH`          | Load the glossary from PATH and inject top-N terms into prompts.    |
| `--no-glossary`            | Skip glossary injection even if `--glossary` is set or the config   |
|                            | declares one. Wins over both.                                       |
| `--glossary-max-terms N`   | Override the default top-5 with top-N. `N >= 1`.                    |

The legacy `/ no glossary` behavior (no flag, no config) is the
pre-PR12 default: translation proceeds without terminology bias.

---

## 5. Validation errors

If the file is malformed, the CLI exits with a non-zero status and
prints a clear error. Common failure modes:

- `Error: glossary file not found: <path>` — path doesn't exist.
- `Error: failed to load glossary <path>: Glossary validation failed
  at terms.0.source: Input should be a valid string` — schema
  violation. The Pydantic error message names the offending field.
- `Error: failed to load glossary <path>: Malformed JSON in
  <path>: ...` — JSON parse error.

No silent fallback: the user passed `--glossary` intentionally, so a
malformed file is a hard error rather than a degraded translation.

---

## 6. Python API

For library users (not the CLI):

```python
from ol_terminology import Glossary

g = Glossary.load("docs/glossary_format.json")  # or .yaml
relevant = g.find_relevant("Use the API to call the rendering pipeline.")
# [("API", ["API", "应用程序接口"]), ("rendering", ["渲染"]), ...]

prompt = g.inject_into_prompt(
    source_text="Use the API to call the rendering pipeline.",
    prompt="Translate to zh:",
    max_terms=5,
)
# "Translate to zh:\n\nUse these terms: API→API, rendering→渲染, ..."
```

See `src/ol_terminology/glossary_class.py` for the full dataclass
implementation. The `Glossary.load` constructor is the single entry
point — there is no separate "register" or "validate" call.

---

## 7. Versioning

| Version | Source                                                  |
|---------|---------------------------------------------------------|
| v1      | PR12 of `slim-pipeline-hardening.md` (PR12+PR13). The    |
|         | shape is `{terms: [{source, targets}, ...]}`.            |

When v2 ships, it will be additive (new top-level keys, new
optional fields) — v1 files will keep loading under v2.
