from __future__ import annotations
from typing import Dict, List, Tuple, Optional
from bs4 import BeautifulSoup, Tag, NavigableString
from input.neon_database.load_catalog import load_catalog
from knowledge.helpers.people_anchor import find_people_anchors
from knowledge.helpers.config import Anchor
import unicodedata
import regex as re


try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None




BLOCK_TAGS = {
    "p","li","dd","dt","td","th","div","article","section",
    "header","footer","aside","main","nav","h1","h2","h3","h4","h5","h6"
}

def _iter_blocks(scope: Tag | BeautifulSoup):
    """Iterate by 'block' nodes to run locally and not through whole page."""
    for t in scope.find_all(True):
        if t.name in BLOCK_TAGS and t.get_text(strip=True):
            yield t

def _iter_text_nodes(tag: Tag):
    for tn in tag.find_all(string=True):
        p = tn.parent
        if not p or p.name in ("script","style"):
            continue
        s = str(tn)
        if s.strip():
            yield tn

def _ascii_fold(s: str) -> str:
    s = (s or "").casefold()
    decomp = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in decomp if not unicodedata.combining(ch))

def _ascii_fold_with_map(s: str):
    norm_chars, norm2orig = [], []
    s_cf = (s or "").casefold()
    for i, ch in enumerate(s_cf):
        for dch in unicodedata.normalize("NFKD", ch):
            if not unicodedata.combining(dch):
                norm_chars.append(dch)
                norm2orig.append(i)
    return "".join(norm_chars), norm2orig

def _build_alt_regex(keys: List[str]) -> re.Pattern:
    if not keys:
        return re.compile(r"(?!x)x")
    uniq = sorted(set(keys), key=len, reverse=True)
    alt = "|".join(re.escape(k) for k in uniq)
    return re.compile(rf"(?<!\w)({alt})(?!\w)")

def _split_text_node_with_span(soup: BeautifulSoup, tn: NavigableString, start: int, end: int, kind: str) -> Tag:
    raw = str(tn)
    before, mid, after = raw[:start], raw[start:end], raw[end:]
    span = soup.new_tag("span")
    span.string = mid
    span["data-annot"] = kind
    parts: List[object] = []
    if before: parts.append(NavigableString(before))
    parts.append(span)
    if after: parts.append(NavigableString(after))
    tn.replace_with(*parts)
    return span

def _norm_key(s: str) -> str:
    return " ".join(_ascii_fold(s).split())

