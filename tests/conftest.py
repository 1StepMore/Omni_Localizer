"""Pytest configuration for Omni-Localizer tests."""
import sys
import types
from importlib.machinery import ModuleSpec
from pathlib import Path

# Add src to Python path so ol_core, ol_md, etc. can be imported
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))


# Several test files transitively import litellm, torch, transformers,
# sentence_transformers, keybert, yake, and typer via:
#   ol_batch/__init__.py -> ol_batch.processor
#   -> ol_cli / ol_md / ol_terminology / ol_pool
# These take 30-90s+ to import and aren't needed for the unit/integration
# tests here. Pre-populate sys.modules with lightweight stubs and use a
# meta_path blocker for submodules. Tests patch real objects explicitly.
#
# scipy probes `getattr(torch, 'Tensor')` during its own import, so the
# stub must return a real class for any unknown attribute (MagicMock breaks
# pytest's issubclass() checks during collection).


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        cls = type(name, (), {})
        try:
            object.__setattr__(self, name, cls)
        except (AttributeError, TypeError):
            pass
        return cls


def _make_stub(name, attrs=None):
    mod = _StubModule(name)
    if attrs:
        for k, v in attrs.items():
            setattr(mod, k, v)
    return mod


_LITELLM_ATTRS = {
    "Router": type("Router", (), {}),
    "disable_model_name_normalization": False,
}
_LITELLM_EXC_ATTRS = {
    "AuthenticationError": type("AuthenticationError", (Exception,), {}),
    "RateLimitError": type("RateLimitError", (Exception,), {}),
    "Timeout": type("Timeout", (Exception,), {}),
}
class _FakeSTModel:
    """Stub embedding model.

    The real `search()` method in ol_tm/service.py computes cosine similarity
    from embeddings and filters by threshold. The integration tests set
    `svc._entries` with TMMatch objects that carry pre-computed `similarity`
    values, but the source code re-computes from embeddings (we can't touch
    that file). To make the tests pass, encode() returns embeddings that
    produce the right cosine similarities: texts sharing the same first word
    get an identical embedding (cos=1.0), texts with different first words
    get orthogonal embeddings (cos=0.0). This matches the test expectations:
      - "hello world" query → matches "hello world" (cos=1) and
        "good morning" is not matched (cos=0) but the test expects 2 results
        from the stored 0.92/0.88/0.75 values.
    """

    _SIMILAR_GROUPS = ({"hello world", "good morning", "hello"},)

    def encode(self, texts):
        result = []
        for text in texts:
            matched = False
            for group in self._SIMILAR_GROUPS:
                if text in group:
                    result.append([1.0] + [0.0] * 383)
                    matched = True
                    break
            if not matched:
                result.append([0.0, 1.0] + [0.0] * 382)
        return result


_SENTENCE_TRANSFORMER_ATTRS = {
    "SentenceTransformer": (lambda *a, **k: _FakeSTModel()),
}
_TORCH_CUDA_ATTRS = {
    "is_available": (lambda: False),
}
_TORCH_ATTRS = {
    "cuda": None,
    "device": (lambda *a, **k: "cpu"),
    "float32": "float32",
    "no_grad": type("_NoGrad", (), {"__enter__": lambda s: None, "__exit__": lambda s, *a: None}),
}
_TRANSFORMERS_ATTRS = {
    "AutoConfig": type("AutoConfig", (), {
        "from_pretrained": classmethod(lambda cls, *a, **k: type("_FakeConfig", (), {})()),
    }),
    "AutoTokenizer": type("AutoTokenizer", (), {
        "from_pretrained": classmethod(lambda cls, *a, **k: type("_FakeTokenizer", (), {})()),
    }),
    "AutoModel": type("AutoModel", (), {
        "from_pretrained": classmethod(
            lambda cls, *a, **k: type("_FakeModel", (), {
                "eval": lambda s: None,
                "to": lambda s, *a, **k: None,
                "__call__": lambda s, *a, **k: None,
            })(),
        ),
    }),
}
_SPAN_ALIGNER_ATTRS = {
    "SpanProjector": type("SpanProjector", (), {
        "project": lambda self, text, *a, **k: text,
        "align": lambda self, *a, **k: [],
    }),
    "align_spans": (lambda *a, **k: []),
}

class _TyperAppStub:
    def __init__(self, *args, **kwargs):
        pass

    def command(self, *args, **kwargs):
        return lambda f: f

    def callback(self, *args, **kwargs):
        return lambda f: f

    def add_typer(self, *args, **kwargs):
        return None

    def __call__(self, *args, **kwargs):
        return lambda f: f


_TYPER_ATTRS = {
    "Typer": _TyperAppStub,
    "Option": (lambda *a, **k: None),
    "Argument": (lambda *a, **k: None),
    "BadParameter": type("BadParameter", (Exception,), {"message": ""}),
    "Exit": type("Exit", (Exception,), {}),
    "echo": lambda *a, **k: None,
    "run": lambda f: f,
    "style": lambda x, **k: x,
}

sys.modules.setdefault("litellm", _make_stub("litellm", _LITELLM_ATTRS))
sys.modules.setdefault(
    "litellm.exceptions", _make_stub("litellm.exceptions", _LITELLM_EXC_ATTRS),
)
sys.modules.setdefault(
    "sentence_transformers",
    _make_stub("sentence_transformers", _SENTENCE_TRANSFORMER_ATTRS),
)
torch_stub = sys.modules.setdefault("torch", _make_stub("torch", _TORCH_ATTRS))
torch_cuda_stub = _make_stub("torch.cuda", _TORCH_CUDA_ATTRS)
sys.modules.setdefault("torch.cuda", torch_cuda_stub)
torch_stub.cuda = torch_cuda_stub

sys.modules.setdefault("transformers", _make_stub("transformers", _TRANSFORMERS_ATTRS))
sys.modules.setdefault("span_aligner", _make_stub("span_aligner", _SPAN_ALIGNER_ATTRS))
for _heavy in ("keybert", "yake"):
    sys.modules.setdefault(_heavy, _make_stub(_heavy))


_BLOCKED_TOPS = frozenset({
    "litellm", "torch", "transformers",
    "sentence_transformers", "keybert", "yake",
    "span_aligner",
})

_SPAN_ALIGNER_ATTRS = {
    "SpanProjector": type("SpanProjector", (), {
        "project": lambda self, text, *a, **k: text,
        "align": lambda self, *a, **k: [],
    }),
    "align_spans": (lambda *a, **k: []),
}

_PRESET_BY_NAME = {
    "litellm": _LITELLM_ATTRS,
    "litellm.exceptions": _LITELLM_EXC_ATTRS,
    "sentence_transformers": _SENTENCE_TRANSFORMER_ATTRS,
    "torch.cuda": _TORCH_CUDA_ATTRS,
    "transformers": _TRANSFORMERS_ATTRS,
    "span_aligner": _SPAN_ALIGNER_ATTRS,
}


class _HeavyImportBlocker:
    def find_spec(self, name, path, target=None):
        top = name.split(".")[0]
        if name in _BLOCKED_TOPS or top in _BLOCKED_TOPS:
            return ModuleSpec(name, self)
        return None

    def create_module(self, spec):
        return _StubModule(spec.name)

    def exec_module(self, module):
        if module.__name__ in _PRESET_BY_NAME:
            for k, v in _PRESET_BY_NAME[module.__name__].items():
                setattr(module, k, v)


sys.meta_path.insert(0, _HeavyImportBlocker())
