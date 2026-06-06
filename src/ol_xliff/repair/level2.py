try:
    from span_aligner import SpanProjector
    _has_span_aligner = True
except ImportError:
    _has_span_aligner = False


def level2_span_align(text: str, shield_map: dict, original: str) -> str:
    if not _has_span_aligner:
        return text
    # Force HF offline mode so the network call fails immediately instead of
    # retrying 1-5 times with backoff (saves ~5s per unit on 3503-unit files).
    # We restore the previous value in finally to avoid leaking the override
    # to other HF users in the same process.
    import os
    old_offline = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        projector = SpanProjector()
        return projector.project(text, shield_map, original)
    except Exception as e:
        # SpanProjector downloads its model from HF; in hermetic / offline envs
        # this fails. L4 safe-fallback in XLIFFRepairPipeline.repair() handles it.
        import logging
        logging.getLogger(__name__).debug(
            "L2 span_aligner unavailable, falling back to upstream text: %s", e
        )
        return text
    finally:
        if old_offline is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = old_offline
