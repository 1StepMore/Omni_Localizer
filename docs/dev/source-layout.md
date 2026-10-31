# OL source layout (moved from AGENTS.md, #162)

Full annotated tree of `src/`:

```
src/
├── ol_cli.py                # `ol` CLI entry (Typer) — builds the app, registers 21 sub-commands
├── cli/                     # CLI sub-command implementations
│   ├── _shared.py           # ExitCode, precheck_api_keys, signal handling
│   ├── cache.py             # content-addressed cache (root ~/.omni_cache/ol)
│   ├── translate_md.py      # `translate-md` + _load_env_for_cli
│   ├── translate_xliff.py   # `translate-xliff`
│   ├── batch.py             # `translate-batch` + `extract-warnings`
│   └── …                    # one module per other sub-command
├── ol/                      # package marker; src/ol/__init__.py holds __version__
├── ol_config/               # YAML config + Pydantic schema
│   ├── schema.py            # LLMPoolConfig, ProjectConfig
│   ├── loader.py            # load_config() with ${ENV_VAR} resolution
│   └── resolver.py          # ${VAR} resolution helpers
├── ol_pool/                 # ModelPool (litellm Router wrapper)
│   ├── router.py            # E2E-83: pre-call check removed
│   ├── prompts/             # OL#112: prompt store (*.txt)
│   ├── fake.py              # _FakeModelPool test seam
│   └── json_tolerance.py    # LLM JSON tolerance
├── ol_md/                   # MD translation channel
│   ├── shield.py            # E2E-77/78: math regex + [OL:...] markers
│   ├── repair/              # repair stages (regex → span → [L3 LLM opt-in] → fallback)
│   ├── extractor.py         # Tokenize MD into translatable units
│   ├── pipeline.py          # MDRepairPipeline
│   └── token_stream.py
├── ol_xliff/                # XLIFF translation channel
│   ├── repair/              # E2E-64: is_complete() checks actual XML
│   ├── parser.py            # trans-unit iteration
│   ├── shield.py            # inline-tag shielding
│   ├── polish.py
│   └── pipeline.py
├── ol_buses/                # Shared translation bus (md_bus, xliff_bus, xliff_shield)
├── ol_batch/                # BatchProcessor
├── ol_terminology/          # RAG-based prompt injection
│   ├── rag_injector.py      # build_translate_prompt with TM/glossary
│   ├── extractor.py         # YAKE term extraction
│   └── disambiguator.py     # LLM-based polysemy resolution
├── ol_lqa/                  # Linguistic Quality Assurance
│   ├── judge.py             # JudgeService (score 0-100)
│   ├── qa_rules.py          # LQA rules
│   └── quality_gates.py     # OL#56 + OL#158: 8 quality gate functions; terms audit is a separate tool
├── ol_restoration/          # Post-translate placeholder restoration
├── ol_concurrency/          # ConcurrencyLimiter (semaphores)
├── ol_retry/                # RetryManager
├── ol_logging/              # Structured JSON + console logger
├── ol_checkpoint/           # Translation checkpointing (library-only; not wired into CLI/batch)
├── ol_post/                 # zh↔en punctuation normalization
├── ol_tm/                   # TMX translation memory service
├── ol_style/                # StyleGuide profiling + cache
├── ol_core/                 # TranslationContext, TranslationUnit, ChannelType
├── ol_review_extractor.py
└── ol_mcp/                  # MCP server (the Agent-facing surface)
```
