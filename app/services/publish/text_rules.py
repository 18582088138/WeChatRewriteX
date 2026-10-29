"""保守的普通 X 帖文分段；URL 不拆开，复杂 emoji 按上界计数。

规则依据 https://docs.x.com/fundamentals/counting-characters 。
此处不宣称替代官方 twitter-text 校验，发布时仍以平台编辑器为准。
"""
import re
import unicodedata

_URL = r"(?:https?://|www\.)[^\s<>]+|(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:/[^\s<>]*)?"
_URL_END = ".,!?;:…。，！？；：、\"')]}"


def units(text: str) -> list[str]:
    tokens = re.findall(_URL + r"|.", unicodedata.normalize("NFC", text), re.S)
    grouped: list[str] = []
    for token in tokens:
        if grouped and len(token) == 1 and (unicodedata.combining(token) or
                token in ("\u200d", "\ufe0f", "\ufe0e") or grouped[-1].endswith("\u200d") or
                0x1F3FB <= ord(token) <= 0x1F3FF):
            grouped[-1] += token
        else:
            grouped.append(token)
    return grouped


def weight(unit: str) -> int:
    if re.fullmatch(_URL, unit):
        # Keep the entire URL unit intact but budget trailing punctuation separately.
        # Ambiguous bare domains are conservatively treated as URLs too.
        suffix = unit[len(unit.rstrip(_URL_END)):]
        return 23 + sum(weight(c) for c in suffix)
    return sum(1 if (ord(c) <= 0x10FF or 0x2000 <= ord(c) <= 0x200D or
                    0x2010 <= ord(c) <= 0x201F or 0x2032 <= ord(c) <= 0x2037) else 2 for c in unit)


def weighted_length(text: str) -> int:
    return sum(weight(u) for u in units(text))


def split_x(text: str, budget: int = 276) -> list[str]:
    out, chunk, used = [], "", 0
    for unit in units(text):
        size = weight(unit)
        if size > budget:
            raise ValueError("X 正文含过长的连续 emoji 序列，请缩短后重试")
        if used + size > budget:
            out.append(chunk.strip())
            chunk, used = "", 0
        chunk += unit
        used += size
    if chunk.strip():
        out.append(chunk.strip())
    return out


def truncate_x(text: str, budget: int) -> str:
    if weighted_length(text) <= budget:
        return text
    out, used = "", 0
    for unit in units(text):
        size = weight(unit)
        if used + size > budget - 2:
            break
        out += unit
        used += size
    return out.rstrip() + "…"
