"""Model pool with LiteLLM Router integration for failover."""
# Lazy import: ModelPool is loaded on first attribute access (PEP 562)
# so that importing ol_pool.fake does NOT trigger litellm's heavy
# import chain (litellm → pydantic → importlib.metadata.entry_points()).
__all__ = ["ModelPool"]


def __getattr__(name: str):
    if name == "ModelPool":
        from ol_pool.router import ModelPool  # noqa: PLC0415
        return ModelPool
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