def _best_token_ratio(a: str, b: str) -> float:
    """return [0..1] probability. rapidfuzz if available, or simple proportion of token match."""
    if fuzz:
        return fuzz.token_set_ratio(a, b) / 100.0
    ta = set(_ascii_fold(a).split())
    tb = set(_ascii_fold(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)



def doesHaveCoverage(text: str, acronym: str) -> bool:
    """
    STUB
    """
    return True



def _det_in_tag_for_map(
    soup: BeautifulSoup,
    tag: Tag,
    fold_map: Dict[str, int],
    kind: str,
    source_label: str,
    id_to_name: Optional[Dict[int, str]] = None,
) -> List[Anchor]:
    """DET: match alias by fold, cut exact span."""
    out: List[Anchor] = []
    if not fold_map:
        return out

    rx = _build_alt_regex(list(fold_map.keys()))

    for tn in _iter_text_nodes(tag):
        raw = str(tn)
        norm, n2o = _ascii_fold_with_map(raw)
        matches = list(rx.finditer(norm))
        if not matches:
            continue

        for m in reversed(matches):
            ns, ne = m.start(1), m.end(1)
            os, oe = n2o[ns], n2o[ne - 1] + 1
            folded = " ".join(norm[ns:ne].split())
            the_id = fold_map.get(folded)
            if the_id is None:
                continue

            span = _split_text_node_with_span(soup, tn, os, oe, kind=kind)
            name = id_to_name.get(the_id) if id_to_name else None

            out.append(Anchor(
                name=name,
                kind=kind,
                per_id=str(the_id),
                node=span,
                trigger_node=span,
                value=raw[os:oe],
                source=f"det:{source_label}",
                score=None,
            ))
    return out


def _fuzz_in_tag_for_map(
    tag: Tag,
    fold_map: Dict[str, int],
    aliases_by_id: Dict[int, List[str]],
    require_acronym_ok: Optional[Dict[int, List[str]]] = None,
    fuzz_threshold: float = 0.85,
) -> Optional[Tuple[int, str, float]]:
    """
    return best (id, alias_matched, score) for given tag tagu or None.
    if require_acronym_ok does have content for given id,
    then fuzzy accepts only if doesHaveCoverage(text, acronim) == True.
    """
    text = tag.get_text(" ", strip=True)
    if not text:
        return None

    best = None
    for the_id, aliases in aliases_by_id.items():
        for alias in aliases:
            sc = _best_token_ratio(text, alias)
            if sc > (best[2] if best else 0.0):
                best = (the_id, alias, sc)

    if not best or best[2] < fuzz_threshold:
        return None

    the_id, alias, sc = best

    if require_acronym_ok and the_id in require_acronym_ok:
        acrs = require_acronym_ok[the_id] or []
        if acrs:
            ok = any(doesHaveCoverage(text, a) for a in acrs)
            if not ok:
                return None

    return best


def find_units_and_procedures_anchors(soup: BeautifulSoup, catalog) -> List[Anchor]:
    """
    DET: aliasy/etykiety po foldzie; wrap tylko dokładny span.
    FUZZ: if nothing found in DET tag – pick best alias > 0.85;
          if procedure has acronym/s, fuzzy requires coverage (stub).
    """
    anchors: List[Anchor] = []


    units_by_label: Dict[str, int] = getattr(catalog, "units_by_label", {}) or {}
    procs_by_alias: Dict[str, int] = getattr(catalog, "procs_by_alias", {}) or {}


    proc_id_to_name: Dict[int, str] = getattr(catalog, "proc_id_to_name", {}) or {}
    unit_id_to_name: Dict[int, str] = getattr(catalog, "unit_id_to_name", {}) or {}

    procs_acronyms: Dict[int, List[str]] = getattr(catalog, "procs_acronyms", {}) or {}


    units_fold = {_norm_key(k): v for k, v in units_by_label.items()}
    procs_fold = {_norm_key(k): v for k, v in procs_by_alias.items()}


    aliases_per_unit: Dict[int, List[str]] = {}
    for k, uid in units_fold.items():
        aliases_per_unit.setdefault(uid, []).append(k)

    aliases_per_proc: Dict[int, List[str]] = {}
    for k, pid in procs_fold.items():
        aliases_per_proc.setdefault(pid, []).append(k)


    for block in _iter_blocks(soup):
        det_u = _det_in_tag_for_map(
            soup, block, units_fold, kind="unit", source_label="label",
            id_to_name=unit_id_to_name
        )
        det_p = _det_in_tag_for_map(
            soup, block, procs_fold, kind="procedure", source_label="alias",
            id_to_name=proc_id_to_name
        )

        if det_u or det_p:
            anchors.extend(det_u)
            anchors.extend(det_p)
            continue


        best_p = _fuzz_in_tag_for_map(
            block, procs_fold, aliases_per_proc,
            require_acronym_ok=procs_acronyms,
            fuzz_threshold=0.85,
        )
        if best_p:
            pid, alias_used, score = best_p
            span_node = block
            anchors.append(Anchor(
                name=proc_id_to_name.get(pid),
                kind="procedure",
                per_id=str(pid),
                node=span_node,
                trigger_node=span_node,
                value=alias_used,
                source="fuzz:alias" + ("+acron" if pid in procs_acronyms and procs_acronyms[pid] else ""),
                score=round(float(score), 3),
            ))
            continue


        best_u = _fuzz_in_tag_for_map(
            block, units_fold, aliases_per_unit,
            require_acronym_ok=None,
            fuzz_threshold=0.85,
        )
        if best_u:
            uid, alias_used, score = best_u
            span_node = block
            anchors.append(Anchor(
                name=unit_id_to_name.get(uid),
                kind="unit",
                per_id=str(uid),
                node=span_node,
                trigger_node=span_node,
                value=alias_used,
                source="fuzz:label",
                score=round(float(score), 3),
            ))

    return anchors



def find_anchors(soup: BeautifulSoup) -> Tuple[List[Anchor], List[Anchor]]:
    """
    1) people
    2) units + procedures (DET → FUZZ)
    """
    cat = load_catalog()
    people_anchors, dropped_people = find_people_anchors(soup)
    up_anchors = find_units_and_procedures_anchors(soup, cat)
    anchors = people_anchors + up_anchors
    return anchors, dropped_people