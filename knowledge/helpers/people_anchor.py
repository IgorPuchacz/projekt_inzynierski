from knowledge.helpers.config import Anchor
import hashlib
import regex as re
import unicodedata
from knowledge.helpers import helpers
from typing import Optional, Tuple, List, Dict
from bs4 import BeautifulSoup, Tag, NavigableString
from input.neon_database.load_catalog import load_catalog, build_people_index
import urllib.parse
from knowledge.helpers.config import (
    MAILTO_IN_HREF_RX,
    EMAIL_PG_RX,
    TEL_IN_HREF_RX,
    PHONE_RX,
    COLOR_SCHEMES,
    COLOR_FALLBACK_ANCHOR,
    COLOR_FALLBACK_SEED,
    COLOR_FALLBACK_REGION,
)


def _scheme_index_for_id(per_id: Optional[str | int]) -> Optional[int]:
    """Maps per_id into colours"""
    if per_id is None:
        return None
    key = str(per_id).encode("utf-8")
    digest = hashlib.blake2s(key, digest_size=4).digest()
    num = int.from_bytes(digest, "big")
    return num % len(COLOR_SCHEMES)

def _apply_colors_to_anchors(anchors: List[Anchor]) -> None:
    """
    sets a.colors = {"anchor": ..., "seed": ..., "region": ...}
    """
    for a in anchors:
        idx = _scheme_index_for_id(getattr(a, "per_id", None))
        if idx is None:
            a.colors = {
                "anchor": COLOR_FALLBACK_ANCHOR,
                "seed":   COLOR_FALLBACK_SEED,
                "region": COLOR_FALLBACK_REGION,
            }
        else:
            hi, mid, low = COLOR_SCHEMES[idx]
            a.colors = {"anchor": hi, "seed": mid, "region": low}

def _is_inside_href(node: Tag | NavigableString, rx) -> bool:
    cur = node if isinstance(node, Tag) else node.parent
    while cur and isinstance(cur, Tag):
        href = cur.get("href")
        if href and rx.search(href):
            return True
        cur = cur.parent
    return False

def _is_inside_mailto(node: Tag | NavigableString) -> bool:
    return _is_inside_href(node, MAILTO_IN_HREF_RX)

def _is_inside_tel(node: Tag | NavigableString) -> bool:
    return _is_inside_href(node, TEL_IN_HREF_RX)

_LINE_CONTAINERS = {"p", "li", "dd", "dt"}

def _choose_wrap_node_for_person(soup: BeautifulSoup, span_node: Tag) -> Tag:
    """
    returns node with line containing full name:
    fragments between nearest <br> before and closest <br> after,
    around nearest container-line (eg. <p>, <li>).
    if <br> is not present or structure is strange – fallback: parent of span.
    """
    if not isinstance(span_node, Tag):
        return span_node


    cont = span_node.parent
    while isinstance(cont, Tag) and cont.name not in _LINE_CONTAINERS and cont.name not in {"body", "html"}:
        cont = cont.parent
    if not isinstance(cont, Tag) or cont.name in {"body", "html"}:

        return span_node.parent if isinstance(span_node.parent, Tag) else span_node


    top = span_node
    while isinstance(top.parent, Tag) and top.parent is not cont:
        top = top.parent


    children = list(cont.children)
    try:
        idx = children.index(top)
    except ValueError:
        return span_node.parent if isinstance(span_node.parent, Tag) else span_node


    start_i = 0
    end_i = len(children) - 1


    for i in range(idx, -1, -1):
        ch = children[i]
        if isinstance(ch, Tag) and ch.name == "br":
            start_i = i + 1
            break


    for j in range(idx, len(children)):
        ch = children[j]
        if isinstance(ch, Tag) and ch.name == "br":
            end_i = j - 1
            break


    line_nodes = [children[k] for k in range(start_i, end_i + 1)]
    if not line_nodes:
        return span_node.parent if isinstance(span_node.parent, Tag) else span_node


    wrapper = soup.new_tag("span")
    insert_ref = children[start_i]
    insert_ref.insert_before(wrapper)
    for node in line_nodes:
        wrapper.append(node.extract())

    return wrapper

