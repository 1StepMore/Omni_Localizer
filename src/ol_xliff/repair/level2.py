try:
    from span_aligner import SpanProjector
    _has_span_aligner = True
except ImportError:
    _has_span_aligner = False


import logging

_logger = logging.getLogger(__name__)


def level2_span_align(
    text: str, shield_map: dict, original: str
) -> tuple[str, bool]:
    """Apply L2 span alignment to `text`. Returns (text, l2_applied).

    l2_applied=True: span_aligner was available AND the L2 repair
    succeeded; `text` is the L2-repaired output.
    l2_applied=False: span_aligner unavailable OR L2 raised; `text`
    is the upstream text (graceful degradation).
    """
    if not _has_span_aligner:
        return text, False
    # Force HF offline mode so the network call fails immediately instead of
    # retrying 1-5 times with backoff (saves ~5s per unit on 3503-unit files).
    # We restore the previous value in finally to avoid leaking the override
    # to other HF users in the same process.
    import os
    old_offline = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        projector = SpanProjector()
        return projector.project(text, shield_map, original), True
    except Exception as e:
        _logger.warning(
            "L2 span_aligner unavailable, falling back to upstream text: %s", e
        )
        return text, False
    finally:
        if old_offline is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = old_offline
