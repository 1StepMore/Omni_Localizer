# OL translation pipeline — MD channel detail (moved from AGENTS.md, #162)

OL's MD translation is a 6-stage pipeline:

```
   input.md
     │
     ▼
  ┌─────────────┐
  │  1. SHIELD   │  Replace code blocks, math ($..$), links, images,
  │             │  HTML, autolinks with [OL:TYPE:NNNN] markers
  └─────────────┘
     │  shielded.md + shield_map
     ▼
  ┌─────────────┐
  │  2. TRANSLATE│  LLM call (litellm Router → ModelPool)
  │             │  with retry + circuit breaker + rate limit
  └─────────────┘
     │  translated.md (with markers preserved)
     ▼
  ┌─────────────┐
  │  3. REPAIR   │  3-stage restoration of any markers the LLM
  │             │  mangled / dropped:
  │             │    Level 1: regex (fast)
  │             │    Level 2: span alignment
  │             │    Level 3: LLM-based (LiteLLMRestorer)
  │             │    Level 4: safe fallback (append at end with warning)
  └─────────────┘
     │  repaired.md
     ▼
  ┌─────────────┐
  │ 4. UNSHIELD  │  Replace [OL:TYPE:NNNN] markers with original content
  │             │  from shield_map. Missing markers → OL_WARN comment.
  └─────────────┘
     │  output.md
     ▼
   ┌─────────────┐
   │ 5. POSTPROC  │  zh↔en punctuation normalization (ol_post.punctuation)
   │             │  + YAML frontmatter injection (source/target lang, ...)
   └─────────────┘
      │
      ▼
   ┌──────────────┐
    │ 6. QUALITY   │  8 gates run after translation/repair, warnings
    │    GATES     │  appended during final output generation:
    │             │  • inline_tags — verify <bx>/<ex>/<x> tag parity
    │             │  • terminology — detect mixed source/glossary term usage
    │             │  • length_ratio — fail if OL_LENGTH_RATIO_MIN..MAX exceeded
    │             │  • locale — currency mixing, date leakage, digit grouping,
    │             │            unit spelling (en-US vs en-GB)
    │             │  • source_copy — detect unchanged source echo in target
    │             │  • source_script_fragments — detect CJK residue in non-CJK target locale
    │             │  • protocol_artifacts — detect LLM protocol markers leaked to output
    │             │  • invented_tokens — detect model-invented glued tokens (OL#158)
   └──────────────┘
      │
      ▼
   output.md (final)
```

## Prompts are a first-class asset (OL#112)

The core translation/judging prompts live in `src/ol_pool/prompts/*.txt`, not
inline in `router.py`. **Changing a prompt touches only a file under
`prompts/`.**

| Prompt | Used by | Variables |
|--------|---------|-----------|
| `translate_system.txt` | `ModelPool.translate()` | `$source_lang`, `$target_lang` |
| `translate_user.txt` | `ModelPool.translate()` | `$source_lang`, `$target_lang`, `$user_text` |
| `judge_system.txt` | `ModelPool.judge()` | none |
| `judge_user.txt` | `ModelPool.judge()` | `$source_lang`, `$source`, `$target_lang`, `$target`, `$terminology_section` |

```python
from ol_pool.prompts import load_prompt, render_prompt

render_prompt("translate_system", source_lang="en", target_lang="zh")
```

Templates are stdlib `string.Template` (`$name`) — **not** `str.format`,
because the prompts legitimately contain `{`/`}` (`{{_OL_XTAG_*_}}`, the judge
JSON schema). A literal `$` must be written `$$`. Rendering **fails loud**
(`PromptRenderError`) on a missing *or* an undeclared variable, so a renamed
placeholder can never silently leave a hole in a prompt.

`tests/test_prompt_store.py` pins the rendered bytes against digests captured
before the extraction, and asserts each prompt is defined in exactly one place
in `src/` — if you intentionally change a prompt, expect those digests to fail
and update them deliberately.

## Pipeline behavior notes (E2E regression contracts)

- **E2E-65 — prompt injection strip**: if the LLM echoes back
  `CRITICAL: Output ONLY the translation...` or similar system-prompt
  fragments, the Level 1 repair strips them via regex. Don't strip these
  patterns yourself; OL handles it.
- **E2E-14 — base64 image dedup**: after translation, if the LLM re-encoded
  `![…](…)` image refs as fresh base64 lines, they're deduplicated. OPP
  already produced the canonical refs in the input.
- **E2E-64 — XLIFF repair `is_complete()`**: the XLIFF repair pipeline checks
  that the XLIFF has all `<target>` elements filled. If not, it attempts
  restoration before writing the output.
- **E2E-77/78 — shield marker format + unshield fallback**:
  - Math: `$..$` only matched if it contains a LaTeX marker
    (`\command`, `^`, or `_`) — currency text is not eaten.
  - HTML: `[OL:HTML:NNNN]` ASCII-delimited markers (not NUL-delimited
    which LLMs would strip).
  - Unshield: if a marker is missing, the original content is appended
    at the end under a `<!-- OL_WARN:missing_shields key1,key2,... -->`
    comment, never silently lost.
- **E2E-83 — litellm pre-call check removed**: OL used to pass
  `optional_pre_call_checks=['enforce_model_rate_limits']` to litellm's
  Router, which fast-rejected large requests (>~50KB / >~20K tokens) and
  triggered 10/20/40s backoffs in the translate() retry loop. This was
  removed; per-model RPM is still set in `litellm_params['rpm']` but
  rejection now comes from the provider's HTTP 429 (handled by the
  existing backoff).

## translate-md vs translate-xliff (channel selection)

OL offers two translation channels for different pipeline paths:

| Aspect | `translate-md` | `translate-xliff` |
|--------|---------------|-------------------|
| Input | `.md` file | `.xlf` / `.xliff` file |
| Output | Translated `.md` | XLIFF with `<target>` filled |
| Downstream | ORF `apply-md` (16 formats) | ORF `apply-xliff` (needs skeleton) |
| Layout preservation | Text-only (pandoc renders) | Full original layout retained |
| Image handling | Via `images.json` + `--separate-images` | Auto-reinjected from skeleton |
| When to use | Web content, docs, e-books | Contracts, branded docs, exact-layout |

**Decision flow:**

1. Is your source an OPP XLIFF that came with a skeleton.zip? → **`translate-xliff`**
2. Do you need the output to look exactly like the source? → **`translate-xliff`**
3. Otherwise → **`translate-md`** (faster, more format choices)

**Both paths can run in parallel** if OPP extracted with `--target-format both`.
The MD and XLIFF channels share no state — translate both simultaneously.

**Full pipeline comparison**: see the suite-level
[Pipeline Selection Strategy](https://github.com/1StepMore/e2e-test-suite/blob/main/README.md#pipeline-selection-strategy)
for the complete decision tree and format support matrix.
