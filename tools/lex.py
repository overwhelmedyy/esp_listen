"""词形 → 原形（用 Wiktionary 全词形表纠正 spaCy 的原形），以及词义查询"""
import csv, json, re, os, collections
POSMAP = {"NOUN": "n", "PROPN": "prop", "VERB": "v", "AUX": "v", "ADJ": "adj", "ADV": "adv",
          "ADP": "prep", "CCONJ": "conj", "SCONJ": "conj", "PRON": "pron", "DET": "determiner",
          "INTJ": "interj", "NUM": "num"}
FORMS = collections.defaultdict(lambda: collections.defaultdict(list))   # form -> pos -> [lemma]
for row in csv.reader(open("/tmp/sd/es_allforms.csv", encoding="utf-8")):
    if len(row) < 3: continue
    form, pos, *lemmas = row
    FORMS[form][pos] += lemmas
FREQ = {}
for i, row in enumerate(csv.DictReader(open("/tmp/sd/frequency.csv", encoding="utf-8"))):
    FREQ.setdefault((row["spanish"], row["pos"]), i)
    FREQ.setdefault(row["spanish"], i)
W = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "wikt.json") if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "wikt.json")) else "/home/claude/ann/wikt.json", encoding="utf-8"))

def fix_lemma(text, lemma, pos):
    form = text.lower()
    wp = POSMAP.get(pos)
    sl = lemma.lower().split(" ")[0]
    if pos in ("PROPN", "NUM", "PUNCT", "SYM", "X", "SPACE"):
        return sl
    cands = []
    if wp and wp in FORMS.get(form, {}):
        cands = FORMS[form][wp]
    elif pos in ("ADJ",) and "v" in FORMS.get(form, {}):     # 过去分词当形容词：cansadas → cansado
        pass
    if not cands and form in FORMS:
        # 词性不匹配时：DET/PRON 互通，ADJ/NOUN 互通
        alt = {"determiner": ["art", "pron", "adj"], "pron": ["determiner", "art"], "adj": ["n", "v"], "n": ["adj"],
               "adv": ["adj", "conj"], "conj": ["adv", "prep"]}.get(wp, [])
        for a in alt:
            if a in FORMS[form]:
                cands = FORMS[form][a]; break
    if not cands:
        return sl if sl and sl != "_" else form
    if sl in cands:
        return sl
    return min(cands, key=lambda c: FREQ.get((c, wp), FREQ.get(c, 10**6)))

def rank(lemma, pos):
    return FREQ.get((lemma, POSMAP.get(pos, "")), FREQ.get(lemma, 10**6))

def clean_gloss(g):
    g = re.sub(r"\[[^\]]*\]", "", g)          # [+de ...] 之类的用法说明
    g = re.sub(r"\s*\((?:[^()]*)\)", lambda m: m.group(0) if len(m.group(0)) < 40 else "", g)
    return re.sub(r"\s+", " ", g).strip(" ;,")

SKIP_G = re.compile(r"^(plural of|feminine of|masculine of|alternative form|obsolete|archaic|misspelling|pronunciation spelling|abbreviation|initialism|synonym of|eye dialect)", re.I)

BAD_Q = re.compile(r"obsolete|archaic|vulgar|rare|dated|derogatory|offensive|euphemis|dialectal|historical|slur|sexual|la vida|nautical|heraldry|botany|zoology|anatomy|law|military|medicine|chemistry|mathematics|physics|computing|religion|Philippines|Rioplatense|Mexico|Chile|Argentina|Cuba|Peru|Colombia|Venezuela|Caribbean|Central America|Latin America|Andes|Bolivia|Ecuador|Uruguay|Paraguay|Puerto Rico|Dominican|Honduras|Guatemala|Nicaragua|El Salvador|Costa Rica|Panama|Canary", re.I)
BAD_G = re.compile(r"\b(fuck|penis|vagina|semen|cum|blowjob|prostitut|sex|whore|testicle|anus|arse)\w*", re.I)

def gloss(lemma, pos, n=3):
    entries = W.get(lemma) or W.get(lemma.lower()) or []
    wp = POSMAP.get(pos)
    pref = [e for e in entries if e["pos"] == wp] or entries
    good, fallback = [], []
    for e in pref:
        qs = e.get("q") or [""] * len(e["glosses"])
        for g, q in zip(e["glosses"], qs):
            if SKIP_G.match(g): continue
            g = clean_gloss(g)
            if not g: continue
            (fallback if (BAD_Q.search(q or "") or BAD_G.search(g)) else good).append(g)
    out = []
    for g in good + fallback[:1] if not good else good:
        if g not in out: out.append(g)
        if len(out) >= n: break
    return out

def gender(lemma):
    for e in W.get(lemma, []):
        if e["pos"] == "n" and e.get("g"): return e["g"]
    return None
