# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Purpose matching: rank jobs for one person by skill fit, mission fit and preferences.

Local and free. The default engine is BM25 over job text (no model downloads, no
API keys). If MATCH_EMBEDDINGS=true and the optional `sentence-transformers`
package is installed, a local embedding model is blended in for semantic recall.

Score (0-100) = 45% skills + 35% mission/values + 20% preferences, then nudged by
the person's own save/dismiss feedback. Every match carries plain-language reasons.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, Optional, Sequence

_WORD = re.compile(r"[a-z0-9][a-z0-9+#.\-]*[a-z0-9+#]|[a-z0-9]")
STOP = set("""a an and are as at be but by for from has have i in is it its of on or our that the their them they
this to was we were will with you your who what when where which while about into over more most other such than
then there these those through under up very can do does just not no only own same so some all any both each few
how why us also may must per via etc using use work working team role job jobs experience years year join help
across within new make makes making based including include strong ability skills skill""".split())

# Cause -> signal terms seen in company sectors, names and job text.
CAUSES: dict[str, set[str]] = {
    "climate": {"climate", "carbon", "decarbonization", "renewable", "solar", "wind", "battery", "batteries",
                "energy", "emissions", "sustainability", "sustainable", "clean", "cleantech", "grid", "ev",
                "electrification", "net-zero", "circular"},
    "health": {"health", "healthcare", "medical", "patient", "patients", "clinical", "biotech", "therapeutics",
               "drug", "hospital", "care", "mental", "wellbeing", "disease", "diagnostics", "nurse"},
    "education": {"education", "edtech", "learning", "learners", "students", "student", "teachers", "school",
                  "schools", "tutor", "tutoring", "curriculum", "literacy", "university", "pedagogy"},
    "financial inclusion": {"inclusion", "unbanked", "microfinance", "credit", "lending", "fintech",
                            "affordable", "savings", "payments", "underserved", "entrepreneurs"},
    "poverty": {"poverty", "cash", "transfers", "livelihoods", "refugee", "refugees", "humanitarian",
                "development", "ngo", "nonprofit", "non-profit", "charity", "underserved"},
    "ai safety": {"alignment", "safety", "interpretability", "responsible", "trustworthy", "evals",
                  "robustness", "governance", "frontier"},
    "science": {"research", "science", "scientific", "discovery", "physics", "biology", "chemistry", "lab",
                "mathematics", "math", "astronomy", "materials"},
    "civic tech": {"government", "civic", "public", "democracy", "policy", "nonprofit", "community",
                   "accessibility", "open-source", "transparency", "justice"},
    "food & agriculture": {"food", "agriculture", "agtech", "farmers", "farming", "nutrition", "hunger",
                           "crops", "supply"},
    "accessibility": {"accessibility", "accessible", "disability", "disabilities", "assistive", "inclusive"},
    "open source": {"open-source", "opensource", "oss", "community", "maintainers", "linux", "apache"},
    "housing": {"housing", "homes", "affordable", "rent", "renters", "homelessness", "shelter"},
    "conservation": {"conservation", "wildlife", "biodiversity", "ocean", "oceans", "forest", "forests",
                     "nature", "water"},
}
_CAUSE_ALIASES = {"environment": "climate", "climate change": "climate", "healthcare": "health",
                  "mental health": "health", "edu": "education", "learning": "education",
                  "ai alignment": "ai safety", "alignment": "ai safety", "safety": "ai safety",
                  "fintech": "financial inclusion", "nonprofit": "poverty", "global development": "poverty",
                  "government": "civic tech", "democracy": "civic tech", "agriculture": "food & agriculture",
                  "food": "food & agriculture", "oss": "open source", "nature": "conservation"}

W_SKILL, W_MISSION, W_PREF, W_FEEDBACK = 0.45, 0.35, 0.20, 0.15


def tokenize(text: str) -> list[str]:
    return [t for t in _WORD.findall((text or "").lower()) if t not in STOP and len(t) > 1]


def phrases(text: str) -> list[str]:
    """Split a comma/semicolon/newline separated field into lowercase phrases."""
    return [p.strip().lower() for p in re.split(r"[,;\n]", text or "") if p.strip()]


def canonical_cause(c: str) -> str:
    c = c.strip().lower()
    return _CAUSE_ALIASES.get(c, c)


