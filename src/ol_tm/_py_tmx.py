"""Pure-Python TMX 1.4 reader/writer stub for ``ol_tm.service``.

Why this exists
---------------
The installed ``hypomnema`` package (version 0.8) is an alpha, typed
domain-model library. It exposes ``TranslationMemory`` /
``TranslationUnit`` / ``TranslationVariant`` dataclasses and
loader/dumper classes — but no ``TMXFile`` convenience class.

The OL translation-memory service (``ol_tm.service``) was written
against the simpler legacy ``TMXFile(path)`` API and only needs four
operations:

* ``__init__(path)``                        — bind to a file path
* ``unit_iterator()``                       — yield TUs with
  ``get_source_segment()`` / ``get_target_segment()``
* ``add_unit(source, target)``              — append one translation pair
* ``write()``                               — persist the in-memory list

This module provides a minimal stub implementing exactly that contract.
It is installed onto the ``hypomnema`` module as ``hypomnema.TMXFile``
by ``ol_tm.service`` at import time, so the existing call sites in
``_load()`` and ``_save()`` work unchanged. Tests can still
``monkeypatch.setattr(hypomnema, "TMXFile", mock)`` because the install
is conditional and reverts cleanly.

Implementation notes
--------------------
* Uses the standard library ``xml.etree.ElementTree`` — no extra
  dependencies.
* Supports TMX 1.4 with a single ``<header>`` and ``<body>`` per file.
* ``source_lang`` / ``target_lang`` are read from the file on
  ``unit_iterator()`` and used by ``write()`` for the next save.
* Construction is lazy: the file is only opened by ``unit_iterator()``.
* The stub is **not** a general TMX 1.4 reader — it understands only
  the structure it writes. Foreign TMX files with namespaces, ``<note>``
  children, multiple ``<tuv>`` per language, or other TMX 1.4 features
  may not round-trip cleanly. Sufficient for OL's translation memory
  use case (source/target pair per TU).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree as ET

# xml:lang is bound to the well-known XML namespace in TMX 1.4.
# ElementTree requires the Clark-notation full name to round-trip it.
_XML_NS_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

# Defaults for newly-created (empty) TMX files.
_DEFAULT_SOURCE_LANG = "en"
_DEFAULT_TARGET_LANG = "en"


class _TranslationUnit:
    """Minimal TU object exposing the two methods ``service._load`` calls.

    The hypomnema-legacy API used ``get_source_segment()`` and
    ``get_target_segment()`` on each yielded unit; this stub provides
    exactly that surface.
    """

    __slots__ = ("_source", "_target")

    def __init__(self, source: str, target: str) -> None:
        self._source = source
        self._target = target

    def get_source_segment(self) -> str:
        return self._source

    def get_target_segment(self) -> str:
        return self._target


class TMXFile:
    """TMX 1.4 reader/writer stub compatible with the legacy API.

    Behavior summary:

    * ``__init__(path)`` binds the path and initializes empty state.
      The file is **not** read.
    * ``unit_iterator()`` lazily parses the on-disk TMX file (if it
      exists and is non-empty) and yields ``_TranslationUnit`` objects.
      The first call also updates ``source_lang`` / ``target_lang`` from
      the file's ``<header srclang=...>`` and the first non-source
      ``<tuv xml:lang=...>``.
    * ``add_unit(source, target)`` appends a pair to the in-memory
      list. Pairs added this way are what ``write()`` will serialize —
      the on-disk file is *not* consulted during ``write()``.
    * ``write()`` serializes the in-memory list as a TMX 1.4 document
      (with a single ``<header>`` and ``<body>``). Parent directories
      are created if missing.
    """

    source_lang: str = _DEFAULT_SOURCE_LANG
    target_lang: str = _DEFAULT_TARGET_LANG

    def __init__(self, path) -> None:
        self._path = Path(path)
        self._units: list[tuple[str, str]] = []

    # -- read path ---------------------------------------------------------

    def unit_iterator(self) -> Iterator[_TranslationUnit]:
        """Yield translation units parsed lazily from the on-disk file.

        Empty / missing / unparseable files yield nothing. On a
        successful read, ``self.source_lang`` is set to the file's
        ``<header srclang=...>`` and ``self.target_lang`` to the
        ``xml:lang`` of the first ``<tuv>`` whose language differs
        from the source.
        """
        if not self._path.exists() or self._path.stat().st_size == 0:
            return
        try:
            tree = ET.parse(self._path)
        except ET.ParseError:
            return
        root = tree.getroot()

        # Discover source language from the first <header>.
        src_lang = self.source_lang
        for header in root.iter("header"):
            hdr_srclang = header.get("srclang")
            if hdr_srclang:
                src_lang = hdr_srclang
            break  # only the first header counts

        for tu in root.iter("tu"):
            src_seg: str | None = None
            tgt_seg: str | None = None
            tgt_lang: str | None = None
            for tuv in tu.findall("tuv"):
                lang = (
                    tuv.get(_XML_NS_LANG)
                    or tuv.get("lang")
                )
                seg_text = ""
                seg = tuv.find("seg")
                if seg is not None and seg.text is not None:
                    seg_text = seg.text
                if lang == src_lang and src_seg is None:
                    src_seg = seg_text
                elif lang is not None and lang != src_lang:
                    if tgt_seg is None:
                        tgt_seg = seg_text
                        tgt_lang = lang
            if src_seg is not None and tgt_seg is not None:
                self.source_lang = src_lang
                if tgt_lang is not None:
                    self.target_lang = tgt_lang
                yield _TranslationUnit(src_seg, tgt_seg)

    # -- write path --------------------------------------------------------

    def add_unit(self, source: str, target: str) -> None:
        """Append a translation pair to the in-memory unit list."""
        self._units.append((source, target))

    def write(self) -> None:
        """Serialize the in-memory unit list to disk as TMX 1.4 XML.

        Existing files are overwritten. The on-disk file is **not**
        consulted — only the pairs previously passed to ``add_unit``
        are written.
        """
        # Make sure the parent directory exists so the first save
        # against a fresh path (e.g. "build/tm.tmx") doesn't fail.
        self._path.parent.mkdir(parents=True, exist_ok=True)

        tmx = ET.Element("tmx", {"version": "1.4"})
        ET.SubElement(
            tmx,
            "header",
            {
                "creationtool": "OL-TM",
                "creationtoolversion": "1.0",
                "segtype": "sentence",
                "o-tmf": "OL-TM",
                "adminlang": self.source_lang,
                "srclang": self.source_lang,
                "datatype": "plaintext",
            },
        )
        body = ET.SubElement(tmx, "body")
        for idx, (source, target) in enumerate(self._units, start=1):
            tu = ET.SubElement(body, "tu", {"tuid": str(idx)})
            tuv_src = ET.SubElement(
                tu, "tuv", {_XML_NS_LANG: self.source_lang}
            )
            ET.SubElement(tuv_src, "seg").text = source
            tuv_tgt = ET.SubElement(
                tu, "tuv", {_XML_NS_LANG: self.target_lang}
            )
            ET.SubElement(tuv_tgt, "seg").text = target

        # ET.tostring with xml_declaration=True only works with str
        # output; build the declaration manually to keep the encoding
        # explicit and the output diff-friendly.
        payload = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
            tmx, encoding="utf-8"
        )
        self._path.write_bytes(payload)


__all__ = ["TMXFile"]