def _iter_text_nodes(scope: Tag | BeautifulSoup):
    for tn in scope.find_all(string=True):
        if tn.parent and tn.parent.name in ("script", "style"):
            continue
        if tn and str(tn).strip():
            yield tn

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
    parent = tn.parent
    tn.replace_with(*parts)
    return span

def _ascii_fold(s: str) -> str:
    """lower + removes "ńćśążź", (NFKD) → ASCII-latin"""
    s = (s or "").strip().casefold()
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))

def _ascii_fold_with_map(s: str) -> Tuple[str, List[int]]:
    """
    return (norm text, mapa_normidx→origidx).
    Every normalised char points which index it originates from.
    """
    norm_chars: List[str] = []
    norm2orig: List[int] = []
    src = s or ""
    src_cf = src.casefold()
    for i, ch in enumerate(src_cf):
        decomp = unicodedata.normalize("NFKD", ch)
        for dch in decomp:
            if not unicodedata.combining(dch):
                norm_chars.append(dch)
                norm2orig.append(i)
    return "".join(norm_chars), norm2orig

def _norm_fullname_key(s: str) -> str:
    return " ".join(_ascii_fold(s).split())

def _build_name_regex_from_keys(keys: List[str]) -> re.Pattern:
    """
    keys -> already lowercase, ascii-folded (like in fullname_to_id).
    """
    if not keys:
        return re.compile(r"(?!x)x")
    uniq = sorted(set(keys), key=len, reverse=True)
    alt = "|".join(re.escape(k) for k in uniq)
    return re.compile(rf"(?<!\w)({alt})(?!\w)")

def _extract_tel_from_href(href: str) -> Optional[str]:
    """
    return number after 'tel:' from href (after percent-decoding), or None.
    """
    if not href:
        return None
    m = TEL_IN_HREF_RX.search(href)
    if not m:
        return None
    raw = m.group(1)
    raw = urllib.parse.unquote(raw)
    return raw.strip()


def _collect_text_person_names(
    soup: BeautifulSoup,
    fullname_to_id: Dict[str, str],
) -> List['Anchor']:
    out: List['Anchor'] = []
    if not fullname_to_id:
        return out

    rx = _build_name_regex_from_keys(list(fullname_to_id.keys()))

    for tn in _iter_text_nodes(soup):
        raw = str(tn)
        if not raw.strip():
            continue

        norm, n2o = _ascii_fold_with_map(raw)
        matches = list(rx.finditer(norm))
        if not matches:
            continue

        for m in reversed(matches):
            n_start = m.start(1)
            n_end = m.end(1)

            o_start = n2o[n_start]
            o_end = n2o[n_end - 1] + 1

            folded_name = " ".join(norm[n_start:n_end].split())
            person_id: Optional[str] = fullname_to_id.get(folded_name)
            if not person_id:
                key_guess = _norm_fullname_key(raw[o_start:o_end])
                person_id = fullname_to_id.get(key_guess)
            if not person_id:
                continue


            span = _split_text_node_with_span(
                soup=soup,
                tn=tn,
                start=o_start,
                end=o_end,
                kind="person_name",
            )


            wrap_node = _choose_wrap_node_for_person(soup, span)


            out.append(Anchor(
                name=None,
                kind="person_name",
                per_id=person_id,
                node=wrap_node,
                trigger_node=span,
                value=folded_name,
                source="det:name_regex",
                score=1.0,
            ))

    return out


def _collect_mailto_emails(soup: BeautifulSoup) -> List[Anchor]:
    out: List[Anchor] = []
    for a in soup.find_all("a"):
        href = a.get("href")
        if not href:
            continue
        m = MAILTO_IN_HREF_RX.search(href)
        if not m:
            continue
        val = helpers.normalize_email(m.group(1))
        out.append(Anchor(
            name=None,
            kind="email",
            per_id=None,
            node=a,
            trigger_node=a,
            value=val,
            source="det:mailto",
            score=1.0,
        ))
    return out

