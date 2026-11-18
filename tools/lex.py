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

def drop_long_parens(g, limit=40):
    """去掉太长的括号说明（支持嵌套）"""
    out, i = [], 0
    while i < len(g):
        if g[i] == "(":
            depth, j = 0, i
            while j < len(g):
                depth += (g[j] == "(") - (g[j] == ")")
                if depth == 0: break
                j += 1
            seg = g[i:j + 1]
            if len(seg) >= limit:
                while out and out[-1] == " ": out.pop()
            else: out.append(seg)
            i = j + 1
        else:
            out.append(g[i]); i += 1
    return "".join(out)

def clean_gloss(g):
    g = re.sub(r"\[[^\]]*\]", "", g)          # [+de ...] 之类的用法说明
    g = re.sub(r'^female equivalent of "[^"]+"\s*(?:\([^)]*\))?[,;:]?\s*', "", g)
    g = re.sub(r'^(?:\(before the noun\) )?apocopic form of "[^"]+"\s*(?:\([^)]*\))?[,;:]?\s*', "", g)
    g = re.sub(r"\((?:see usage notes|countable|uncountable|transitive|intransitive|pronominal)\)\s*", "", g)
    g = drop_long_parens(g)
    g = re.sub(r"^\((?:botany|zoology|anatomy|music|sports?|grammar|linguistics|cooking|biology|computing|medicine|law)\)\s*", "", g)
    return re.sub(r"\s+", " ", g).strip(" ;,")

SKIP_G = re.compile(r"^(senses relating to|plural of|feminine of|masculine of|(masculine|feminine) (singular|plural) of|(smart )?inflection of|alternative (form|spelling|case form)|superseded spelling|nonstandard (form|spelling)|uncommon form|obsolete|archaic|misspelling|pronunciation spelling|abbreviation|initialism|synonym of|eye dialect)", re.I)
REDIR = re.compile(r'^(?:alternative (?:form|spelling)|superseded spelling|misspelling|nonstandard (?:form|spelling)|pronunciation spelling|synonym|uncommon form|(?:masculine|feminine) (?:singular|plural)|feminine|plural|female equivalent|apocopic form) of "([^"]+)"', re.I)

BAD_Q = re.compile(r"obsolete|archaic|vulgar|rare|dated|derogatory|offensive|euphemis|dialectal|historical|slur|sexual|la vida|heraldry|Philippines|Rioplatense|Mexico|Chile|Argentina|Cuba|Peru|Colombia|Venezuela|Caribbean|Central America|Latin America|Andes|Bolivia|Ecuador|Uruguay|Paraguay|Puerto Rico|Dominican|Honduras|Guatemala|Nicaragua|El Salvador|Costa Rica|Panama|Canary", re.I)
BAD_G = re.compile(r"\b(cunnilingus|fellatio|orgasm|masturbat|ejaculat|copulat|intercourse|queer|bat for the other|fuck|penis|vagina|semen|cum|blowjob|prostitut|sex|whore|testicle|anus|arse)\w*", re.I)

def gloss(lemma, pos, n=3, _depth=0, strict=True):
    entries = W.get(lemma) or W.get(lemma.lower()) or []
    wp = POSMAP.get(pos)
    pref = [e for e in entries if e["pos"] in ALT_POS.get(wp, [wp])]
    if not pref and not strict: pref = entries
    good, fallback = [], []
    for e in pref:
        qs = e.get("q") or [""] * len(e["glosses"])
        for g, q in zip(e["glosses"], qs):
            if SKIP_G.match(g): continue
            g = clean_gloss(g)
            if not g: continue
            (fallback if (BAD_Q.search(q or "") or BAD_G.search(g)) else good).append(g)
    if not good and not fallback and _depth < 2:      # 只有“某词的异体/拼写”：转到那个词
        for e in pref:
            for g in e["glosses"]:
                m = REDIR.match(g)
                if m and m.group(1) != lemma:
                    r = gloss(m.group(1), pos, n, _depth + 1, strict=False)
                    if r: return r
    out = []
    for g in good + fallback[:1] if not good else good:
        if g not in out: out.append(g)
        if len(out) >= n: break
    return out

def gender(lemma):
    for e in W.get(lemma, []):
        if e["pos"] == "n" and e.get("g"): return e["g"]
    return None

# ---------------------------------------------------------------- 词形 → (原形, 词性) 的综合判断（2026-11 审校后重写）
WPOS = {"n", "v", "adj", "adv", "prep", "conj", "pron", "determiner", "interj", "art", "num", "contraction"}
def has_pos(lemma, wp):
    return any(e["pos"] == wp for e in (W.get(lemma) or []))
