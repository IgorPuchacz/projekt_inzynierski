from __future__ import annotations
from pathlib import Path
import os, json, re, hashlib, unicodedata
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, quote
from dotenv import load_dotenv
load_dotenv()
import psycopg
from psycopg.rows import dict_row

BASE_DIR = Path(__file__).resolve().parent
CATALOG_DIR = BASE_DIR / "neon_data"
CATALOG_DIR.mkdir(parents=True, exist_ok=True)

PEOPLE_JSON      = CATALOG_DIR / "people.json"
UNITS_JSON       = CATALOG_DIR / "units.json"
PROCEDURES_JSON  = CATALOG_DIR / "procedures.json"
CATALOG_JSON      = CATALOG_DIR / "catalog.json"


def as_psycopg_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url.split("postgresql+psycopg://", 1)[1]
    parts = urlsplit(url)
    if "@" in parts.netloc:
        creds, host = parts.netloc.split("@", 1)
        if ":" in creds:
            user, pwd = creds.split(":", 1)
            creds = f"{user}:{quote(pwd, safe='')}"
        netloc = f"{creds}@{host}"
    else:
        netloc = parts.netloc
    q = parts.query
    if "sslmode=" not in q:
        q = "sslmode=require" if not q else q + "&sslmode=require"
    return urlunsplit((parts.scheme, netloc, parts.path, q, parts.fragment))

def connect_db() -> psycopg.Connection:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("❌ Brak zmiennej środowiskowej DATABASE_URL")
    return psycopg.connect(as_psycopg_url(db_url), row_factory=dict_row)


_WS_RE = re.compile(r"\s+")
_NON_DIGIT_RE = re.compile(r"\D+")

def fold_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = _WS_RE.sub(" ", s).strip()
    return s

def phone_to_nsn9(s: str) -> Optional[str]:
    if not s:
        return None
    digits = _NON_DIGIT_RE.sub("", s)
    if len(digits) >= 9:
        return digits[-9:]
    return None

def split_multi(value: Optional[str]) -> List[str]:
    if not value:
        return []
    out = []
    for x in re.split(r"[;,\n]+", value):
        z = (x or "").strip()
        if z:
            out.append(z)
    return out

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def atomic_write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

def sha1_of_obj(obj: Any) -> str:
    data = json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha1(data).hexdigest()


def load_people(conn: psycopg.Connection) -> List[Dict[str, Any]]:
    """
    employee + active employment (valid_to IS NULL):
    - email/phone/room/role we take from employment table, aggregate and deduplicate.
    """

    emp_rows = conn.execute("""
        SELECT employee_id, full_name, first_name, last_name, degree, email, phone, room
        FROM employee
        ORDER BY last_name, first_name
    """).fetchall()


    job_rows = conn.execute("""
        SELECT employee_id, unit_id, role, room, work_email, work_phone
        FROM employment
        WHERE valid_to IS NULL
        ORDER BY employee_id
    """).fetchall()

    by_emp: Dict[int, Dict[str, Any]] = {}
    for r in emp_rows:
        pid = int(r["employee_id"])
        full = (r["full_name"] or "").strip() or f"{(r['first_name'] or '').strip()} {(r['last_name'] or '').strip()}".strip()
        by_emp[pid] = {
            "person_id": pid,
            "full_name": full,
            "first_name": (r["first_name"] or "").strip(),
            "last_name": (r["last_name"] or "").strip(),
            "degree": r.get("degree"),
            "emails": [],
            "phones_nsn9": [],
            "room": r.get("room"),
            "role": None,
            "name_folded": [],
        }


    for j in job_rows:
        pid = int(j["employee_id"])
        if pid not in by_emp:
            by_emp[pid] = {
                "person_id": pid, "full_name": "", "first_name": "", "last_name": "", "degree": None,
                "emails": [], "phones_nsn9": [], "room": None, "role": None, "name_folded": []
            }
        p = by_emp[pid]
        if j.get("room"):
            p["room"] = j["room"]
        if j.get("role"):
            p["role"] = j["role"]


        for em in split_multi(j.get("work_email")):
            eml = em.strip().lower()
            if eml and eml not in p["emails"]:
                p["emails"].append(eml)
        ph = j.get("work_phone")
        for phx in split_multi(ph):
            nsn = phone_to_nsn9(phx)
            if nsn and nsn not in p["phones_nsn9"]:
                p["phones_nsn9"].append(nsn)


    for p in by_emp.values():
        display = p["full_name"] or f"{p['first_name']} {p['last_name']}".strip()
        folded = set()
        if display:
            a = fold_text(display)
            folded.add(a)
            parts = a.split()
            if len(parts) >= 2:
                imie = parts[0]
                nazw = " ".join(parts[1:])
                folded.add(f"{nazw} {imie}")
        p["name_folded"] = sorted(folded)


    return sorted(by_emp.values(), key=lambda x: (x["last_name"], x["first_name"], x["person_id"]))