def _collect_text_emails(soup: BeautifulSoup) -> List[Anchor]:
    out: List[Anchor] = []
    for tn in _iter_text_nodes(soup):
        if _is_inside_mailto(tn):
            continue
        raw = str(tn)
        for m in EMAIL_PG_RX.finditer(raw):
            val = helpers.normalize_email(m.group(0))
            span = _split_text_node_with_span(soup, tn, m.start(0), m.end(0), kind="email")
            out.append(Anchor(
                name=None,
                kind="email",
                per_id=None,
                node=span,
                trigger_node=span,
                value=val,
                source="det:text",
                score=1.0,
            ))
    return out


def _collect_telhref_phones(soup: BeautifulSoup) -> List[Anchor]:
    out: List[Anchor] = []
    for a in soup.find_all("a"):
        href = a.get("href")
        raw_tel = _extract_tel_from_href(href or "")
        if not raw_tel:
            continue
        nsn9 = helpers.normalise_phone(raw_tel)
        if nsn9:
            out.append(Anchor(
                name=None,
                kind="phone",
                per_id=None,
                node=a,
                trigger_node=a,
                value=nsn9,
                source="det:telhref",
                score=1.0,
            ))
    return out

def _collect_text_phones(soup: BeautifulSoup) -> List[Anchor]:
    out: List[Anchor] = []
    for tn in _iter_text_nodes(soup):
        if _is_inside_tel(tn):
            continue
        raw = str(tn)
        for m in PHONE_RX.finditer(raw):
            nsn9 = helpers.normalise_phone(m.group(0))
            if not nsn9:
                continue
            span = _split_text_node_with_span(soup, tn, m.start(0), m.end(0), kind="phone")
            out.append(Anchor(
                name=None,
                kind="phone",
                per_id=None,
                node=span,
                trigger_node=span,
                value=nsn9,
                source="det:text",
                score=1.0,
            ))
    return out


def _attach_to_people(
    anchors: List[Anchor],
    people_index: Optional[Dict[str, Dict[str, str]]] = None
) -> Tuple[List[Anchor], List[Anchor]]:
    email_to_id = (people_index or {}).get("email_to_id") or {}
    phone_to_id = (people_index or {}).get("phone_to_id") or {}
    fullname_to_id = (people_index or {}).get("fullname_to_id") or {}
    id_to_fullname = (people_index or {}).get("id_to_fullname") or {}

    linked_anchors: List[Anchor] = []
    dropped: List[Anchor] = []

    for a in anchors:
        per_id: Optional[str] = getattr(a, "per_id", None)
        name: Optional[str] = getattr(a, "name", None)

        if a.kind == "email" and a.value:
            per_id = per_id or email_to_id.get(a.value.lower())
        elif a.kind == "phone" and a.value:
            per_id = per_id or phone_to_id.get(a.value)
        elif a.kind == "person_name" and a.value:
            per_id = per_id or fullname_to_id.get(a.value)


        if per_id and not name:
            name = id_to_fullname.get(per_id)

        a.per_id = per_id
        a.name = name

        if a.per_id is None:
            dropped.append(Anchor(
                name=None,
                kind=a.kind,
                per_id=None,
                node=a.node,
                trigger_node=a.trigger_node,
                value=a.value,
                source=(a.source or "det") + "|unlinked",
                score=a.score,
            ))
        else:
            linked_anchors.append(a)

    return linked_anchors, dropped


def find_people_anchors(soup: BeautifulSoup) -> Tuple[List[Anchor], List[Anchor]]:
    cat = load_catalog()
    people_index = build_people_index(cat)

    fullname_to_id = (people_index or {}).get("fullname_to_id") or {}
    all_candidates: List[Anchor] = []


    all_candidates += _collect_mailto_emails(soup)
    all_candidates += _collect_text_emails(soup)
    all_candidates += _collect_telhref_phones(soup)
    all_candidates += _collect_text_phones(soup)
    all_candidates += _collect_text_person_names(soup, fullname_to_id)

    anchors, dropped = _attach_to_people(all_candidates, people_index)

    _apply_colors_to_anchors(anchors)
    _apply_colors_to_anchors(dropped)

    return anchors, dropped