class BM25:
    """Okapi BM25 over a fixed corpus of token lists."""

    def __init__(self, docs: Sequence[Sequence[str]], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = (sum(self.len) / len(self.len)) if self.len else 0.0
        df: Counter = Counter()
        for d in self.tf:
            df.update(d.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, query: Iterable[str], i: int) -> float:
        tf, dl, s = self.tf[i], self.len[i], 0.0
        norm = self.k1 * (1 - self.b + self.b * dl / (self.avg or 1))
        for t in set(query):
            f = tf.get(t)
            if f:
                s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / (f + norm)
        return s


_MONEY = re.compile(r"(?i)(?:\$|usd|€|eur|£|gbp)\s?(\d{1,3}(?:[,.]\d{3})+|\d+(?:\.\d+)?)\s*(k)?")


def parse_salary(text: str) -> Optional[tuple[int, int]]:
    """Best-effort yearly salary range from posting text (e.g. "$120k–$150k", "Salary: 90,000–110,000 USD")."""
    vals = []
    for m in _MONEY.finditer(text or ""):
        v = float(m.group(1).replace(",", "").replace(".", "") if re.search(r"[,.]\d{3}", m.group(1))
                  else m.group(1))
        if m.group(2):
            v *= 1000
        if 10_000 <= v <= 2_000_000:
            vals.append(int(v))
    if not vals:
        m = re.search(r"Salary:\s*([\d,]+)(?:–([\d,]+))?", text or "")
        if m:
            vals = [int(x.replace(",", "")) for x in m.groups() if x]
            vals = [v for v in vals if 10_000 <= v <= 2_000_000]
    if not vals:
        return None
    return min(vals), max(vals)


@dataclass
class Profile:
    skills: str = ""
    experience: str = ""
    values: str = ""
    causes: str = ""
    desired_impact: str = ""
    location: str = ""
    remote_preference: str = "any"
    comp_floor: int = 0


@dataclass
class JobDoc:
    id: int
    title: str
    company: str = ""
    location: str = ""
    description: str = ""
    remote: bool = False
    sector: str = ""
    url: str = ""
    source: str = ""


@dataclass
class Match:
    job: JobDoc
    score: float
    parts: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def why(self) -> str:
        return " ".join(self.reasons)


def _doc_tokens(j: JobDoc) -> list[str]:
    # Title and sector count extra: they say the most about what the work is.
    return tokenize(f"{j.title} {j.title} {j.sector} {j.sector} {j.company} {j.location} {j.description[:6000]}")


def _norm(xs: list[float]) -> list[float]:
    top = max(xs) if xs else 0.0
    return [x / top if top > 0 else 0.0 for x in xs]


class _Embedder:
    """Optional local sentence-embedding model; disabled unless installed and enabled."""

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # optional dependency
        self.model = SentenceTransformer(model_name)

    def sims(self, query: str, docs: list[str]) -> list[float]:
        import numpy as np
        q = self.model.encode([query], normalize_embeddings=True)
        d = self.model.encode(docs, normalize_embeddings=True, batch_size=64)
        return [max(0.0, float(x)) for x in (d @ q[0])]


@lru_cache(maxsize=2)
def get_embedder(model_name: str) -> Optional[_Embedder]:
    try:
        return _Embedder(model_name)
    except Exception:
        return None


def _hits(terms: Iterable[str], tokens: set[str], text: str) -> list[str]:
    out = []
    for t in terms:
        tt = tokenize(t)
        if not tt:
            continue
        if (len(tt) == 1 and tt[0] in tokens) or (len(tt) > 1 and t in text):
            out.append(t)
    return out


def rank(profile: Profile, jobs: Sequence[JobDoc], *, saved: Sequence[JobDoc] = (),
         dismissed_ids: Iterable[int] = (), dismissed: Sequence[JobDoc] = (), limit: int = 20,
         embedder: Optional[_Embedder] = None) -> list[Match]:
    dismissed_ids = set(dismissed_ids)
    pool = [j for j in jobs if j.id not in dismissed_ids]
    if profile.remote_preference == "remote":
        pool = [j for j in pool if j.remote]
    if not pool:
        return []
    docs = [_doc_tokens(j) for j in pool]
    bm = BM25(docs)
    skill_terms = phrases(profile.skills)
    skill_q = tokenize(profile.skills + " " + profile.experience)
    causes = [canonical_cause(c) for c in phrases(profile.causes)]
    cause_terms = set().union(*(CAUSES.get(c, set(tokenize(c))) for c in causes)) if causes else set()
    mission_q = tokenize(" ".join([profile.values, profile.desired_impact, " ".join(causes)])) + list(cause_terms)

    skill_raw = [bm.score(skill_q, i) for i in range(len(pool))] if skill_q else [0.0] * len(pool)
    mission_raw = [bm.score(mission_q, i) for i in range(len(pool))] if mission_q else [0.0] * len(pool)
    skill_n, mission_n = _norm(skill_raw), _norm(mission_raw)

    if embedder is not None:
        texts = [f"{j.title}. {j.company}. {j.sector}. {j.description[:1500]}" for j in pool]
        if skill_q:
            sem = embedder.sims(profile.skills + ". " + profile.experience, texts)
            skill_n = [0.6 * a + 0.4 * b for a, b in zip(skill_n, sem)]
        if mission_q:
            sem = embedder.sims(". ".join([profile.values, profile.desired_impact, profile.causes]), texts)
            mission_n = [0.6 * a + 0.4 * b for a, b in zip(mission_n, sem)]

    # Feedback: terms from saved jobs pull similar jobs up; dismissed-job terms push down.
    pos = Counter(t for j in saved for t in set(_doc_tokens(j)))
    neg = Counter(t for j in dismissed for t in set(_doc_tokens(j)))
    fb_terms = {t: pos[t] - neg[t] for t in set(pos) | set(neg) if pos[t] != neg[t]}
    fb_q_pos = [t for t, v in fb_terms.items() if v > 0]
    fb_q_neg = [t for t, v in fb_terms.items() if v < 0]
    fb_pos = _norm([bm.score(fb_q_pos, i) for i in range(len(pool))]) if fb_q_pos else [0.0] * len(pool)
    fb_neg = _norm([bm.score(fb_q_neg, i) for i in range(len(pool))]) if fb_q_neg else [0.0] * len(pool)

    loc_terms = set(tokenize(profile.location))
    out: list[Match] = []
    for i, j in enumerate(pool):
        tokens = set(docs[i])
        text = f"{j.title} {j.sector} {j.company} {j.description[:6000]}".lower()
        reasons: list[str] = []

        # Preferences: work arrangement, location, pay floor.
        pref, pref_n = 0.0, 0
        if profile.remote_preference in ("remote", "hybrid", "onsite"):
            pref_n += 1
            if profile.remote_preference == "remote" or (profile.remote_preference == "hybrid" and j.remote):
                pref += 1.0
                reasons.append("It's remote, as you prefer.")
            elif profile.remote_preference == "onsite" and not j.remote:
                pref += 1.0
        if loc_terms:
            pref_n += 1
            if loc_terms & set(tokenize(j.location)):
                pref += 1.0
                reasons.append(f"It's in {j.location}, where you want to be.")
            elif j.remote:
                pref += 0.7
        sal = parse_salary(j.description)
        if profile.comp_floor:
            pref_n += 1
            if sal and sal[1] >= profile.comp_floor:
                pref += 1.0
                reasons.append(f"Listed pay ({sal[0]:,}–{sal[1]:,}) meets your {profile.comp_floor:,} floor.")
            elif sal:
                reasons.append(f"Heads up: listed pay ({sal[0]:,}–{sal[1]:,}) is below your "
                               f"{profile.comp_floor:,} floor.")
            else:
                pref += 0.5  # unknown pay: neutral
        pref_s = pref / pref_n if pref_n else 0.5

        skill_hits = _hits(skill_terms, tokens, text)
        if skill_hits:
            reasons.insert(0, f"Uses your skills in {', '.join(skill_hits[:5])}.")
        matched_causes = [c for c in causes if CAUSES.get(c, set(tokenize(c))) & tokens]
        sector_l = j.sector.lower()
        sector_causes = [c for c in causes if c in sector_l or (CAUSES.get(c) and set(tokenize(sector_l)) & CAUSES[c])]
        mission = mission_n[i]
        if sector_causes:
            mission = min(1.0, mission + 0.25)
        if matched_causes or sector_causes:
            names = list(dict.fromkeys(sector_causes + matched_causes))
            where = f"{j.company or 'This organization'}" + (f" ({j.sector})" if j.sector else "")
            reasons.insert(1 if skill_hits else 0,
                           f"{where} works on {', '.join(names[:3])}, a cause you care about.")
        value_hits = _hits(phrases(profile.values) + phrases(profile.desired_impact), tokens, text)
        if value_hits:
            reasons.append(f"The posting speaks to what you value: {', '.join(value_hits[:3])}.")

        fb = fb_pos[i] - fb_neg[i]
        if fb > 0.3:
            reasons.append("It's similar to jobs you saved.")
        elif fb < -0.3:
            reasons.append("It's similar to jobs you dismissed, so it's ranked lower.")

        total = W_SKILL * skill_n[i] + W_MISSION * mission + W_PREF * pref_s + W_FEEDBACK * fb
        if not reasons:
            reasons.append("A broad match; add skills and causes to your profile for sharper results.")
        out.append(Match(j, round(max(0.0, min(1.0, total)) * 100, 1),
                         {"skills": round(skill_n[i], 3), "mission": round(mission, 3),
                          "preferences": round(pref_s, 3), "feedback": round(fb, 3)}, reasons))
    out.sort(key=lambda m: (-m.score, -m.job.id))
    return out[:limit]