def load_units(conn: psycopg.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute("""
        SELECT unit_id, name, parent_id
        FROM unit
        ORDER BY unit_id
    """).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "unit_id": int(r["unit_id"]),
            "name": (r["name"] or "").strip(),
            "parent_id": int(r["parent_id"]) if r["parent_id"] is not None else None,
            "label_folded": fold_text(r["name"] or ""),
        })
    return out

def load_procedures(conn: psycopg.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute("""
        SELECT proc_id, name
        FROM procedure_def
        ORDER BY proc_id
    """).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        nm = (r["name"] or "").strip()
        out.append({
            "proc_id": int(r["proc_id"]),
            "name": nm,
            "alias_folded": [fold_text(nm)] if nm else [],
        })
    return out


def build_people_catalog(people: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    by_email: Dict[str, int] = {}
    by_phone: Dict[str, int] = {}
    by_name:  Dict[str, int] = {}
    for p in people:
        pid = p["person_id"]
        for em in p["emails"]:
            by_email[em] = pid
        for ph in p["phones_nsn9"]:
            by_phone[ph] = pid
        for nf in p["name_folded"]:
            by_name[nf] = pid
    return {"by_email": by_email, "by_phone": by_phone, "by_name": by_name}

def build_units_catalog(units: List[Dict[str, Any]]) -> Dict[str, int]:
    return {u["label_folded"]: u["unit_id"] for u in units if u["label_folded"]}

def build_procedures_catalog(procs: List[Dict[str, Any]]) -> Dict[str, int]:
    by_alias: Dict[str, int] = {}
    for pr in procs:
        for a in pr.get("alias_folded", []):
            if a:
                by_alias[a] = pr["proc_id"]
    return by_alias


def main() -> None:
    print("Connecting with Neon")
    with connect_db() as conn:
        print("Downloading people/units/procedures")
        people = load_people(conn)
        units  = load_units(conn)
        procs  = load_procedures(conn)

    meta = {
        "version": now_iso(),
        "counts": {"people": len(people), "units": len(units), "procedures": len(procs)},
    }


    atomic_write_json(PEOPLE_JSON,     {"meta": meta, "people": people})
    atomic_write_json(UNITS_JSON,      {"meta": meta, "units": units})
    atomic_write_json(PROCEDURES_JSON, {"meta": meta, "procedures": procs})


    people_cat = build_people_catalog(people)
    units_cat  = build_units_catalog(units)
    procs_cat  = build_procedures_catalog(procs)
    anchor_catalog = {
        "people": people_cat,
        "units": {"by_label": units_cat},
        "procedures": {"by_alias": procs_cat},
        "meta": {
            **meta,
            "sha1": sha1_of_obj({"people": people_cat, "units": units_cat, "procedures": procs_cat})
        }
    }
    atomic_write_json(CATALOG_JSON, anchor_catalog)

    print("Ready")
    print(f"   -> {PEOPLE_JSON}")
    print(f"   -> {UNITS_JSON}")
    print(f"   -> {PROCEDURES_JSON}")
    print(f"   -> {CATALOG_JSON}")

if __name__ == "__main__":
    main()