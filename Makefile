# ---------------------------------------------------------------------------
# Omni-Localizer (OL) developer / CI entrypoints.
# All targets route through `uv` so the local `.venv` is always the source
# of truth. Run `make help` to list targets.
# ---------------------------------------------------------------------------

.PHONY: help install test lint build docker run docker-run clean

help:
	@echo "OL targets:"
	@echo "  install   - uv sync (project + all extras + dev)"
	@echo "  test      - run pytest with the FAKE_LLM seam enabled"
	@echo "  lint      - ruff check on src/ and tests/"
	@echo "  build     - build sdist + wheel via uv build"
	@echo "  docker    - build the production image as ol:dev"
	@echo "  run       - run 'ol --help' inside the local venv"
	@echo "  docker-run- run 'ol --help' inside the production image"
	@echo "  clean     - remove build artifacts and __pycache__ dirs"

install:
	uv sync --all-extras

# OMNI_TEST_FAKE_LLM=1 short-circuits real LLM calls inside ol_cli so the
# suite runs hermetically without provider credentials.
test:
	OMNI_TEST_FAKE_LLM=1 uv run pytest tests/ -v

lint:
	uv run ruff check src/ tests/

build:
	uv build

docker:
	docker build -t ol:dev .

run:
	uv run ol --help

docker-run:
	docker run --rm ol:dev

clean:
	rm -rf .venv build/ dist/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
