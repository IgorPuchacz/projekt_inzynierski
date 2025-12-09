import re, urllib.parse
from typing import Optional

def normalise_phone(raw: str | None) -> Optional[str]:
    """
    From string like '+48 58 347 12 34', '58 347-12-34 wew. 123'
    extracts 9-digit polish NSN (National Significant Number), eg. '583471234'.
    return None, if <9 numbers

    Rules:
    - cuts sections like 'wew.', 'w.', 'ext', 'extension', 'x', or after ';'
    - removes everything besides numbers
    - removes international prefix like '00' and country code like '48'
    - return last 9 digits, if >= 9 digits
    """
    if not raw:
        return None

    s = str(raw).replace("\xa0", " ").strip()


    s = re.split(r'(?i)(?:\bwew\.?\b|\bw\.?\b|\bext\.?\b|\bextension\b|\bx\b|;|#)', s, maxsplit=1)[0]


    digits = re.findall(r'\d+', s)
    if not digits:
        return None
    nums = ''.join(digits)


    if nums.startswith('00'):
        nums = nums[2:]


    if nums.startswith('48') and len(nums) >= 11:
        nums = nums[2:]


    if len(nums) < 9:
        return None

    nsn9 = nums[-9:]
    return nsn9

def normalize_email(s: str) -> str:
    s = (s or "").strip().lower()
    s = urllib.parse.unquote(s)
    return s

def norm_hyphens(s: str) -> str:
    return re.sub(r"\s*[\-\u2010\u2011\u2012\u2013\u2014\u2212]\s*", "-", s)
