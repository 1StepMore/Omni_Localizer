# Omni-Localizer (OL)

AI-native localization pipeline with automated quality control.

## Architecture

- **MD Channel**: Token Stream reconstruction + 4-layer semantic repair
- **XLIFF Channel**: translate-toolkit based
- **LQA**: openevalkit (Scorer→Judge two-layer) + COMET
- **LLM Routing**: LiteLLM with model pool failover
- **TM**: hypomnema (TMX)
- **Alignment**: span-aligner + VectorAlign

## Development Phases

| Phase | Description | Duration |
|-------|-------------|----------|
| M0 | Infrastructure + data structures + mock interfaces | 2.5 days |
| M1 | MD native channel | 3 days |
| M2 | XLIFF channel | 2 days |
| M3a | Routing + model pool + concurrency | 1.5 days |
| M3b | LQA + TM + checkpoint | 1.5 days |
| M4 | UX + E2E + PyPI | 1.5 days |

**Total**: 10 days

## Setup

```bash
poetry install
```

## Test

```bash
poetry run pytest
```

## License

MIT