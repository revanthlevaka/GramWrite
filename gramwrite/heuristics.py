"""
heuristics.py — Fast heuristic pipelines for GramWrite
Tense detection, word-level diff, and confidence scoring.
"""

from __future__ import annotations
import re
import difflib

# ── Confidence Calculator ───────────────────────────────────────────────────

def calculate_confidence(original: str, correction: str) -> str:
    """
    Heuristics based confidence scoring.
    Minimal differences (e.g. punctuation, 1 character) -> LOW
    Moderate differences -> MEDIUM
    Structural/Major differences -> HIGH
    """
    if original == correction:
        return "LOW"
    
    dist = calculate_edit_distance(original, correction)
    
    if dist <= 2:
        return "LOW"
    elif dist <= 5:
        return "MEDIUM"
    return "HIGH"

def calculate_edit_distance(s1: str, s2: str) -> int:
    """Fast, basic edit distance metric matching difflib."""
    matcher = difflib.SequenceMatcher(None, s1, s2)
    dist = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            dist += max(i2 - i1, j2 - j1)
        elif tag == "insert":
            dist += j2 - j1
        elif tag == "delete":
            dist += i2 - i1
    return dist

# ── Diff Generator ──────────────────────────────────────────────────────────

def generate_diff_html(original: str, correction: str) -> str:
    """
    Generate word-level inline diff.
    Returns Original text and Corrected text with modified words highlighted in green.
    """
    # Split by word boundaries keeping whitespace
    words_orig = re.split(r'(\s+)', original)
    words_corr = re.split(r'(\s+)', correction)
    
    matcher = difflib.SequenceMatcher(None, words_orig, words_corr)
    
    html_parts = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            html_parts.append("".join(words_corr[j1:j2]))
        elif tag in ('replace', 'insert'):
            # Highlight added/replaced text
            segment = "".join(words_corr[j1:j2])
            # Only wrap if it's not purely whitespace
            if segment.strip():
                html_parts.append(f"<span style='color: #4CAF50; font-weight: normal;'>{segment}</span>")
            else:
                html_parts.append(segment)
        elif tag == 'delete':
            # Highlight deleted text in red and strike-through.
            # But the prompt said "Highlight ONLY modified words" in the context of "Corrected text".
            # "Show original text \n Show corrected text \n Highlight ONLY modified words"
            # It implies highlighting what was added. We'll simply omit deletions from the unified view 
            # if we are showing the fully corrected text.
            pass
            
    corrected_html = "".join(html_parts).replace("\n", "<br>")
    orig_html = original.replace("\n", "<br>")
    
    # We will format it so the UI can display:
    # Original: <text>
    # Suggestion: <highlighted text>
    diff_html = (
        f"<div style='color: rgba(120, 120, 130, 255); font-size: 13px; margin-bottom: 6px;'>"
        f"<s>{orig_html}</s></div>"
        f"<div>{corrected_html}</div>"
    )
    return diff_html

# ── Present Tense Enforcement ───────────────────────────────────────────────

_IRREGULAR_VERBS = {
    r"\bwas\b": "is", r"\bwere\b": "are", r"\bhad\b": "has",
    r"\bran\b": "runs", r"\bwalked\b": "walks", r"\bsang\b": "sings",
    r"\bwent\b": "goes", r"\bcame\b": "comes", r"\bsaw\b": "sees",
    r"\bthought\b": "thinks", r"\bfelt\b": "feels", r"\bheard\b": "hears",
    r"\bknew\b": "knows", r"\blet\b": "lets", r"\bleft\b": "leaves",
    r"\bstood\b": "stands", r"\btook\b": "takes", r"\bgave\b": "gives",
    r"\bgot\b": "gets", r"\bmade\b": "makes", r"\bheld\b": "holds",
    r"\bkept\b": "keeps", r"\bcaught\b": "catches", r"\bbrought\b": "brings",
    r"\bbegan\b": "begins", r"\bdid\b": "does", r"\bspoke\b": "speaks",
    r"\bwrote\b": "writes", r"\bdrank\b": "drinks", r"\bswam\b": "swims"
}

_CONTINUOUS_PAST_REGEX = re.compile(r"\b(was|were)\s+([a-z]+ing)\b", re.IGNORECASE)
_PAST_PERFECT_REGEX = re.compile(r"\bhad\s+([a-z]+(ed|en|n))\b", re.IGNORECASE)
# Basic -ed verbs (heuristically strip ed -> add s)
# Example: jumped -> jumps, looked -> looks
_ED_VERB_REGEX = re.compile(r"\b([a-z]{3,})(ed)\b", re.IGNORECASE)

def enforce_present_tense(text: str) -> tuple[str, str]:
    """
    Convert action lines to present tense.
    Returns (corrected_text, confidence)
    """
    original = text
    confidence = "LOW"
    
    # 1. Continuous past: "was running" -> "runs"
    # To keep it simple heuristically, we just remove the 'was ' and 'were ' for -ing. 
    # Actually "was running" -> "is running" is safer than turning to "runs" algorithmically.
    def replace_continuous(m):
        nonlocal confidence
        confidence = "HIGH"
        return "is " + m.group(2)
    text = _CONTINUOUS_PAST_REGEX.sub(replace_continuous, text)
    
    # 2. Past perfect: "had gone" -> "has gone", "had walked" -> "has walked"
    def replace_perfect(m):
        nonlocal confidence
        confidence = "HIGH"
        return "has " + m.group(1)
    text = _PAST_PERFECT_REGEX.sub(replace_perfect, text)
    
    # 3. Known irregular verbs
    for past_regex, present in _IRREGULAR_VERBS.items():
        if re.search(past_regex, text, re.IGNORECASE):
            text = re.sub(past_regex, present, text, flags=re.IGNORECASE)
            confidence = "HIGH"
            
    # 4. Standard -ed verbs
    def replace_ed(m):
        nonlocal confidence
        if confidence == "LOW":
            confidence = "MEDIUM" # somewhat ambiguous, could be adjective
        base = m.group(1)
        # e.g., 'look' -> 'looks', 'jump' -> 'jumps'
        if base.endswith('e'):
            return base + "s"
        elif base.endswith(('s', 'sh', 'ch', 'x', 'z')):
            return base + "es"
        elif base.endswith('y') and len(base) > 2 and base[-2] not in 'aeiou':
            return base[:-1] + "ies"
        return base + "s"
        
    text = _ED_VERB_REGEX.sub(replace_ed, text)
    
    if text == original:
        return text, "LOW"
    return text, confidence