ALT_POS = {   # spaCy 词性 → 词典里可以接受的等价词性（按优先级）
    "determiner": ["determiner", "art", "adj", "pron"], "pron": ["pron", "determiner", "adj"],
    "adj": ["adj", "determiner"], "n": ["n"], "adv": ["adv"], "conj": ["conj"], "prep": ["prep", "contraction"],
    "interj": ["interj"], "v": ["v"],
}
SWITCH = {    # 词性在词典里查不到时，可以改判成的词性（按优先级）
    "adj": ["v", "n", "adv", "determiner"], "n": ["adj", "v", "adv", "interj"], "v": ["adj", "n", "interj", "adv"],
    "adv": ["adj", "conj", "prep", "pron", "interj"], "pron": ["adv", "determiner", "adj"], "determiner": ["pron", "adj", "adv"],
    "interj": ["v", "adv", "n", "adj"], "prep": ["adv", "conj"], "conj": ["adv", "prep"],
}
FIXED = {"contigo": ("contigo", "PRON"), "conmigo": ("conmigo", "PRON"), "consigo": ("consigo", "PRON"),
         "donde": ("donde", "ADV"), "dónde": ("dónde", "ADV"), "okey": ("okey", "INTJ"), "okay": ("okay", "INTJ"),
         "del": ("del", "ADP"), "al": ("al", "ADP"), "gracias": ("gracias", "INTJ"), "muy": ("muy", "ADV"), "sea": ("ser", "AUX"), "es": ("ser", "AUX"), "y": ("y", "CCONJ"), "e": ("e", "CCONJ")}
BACK = {"n": "NOUN", "v": "VERB", "adj": "ADJ", "adv": "ADV", "prep": "ADP", "conj": "CCONJ", "pron": "PRON",
        "determiner": "DET", "art": "DET", "interj": "INTJ", "contraction": "ADP", "num": "NUM"}

def masc_sing(form):
    c = [form]
    if form.endswith("as"): c += [form[:-2] + "o", form[:-1], form[:-2]]
    if form.endswith("os"): c += [form[:-1]]
    if form.endswith("a"): c += [form[:-1] + "o", form[:-1]]
    if form.endswith("es"): c += [form[:-2], form[:-1]]
    if form.endswith("s"): c += [form[:-1]]
    for a, b in (("ía", "ío"),):
        if form.endswith(a): c.append(form[:-len(a)] + b)
    return c

PERS_PRON = set("ella ellas ellos ello nosotros nosotras vosotros vosotras la las los le les lo usted ustedes me te se nos os mí ti conmigo contigo".split())
def resolve(text, lemma, pos):
    """返回 (原形, spaCy 风格词性, 是否是过去分词形容词)；查不到返回 (None, pos, False)"""
    form = text.lower()
    wp = POSMAP.get(pos)
    sl = (lemma or "").lower().split(" ")[0]
    if not wp or pos in ("PROPN", "NUM"): return None, pos, False
    if form in FIXED: return FIXED[form][0], FIXED[form][1], False
    known = FORMS.get(form, {})
    for p in ALT_POS.get(wp, [wp]):
        cands = [c for c in known.get(p, []) if has_pos(c, p)]
        if has_pos(form, p) and form not in cands: cands.append(form)
        if cands:
            best = sl if sl in cands else min(cands, key=lambda c: FREQ.get((c, wp), FREQ.get(c, 10**6)))
            if p == "pron" and form in cands and form in PERS_PRON: best = form          # ella / ellos / nosotras 本身就是词条
            return best, pos, False
        if p in ("adj", "n", "determiner", "pron"):
            for c in masc_sing(form):
                if has_pos(c, p): return c, pos, False
    if not known and sl and has_pos(sl, wp):            # 词典里没有这个词形（如带代词的 cuéntame），相信 spaCy
        return sl, pos, False
    # 词性在词典里对不上：先看是不是过去分词当形容词用
    if wp in ("adj", "n") and "v" in known and re.search(r"(ad|id|íd|ech|ich|ist|uest|iert|uelt|crit|ort)[oa]s?$", form):
        return known["v"][0], pos, True
    for p in SWITCH.get(wp, []):
        cands = [c for c in known.get(p, []) if has_pos(c, p)]
        if cands:
            best = sl if sl in cands else min(cands, key=lambda c: FREQ.get((c, p), FREQ.get(c, 10**6)))
            return best, BACK[p], False
    if sl and has_pos(sl, wp): return sl, pos, False
    return None, pos, False
