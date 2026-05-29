#!/bin/bash
# Wrapper for OL MCP server - loads .env before starting
cd /mnt/d/Hermes-Workspace/01-Projects/Omni_Localizer
set -a
source .env
set +a

# E2E-05 fix: prevent liteLLM Router from auto-adding bert-base-multilingual-cased
# when network is unreachable. Must be set before Python process starts.
export LITELLM_OFFLINE="true"
export LITELLM_DISABLE_MODEL_LIST_AUTO_UPDATE="true"
# E2E-05 fix: prevent span-aligner from loading bert-base-multilingual-cased
# (span-aligner's SpanProjector instantiates transformers on __init__)
export HF_HUB_OFFLINE="1"

exec /home/renanzai/.hermes/venvs/omni-localizer/bin/python src/ol_mcp_run.py