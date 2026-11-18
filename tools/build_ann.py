"""
Build per-episode annotation files web/ann/<n>.json and the shared word list web/lex.json
from spaCy output.  All annotation text is in English.

Inputs:
  nlp/<n>.json      output of nlp_pass.py: one token list per paragraph
                    token = [text, whitespace, lemma, pos, morph, dep, head, sent_start]
  transcripts.json  (only used to know which episodes exist)
  phrase_blacklist.txt  optional: Wiktionary multi-word entries that should not be shown

Annotations per token:
  l  → lex.json entry (base form, part of speech, English meaning)
  v  verb form (mood · tense · person) + usage hint
  c  gender/number class for colouring (ms / fs / mp / fp)
  o  object role (od = direct, oi = indirect) and r = explanation / referent
  g  → notes (grammar structures "g" and fixed expressions "c")
"""
import json, re, os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lex import fix_lemma, gloss, POSMAP, W, BAD_Q, BAD_G, resolve, FORMS
from verbtag import correct as correct_verb

HERE = os.path.dirname(os.path.abspath(__file__))
NLP = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/ann/nlp"
WEB = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "web")

# ---------------------------------------------------------------- morphology
def morph(m):
    return dict(kv.split("=", 1) for kv in m.split("|") if "=" in kv)

MOOD = {"Ind": "Indicative", "Sub": "Subjunctive", "Imp": "Imperative", "Cnd": "Conditional"}
TENSE = {"Pres": "present", "Past": "preterite", "Imp": "imperfect", "Fut": "future"}
PERSON = {("1", "Sing"): "1st person singular (yo)", ("2", "Sing"): "2nd person singular (tú)",
          ("3", "Sing"): "3rd person singular (él / ella / usted)", ("1", "Plur"): "1st person plural (nosotros)",
          ("2", "Plur"): "2nd person plural (vosotros)", ("3", "Plur"): "3rd person plural (ellos / ellas / ustedes)"}
TENSE_HINT = {
    ("Ind", "Pres"): "Actions happening now, habits and general truths.",
    ("Ind", "Past"): "Completed actions at a specific point in the past (pretérito indefinido).",
    ("Ind", "Imp"): "Background description, ongoing or habitual actions in the past (pretérito imperfecto).",
    ("Ind", "Fut"): "Future actions; also used to guess about the present (será = it's probably…).",
    ("Cnd", None): "\"Would…\": hypothetical results, polite requests, or guesses about the past.",
    ("Sub", "Pres"): "Used in clauses expressing wishes, doubt, emotion, purpose, etc.",
    ("Sub", "Imp"): "Past subjunctive: subjunctive clauses in a past context, or unreal conditions (si + past subjunctive).",
    ("Imp", None): "Commands, requests, advice; object pronouns attach to the end (dímelo).",
}

TAGNAME = {("Ind", "Pres"): "present", ("Ind", "Past"): "preterite", ("Ind", "Imp"): "imperfect", ("Ind", "Fut"): "future",
           ("Cnd", None): "conditional", ("Sub", "Pres"): "present subjunctive", ("Sub", "Imp"): "past subjunctive", ("Imp", None): "imperative"}
def same_form_note(tags):
    """同一个词形还可以是别的时态（hablamos = 现在时 / 过去时）：提醒一句。人称不同的不提（hable = yo / él）。"""
    first = tags[0]
    if len(first) < 4: return ""
    others = []
    for t in tags[1:]:
        if len(t) < 4 or t[:2] == first[:2]: continue
        pair = {first[0], t[0]}
        if pair == {"Ind", "Imp"} or pair == {"Sub", "Imp"}: continue      # cuenta (él / ¡tú!)、hable (que él / ¡usted!) 太常见，不提
        name = TAGNAME.get(t[:2])
        if name and name not in others: others.append(name)
    return ("Same spelling is also the " + " / ".join(others) + "; context decides.") if others else ""

def verb_desc(m, tags=None):
    vf = m.get("VerbForm")
    if vf == "Inf": return "Infinitive"
    if vf == "Ger": return "Gerund (-ando / -iendo): \"…ing\""
    if vf == "Part": return "Past participle"
    mood = m.get("Mood"); tense = m.get("Tense")
    if not mood: return None
    if mood == "Cnd":
        parts = ["Conditional"]
    elif mood == "Imp":
        parts = ["Imperative"]
    else:
        t = "past" if (mood == "Sub" and tense in ("Imp", "Past")) else TENSE.get(tense, tense or "")
        parts = [f"{MOOD.get(mood, mood)} {t}".strip()]
    p = PERSON.get((m.get("Person"), m.get("Number")))
    if p: parts.append(p)
    if mood == "Sub" and tense == "Past": tense = "Imp"
    hint = TENSE_HINT.get((mood, tense)) or TENSE_HINT.get((mood, None))
    extra = same_form_note(tags) if tags else ""
    if extra: hint = (hint + " " if hint else "") + extra
    return " · ".join(parts) + ("\n" + hint if hint else "")

NOUN_G = {"performance": "Fem", "tilde": "Fem", "pijama": "Masc", "macro": "Fem"}   # 依据 Collins 修正
def noun_gender(lemma):
    if lemma not in NOUN_G:
        gs = {x.get("g") for x in W.get(lemma, []) if x["pos"] == "n" and x.get("g")}
        NOUN_G[lemma] = {"m": "Masc", "f": "Fem", "m-p": "Masc", "f-p": "Fem"}.get(gs.pop()) if len(gs) == 1 else None
    return NOUN_G[lemma]

def gn_class(tok, lemma=None):
    text, ws, _, pos, m = tok[0], tok[1], tok[2], tok[3], morph(tok[4])
    if pos not in ("NOUN", "ADJ", "DET", "PRON", "VERB"): return None
    if pos == "VERB" and m.get("VerbForm") != "Part": return None
    if pos == "PRON" and m.get("PronType") == "Prs" and m.get("Person") in ("1", "2"): return None
    g, n = m.get("Gender"), m.get("Number")
    if pos == "NOUN" and lemma:
        dg = noun_gender(lemma)               # 名词的性以词典为准（spaCy 偶尔判错）
        if dg: g = dg
    if g not in ("Masc", "Fem") or n not in ("Sing", "Plur"): return None
    return ("m" if g == "Masc" else "f") + ("s" if n == "Sing" else "p")

# ---------------------------------------------------------------- shared word list
LEX, LEXID = [], {}
OVR = {}
for line in open(os.path.join(HERE, "gloss_override.tsv"), encoding="utf-8"):
    if line.startswith("#") or not line.strip(): continue
    w, p, g = line.rstrip("\n").split("\t")
    OVR[(w, p)] = g
POS_EN = {"NOUN": "noun", "VERB": "verb", "AUX": "verb", "ADJ": "adjective", "ADV": "adverb", "ADP": "preposition",
          "CCONJ": "conjunction", "SCONJ": "conjunction", "PRON": "pronoun", "DET": "determiner",
          "INTJ": "interjection", "NUM": "number"}
GENDER_EN = {"m": "masculine", "f": "feminine", "mf": "masculine or feminine", "m-p": "masculine plural", "f-p": "feminine plural"}

def join_glosses(gl, limit=150):
    parts = []
    for g in gl:
        for p in g.split("; "):
            p = p.strip()
            if len(p) > 90: p = p[:90].rsplit(" ", 1)[0] + "…"
            if p and p.lower() not in (x.lower() for x in parts): parts.append(p)
    out = ""
    for p in parts:
        if len(out) + len(p) + 2 > limit and out: break
        out = (out + "; " + p) if out else p
    return out

def lex_id(lemma, pos, part=False):
    if pos == "AUX": pos = "VERB"
    key = (lemma, "PART" if part else pos)
    if key in LEXID: return LEXID[key]
    en = gloss(lemma, "VERB" if part else pos, n=4)
    ov = OVR.get((lemma, "verb" if part else POS_EN.get(pos, "")))
    if ov: en = [ov]
    if not en: return None
    if part: en = [g if not g.startswith("to ") else g for g in en]
    e = {"w": lemma, "p": "past participle (as adjective)" if part else POS_EN.get(pos, ""), "en": ov if ov else join_glosses(en)}
    if pos == "NOUN":
        for x in W.get(lemma, []):
            if x["pos"] == "n" and x.get("g") in GENDER_EN:
                e["g"] = GENDER_EN[x["g"]]; break
    LEXID[key] = len(LEX); LEX.append(e)
    return LEXID[key]

# ---------------------------------------------------------------- grammar rules
CLITICS = {"me", "te", "se", "nos", "os", "lo", "la", "los", "las", "le", "les"}
REFLEX = {"me", "te", "se", "nos", "os"}

PERIPH = [  # (verb, linking word or None, title, explanation)
    ("ir", "a", "ir a + infinitive (near future)", "\"Going to…\": plans or something about to happen. Voy a comer = I'm going to eat."),
    ("tener", "que", "tener que + infinitive", "\"Have to / must…\" (personal obligation)."),
    ("haber", "que", "hay que + infinitive", "\"One has to / it's necessary to…\" — impersonal obligation, no specific subject."),
    ("deber", None, "deber + infinitive", "\"Should / ought to…\"."),
    ("acabar", "de", "acabar de + infinitive", "\"To have just…\": acabo de llegar = I've just arrived."),
    ("volver", "a", "volver a + infinitive", "\"To do … again\": volver a empezar = to start again."),
    ("empezar", "a", "empezar a + infinitive", "\"To start / begin to…\"."),
    ("comenzar", "a", "comenzar a + infinitive", "\"To begin to…\"."),
    ("ponerse", "a", "ponerse a + infinitive", "\"To start (to get down to) …\"."),
    ("dejar", "de", "dejar de + infinitive", "\"To stop …-ing / to no longer…\"."),
    ("soler", None, "soler + infinitive", "\"To usually / tend to…\": suelo levantarme temprano = I usually get up early."),
    ("llegar", "a", "llegar a + infinitive", "\"To end up / get to the point of…\"."),
    ("tratar", "de", "tratar de + infinitive", "\"To try to…\"."),
    ("terminar", "de", "terminar de + infinitive", "\"To finish …-ing\"; no terminar de = not quite / not entirely."),
    ("estar", "a punto de", "estar a punto de + infinitive", "\"To be about to…\"."),
    ("poder", None, "poder + infinitive", "\"Can / be able to / may…\"."),
    ("querer", None, "querer + infinitive", "\"To want to…\"."),
    ("necesitar", None, "necesitar + infinitive", "\"To need to…\"."),
]
GER_AUX = {
    "estar": ("Progressive: estar + gerund", "An action in progress at a given moment: estoy hablando = I'm talking."),
    "seguir": ("seguir + gerund", "\"To keep / still be …-ing\"."),
    "continuar": ("continuar + gerund", "\"To continue …-ing\"."),
    "llevar": ("llevar + time + gerund", "\"To have been …-ing for (time)\": llevo dos años estudiando = I've been studying for two years."),
    "ir": ("ir + gerund", "\"To gradually / progressively …\"."),
    "andar": ("andar + gerund", "\"To go around …-ing\" (often with annoyance)."),
    "pasar": ("pasar(se) + time + gerund", "\"To spend (time) …-ing\"."),
}
PERFECT = {
    ("Ind", "Pres"): ("Present perfect (haber present + participle)", "Completed actions connected to now: today, this year, ever, so far. He comido = I have eaten."),
    ("Ind", "Imp"): ("Pluperfect (haber imperfect + participle)", "\"Had done\": completed before another past moment."),
    ("Ind", "Fut"): ("Future perfect (haber future + participle)", "\"Will have done\"; also a guess about the past (habrá salido = he's probably gone out)."),
    ("Ind", "Past"): ("Past anterior (hube + participle)", "Literary, rare."),
    ("Cnd", None): ("Conditional perfect (habría + participle)", "\"Would have done\" — contrary to what actually happened."),
    ("Sub", "Pres"): ("Present perfect subjunctive (haya + participle)", "A completed action inside a subjunctive clause: espero que hayas aprendido…"),
    ("Sub", "Imp"): ("Pluperfect subjunctive (hubiera + participle)", "Unreal past conditions: si hubiera sabido… = if I had known…"),
    (None, None): ("Perfect form (haber + participle)", "A completed action."),
}
GUSTAR = {"gustar", "encantar", "interesar", "importar", "molestar", "doler", "apetecer", "preocupar",
          "faltar", "quedar", "parecer", "fascinar", "aburrir", "costar", "sobrar", "agobiar", "flipar", "chiflar"}
SUBJ_TRIGGERS = [
    (r"\bpara que\b", "para que (purpose: so that…)"), (r"\bojal[aá]\b", "ojalá (wish: I hope…)"),
    (r"\bantes de que\b", "antes de que (before…)"), (r"\bsin que\b", "sin que (without…)"),
    (r"\bhasta que\b", "hasta que (until…, future reference)"), (r"\bcuando\b", "cuando (when…, referring to the future)"),
    (r"\baunque\b", "aunque (even if…)"), (r"\bcomo si\b", "como si (as if…)"),
    (r"\bsi\b", "si (unreal / hypothetical condition)"),
    (r"\bes (importante|necesario|mejor|posible|probable|normal|raro|increíble|una pena|bueno|malo) que\b", "es + evaluation + que (opinion, possibility)"),
    (r"\b(quiero|quieres|quiere|queremos|quería|querría|espero|esperamos|pido|pide|necesito|prefiero|prefiere|dudo|me gusta|me encanta|me molesta|odio) que\b", "verb of wishing / requesting / emotion / doubt + que"),
    (r"\bno (creo|pienso|digo|es que|me parece) que\b", "negated opinion verb + que (no creo que…)"),
    (r"\bel que\b|\blo que\b|\bla que\b|\bquien\b|\bdonde\b", "relative clause about something unknown or not specific"),
    (r"\bque\b", "que-clause (wish, emotion, doubt, command…)"),
]

STATS = collections.Counter()
ENG_STOP = set("the of and to a in is it you that this for on with as are be at by have from or an not but what all were we when your can said there use each which she do how their if will up other about out many then them these so some her would make like him into time has look two more write go see number no way could people my than first been call who its now find long down day did get come made may part episode podcast welcome hello".split())
ENG_ONLY = set("the to yes out is are of and you false beginner beginners listening".split())
def english_mask(toks, starts):
    """英文句子（节目开头的英文介绍等）不加西语注释"""
    mask = [False] * len(toks)
    bounds = starts + [len(toks)]
    for a, b in zip(bounds, bounds[1:]):
        words = [t[0].lower() for t in toks[a:b] if re.fullmatch(r"[A-Za-z']+", t[0])]
        if len(words) < 3: continue
        eng = sum(1 for w in words if w in ENG_STOP or (w not in FORMS and not w.istitle()))
        if eng / len(words) >= 0.6:
            for k in range(a, b): mask[k] = True
    return mask

class Notes:
    def __init__(self): self.items = []; self.index = {}
    def add(self, kind, title, desc, toks):
        key = (kind, title, tuple(toks))
        if key in self.index: return
        self.index[key] = len(self.items)
        self.items.append({"k": kind, "t": title, "d": desc, "x": list(toks)})

def subtree_text(toks, children, i, limit=50):
    idx, stack = [], [i]
    while stack:
        k = stack.pop(); idx.append(k); stack += children[k]
    idx = sorted(idx)
    s = "".join(toks[k][0] + toks[k][1] for k in range(idx[0], idx[-1] + 1)).strip()
    return s if len(s) <= limit else s[:limit] + "…"

def build_episode(paras):
    out_paras = []
    notes = Notes()
    history = []        # nouns seen so far (for guessing what lo/la refer to)
    for pi, toks in enumerate(paras):
        N = len(toks)
        M = [morph(t[4]) for t in toks]
        low = [t[0].lower() for t in toks]
        info = [dict() for _ in toks]
        sent_starts = [i for i, t in enumerate(toks) if t[7] or i == 0]
        english = english_mask(toks, sent_starts)
        # 引号里夹的英文（“false beginner”）和明显的英文虚词也不注释
        q0 = None
        for i, t in enumerate(toks):
            if t[0] in ("“", '"', "«") and q0 is None: q0 = i; continue
            if t[0] in ("”", '"', "»") and q0 is not None:
                inside = [low[k] for k in range(q0 + 1, i)]
                if any(w in ENG_STOP or w in ENG_ONLY for w in inside):
                    for k in range(q0 + 1, i): english[k] = True
                q0 = None
        for i in range(N):
            if low[i] in ENG_ONLY: english[i] = True
        L, P, PART, TAGS = [], [], [], [None] * N
        for i, t in enumerate(toks):
            if not re.search(r"\w", t[0]) or english[i]:
                L.append(t[0] if not english[i] else low[i]); P.append(t[3] if not english[i] else "X"); PART.append(False); continue
            lem, pos, part = resolve(t[0], t[2], t[3])
            if low[i] == "sí" and not (i > 0 and low[i - 1] in ("para", "en", "por", "de", "a", "con", "entre", "sobre", "ante", "contra", "hacia", "desde", "sin")):
                lem, pos, part = "sí", "ADV", False           # “sí” = yes（介词后面才是反身代词 sí）；Collins 标为副词
            if low[i] in ("exacto", "exactamente", "perfecto", "genial") and (i + 1 >= N or not re.search(r"\w", toks[i + 1][0])) and (i == 0 or not re.search(r"\w", toks[i - 1][0])):
                lem, pos, part = low[i] if low[i] != "exactamente" else "exactamente", ("INTJ" if low[i] == "exacto" else pos), False
            if low[i] == "vale" and (i + 1 >= N or not re.search(r"\w", toks[i + 1][0])) and (i == 0 or not re.search(r"\w", toks[i - 1][0]) or low[i - 1] in ("y", "pues", "bueno", "ah", "vale")):
                lem, pos, part = "vale", "INTJ", False        # “¡Vale!” = OK
            elif low[i] == "vale" and i + 1 < N and low[i + 1] == "," and i > 0 and not re.search(r"\w", toks[i - 1][0]):
                lem, pos, part = "vale", "INTJ", False
            if lem is None:
                lem = fix_lemma(t[0], t[2], t[3])
                if low[i] not in FORMS and lem not in W and t[3] not in ("PROPN", "NUM"):
                    L.append(low[i]); P.append("X"); PART.append(False); continue      # 外语词（英文等），不注释
            L.append(lem); P.append(pos); PART.append(part)
            if pos in ("VERB", "AUX") and not part:
                tags, status = correct_verb(t[0], lem, M[i] if t[3] in ("VERB", "AUX") else {})
                tg = tags[0]
                if tg and tg[0]:
                    m = dict(M[i]); STATS["verb_" + status] += 1
                    for k in ("Mood", "Tense", "Person", "Number", "VerbForm"): m.pop(k, None)
                    if len(tg) == 1: m["VerbForm"] = tg[0]
                    else:
                        m.update(VerbForm="Fin", Mood=tg[0])
                        if tg[1]: m["Tense"] = tg[1]
                        if tg[2]: m["Person"] = tg[2]
                        if tg[3]: m["Number"] = tg[3]
                    M[i] = m; TAGS[i] = tags
        children = collections.defaultdict(list)
        for i, t in enumerate(toks):
            if t[6] != i: children[t[6]].append(i)

        def note(kind, title, desc, idxs):
            notes.add(kind, title, desc, [f"{pi}:{i}" for i in sorted(set(idxs))])

        def sent_of(i):
            s = 0
            for st in sent_starts:
                if st <= i: s = st
            return s

        # ---- meaning, verb form, gender/number
        for i, t in enumerate(toks):
            text, pos = t[0], P[i]
            if not re.search(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü]", text) or english[i]: continue
            if pos not in ("PROPN", "PUNCT", "SYM", "X", "NUM", "SPACE"):
                lid = lex_id(L[i], pos, PART[i])
                if lid is not None: info[i]["l"] = lid
            if pos in ("VERB", "AUX") and not PART[i]:
                vd = verb_desc(M[i], TAGS[i])
                if vd: info[i]["v"] = vd
            elif PART[i]:
                info[i]["v"] = f"Past participle of {L[i]}, used as an adjective\nIt agrees in gender and number with the noun it describes."
            c = gn_class(t, L[i])
            if c: info[i]["c"] = c

        # ---- perfect tenses / progressive
        for i, t in enumerate(toks):
            if t[3] not in ("VERB", "AUX", "ADJ"): continue
            for a in children[i]:
                if toks[a][5] != "aux": continue
                if L[a] == "haber" and M[i].get("VerbForm") == "Part":
                    ma = M[a]
                    key = (ma.get("Mood"), ma.get("Tense")) if ma.get("Mood") != "Cnd" else ("Cnd", None)
                    if key == ("Sub", "Past"): key = ("Sub", "Imp")
                    title, desc = PERFECT.get(key) or PERFECT[(None, None)]
                    note("g", title, desc, [a, i])
                if L[a] in GER_AUX and M[i].get("VerbForm") == "Ger":
                    title, desc = GER_AUX[L[a]]
                    note("g", title, desc, [a, i])
        for i in range(N - 1):
            if L[i] in GER_AUX and L[i] != "estar" and toks[i][3] in ("VERB", "AUX"):
                for j in range(i + 1, min(N, i + 4)):
                    if M[j].get("VerbForm") == "Ger":
                        title, desc = GER_AUX[L[i]]; note("g", title, desc, [i, j]); break
                    if low[j] not in CLITICS and toks[j][3] not in ("NUM", "NOUN", "DET", "ADV"): break

        # ---- verb + infinitive constructions (surface order)
        for i in range(N):
            if toks[i][3] not in ("VERB", "AUX"): continue
            for verb, prep, title, desc in PERIPH:
                v0 = verb[:-2] if verb.endswith("se") else verb
                if L[i] != v0: continue
                if verb == "haber" and low[i] != "hay" and not low[i].startswith("hab"): continue
                if verb == "ir" and M[i].get("VerbForm") in ("Inf", "Ger", "Part"): continue
                j = i + 1; idx = [i]
                if prep:
                    words = prep.split()
                    if [low[k] for k in range(j, min(N, j + len(words)))] != words: continue
                    idx += list(range(j, j + len(words))); j += len(words)
                while j < N and low[j] in CLITICS: j += 1
                if j < N and M[j].get("VerbForm") == "Inf":
                    idx.append(j); note("g", title, desc, idx); break
        for i in range(N - 1):
            if low[i] == "para" and M[i + 1].get("VerbForm") == "Inf":
                note("g", "para + infinitive", "\"In order to…\": expresses purpose.", [i, i + 1])

        # ---- subjunctive, conditional, imperative
        for i, t in enumerate(toks):
            m = M[i]
            if t[3] not in ("VERB", "AUX") or m.get("VerbForm") != "Fin": continue
            if not re.search(r"[a-záéíóúñü]", low[i]): continue
            mood = m.get("Mood")
            if mood == "Sub":
                s0 = sent_of(i)
                left = " ".join(low[s0:i])
                trig = None
                for pat, label in SUBJ_TRIGGERS:
                    mm = list(re.finditer(pat, left))
                    if mm: trig = (mm[-1], label); break
                past = m.get("Tense") in ("Imp", "Past")
                title = "Past subjunctive" if past else "Present subjunctive"
                desc = TENSE_HINT[("Sub", "Imp" if past else "Pres")]
                idx = [i]
                if trig:
                    desc = "Triggered by: " + trig[1] + "\n" + desc
                    trig_words = trig[0].group(0).split()
                    for k in range(i - 1, s0 - 1, -1):
                        if low[k] == trig_words[-1]:
                            idx += list(range(max(s0, k - len(trig_words) + 1), k + 1)); break
                neg_cmd = m.get("Person") == "2" and ((i > 0 and low[i - 1] == "no") or (i > 1 and low[i - 2] == "no" and low[i - 1] in CLITICS))
                if neg_cmd:
                    note("g", "Negative command (no + subjunctive)", "Negative commands use the subjunctive: no lo hagas = don't do it.", idx)
                else:
                    note("g", title, desc, idx)
            elif mood == "Cnd":
                if not (L[i] == "haber" and M[toks[i][6]].get("VerbForm") == "Part"):
                    note("g", "Simple conditional", TENSE_HINT[("Cnd", None)], [i])
            elif mood == "Imp":
                note("g", "Imperative", TENSE_HINT[("Imp", None)], [i])
        for s0 in sent_starts:
            s1 = min([s for s in sent_starts if s > s0] + [N])
            si = [k for k in range(s0, s1) if low[k] == "si"]
            subj = [k for k in range(s0, s1) if M[k].get("Mood") == "Sub" and M[k].get("Tense") in ("Imp", "Past")]
            cnd = [k for k in range(s0, s1) if M[k].get("Mood") == "Cnd"]
            if si and subj and cnd:
                note("g", "Unreal condition", "si + past subjunctive, with the conditional in the main clause: si tuviera dinero, viajaría = if I had money, I would travel.", [si[0], subj[0], cnd[0]])

        # ---- gustar-type verbs
        for i, t in enumerate(toks):
            if L[i] in GUSTAR and t[3] in ("VERB", "AUX"):
                if any(toks[c][5] == "iobj" for c in children[i]) or (i > 0 and low[i - 1] in ("me", "te", "le", "nos", "os", "les")):
                    note("g", "gustar-type verb", "The thing liked is the subject (the verb agrees with it); the person is an indirect object pronoun (me, te, le…): me gustan los perros = I like dogs (lit. dogs please me).", [i])

        # ---- se, relative pronouns, lo + adjective, hay, hace + time, comparisons, superlatives, diminutives
        for i, t in enumerate(toks):
            d = t[5]
            if low[i] == "se":
                h = toks[i][6]
                if d == "expl:pv":
                    note("g", "Pronominal verb (verb + se)", f"This verb is used as {L[h]}se; se changes with the subject (me / te / se / nos / os).", [i, h])
                elif d == "expl:pass":
                    note("g", "Passive se", "se + 3rd-person verb = \"is/are …-ed\"; the verb agrees with the thing: se venden pisos = flats for sale.", [i, h])
                elif d == "expl:impers":
                    note("g", "Impersonal se", "se + 3rd-person singular = \"people / one / you (in general)\": se dice que… = they say that…", [i, h])
                elif d == "iobj" and i + 1 < N and low[i + 1] in ("lo", "la", "los", "las"):
                    note("g", "se = le / les", "le / les become se before lo / la / los / las: se lo di = I gave it to him/her.", [i, i + 1])
            if M[i].get("PronType") == "Rel" or (low[i] in ("que", "quien", "quienes", "donde", "cual", "cuales") and d in ("nsubj", "obj", "obl", "advmod") and toks[toks[i][6]][5] == "acl"):
                if i > 0 and low[i - 1] == "lo" and low[i] == "que":
                    note("g", "lo que", "Neuter relative: \"what / the thing that\": lo que dices = what you say.", [i - 1, i])
                elif low[i] in ("que", "quien", "quienes", "donde", "cual", "cuales", "cuyo", "cuya"):
                    h = toks[i][6]; target = toks[h][6] if toks[h][5] == "acl" else None
                    desc = "Relative pronoun introducing a relative clause"
                    if target is not None and target != h:
                        desc += f" that describes \"{toks[target][0]}\""
                    note("g", "Relative clause", desc + ".", [i] + ([target] if target is not None else []))
            if low[i] == "lo" and i + 1 < N and toks[i + 1][3] == "ADJ" and d == "det" and not (i > 0 and low[i - 1] == "por"):
                note("g", "lo + adjective", "Turns an adjective into an abstract noun: \"the … thing / part\": lo bueno = the good thing.", [i, i + 1])
            if low[i] == "hay" or (L[i] == "haber" and t[3] in ("VERB", "AUX") and d != "aux" and low[i] in ("había", "habrá", "hubo", "habría", "haya", "hubiera")):
                note("g", "hay (impersonal haber)", "\"There is / there are\": always singular, even with plural nouns: hay dos gatos.", [i])
            if low[i] == "hace" and i + 1 < N and (toks[i + 1][3] == "NUM" or low[i + 1] in ("mucho", "poco", "unos", "unas", "años", "meses", "días", "tiempo", "un", "una", "dos", "tres")):
                note("g", "hace + time", "\"… ago\"; hace + time + que + verb = \"it's been … since / for\": hace dos años = two years ago.", [i, i + 1])
            if low[i] in ("más", "menos") and t[3] == "ADV":
                s1 = min([s for s in sent_starts if s > i] + [N])
                for k in range(i + 1, min(s1, i + 7)):
                    if low[k] == "que":
                        note("g", "Comparative más / menos … que", "\"More / less … than\".", [i, k]); break
                    if low[k] == "de" and k + 1 < N and toks[k + 1][3] == "NUM":
                        note("g", "más / menos de + number", "With numbers use de, not que: más de cien = more than a hundred.", [i, k]); break
            if low[i] == "tan":
                for k in range(i + 1, min(N, i + 6)):
                    if low[k] == "como":
                        note("g", "Comparison of equality tan … como", "\"As … as\".", [i, k]); break
            if t[3] == "ADJ" and re.search(r"ísim[oa]s?$", low[i]):
                note("g", "Absolute superlative -ísimo", "\"Very / extremely …\": buenísimo = really good.", [i])
            if t[3] == "NOUN" and re.search(r"(it|cit)(o|a|os|as)$", low[i]) and len(low[i]) > 5 and L[i] not in W:
                note("g", "Diminutive -ito / -ita", "Means small, or adds an affectionate / cute tone: casita = little house.", [i])
            if low[i] == "a" and i + 2 < N and low[i + 1] in ("mí", "ti", "él", "ella", "nosotros", "vosotros", "ellos", "ellas", "usted", "ustedes") and low[i + 2] in ("me", "te", "le", "nos", "os", "les"):
                note("g", "a mí me… (emphasis)", "The pronoun already says who; a mí / a ti adds emphasis or contrast: a mí me gusta = I (for my part) like it.", [i, i + 1, i + 2])

        # ---- objects
        for i, t in enumerate(toks):
            d = t[5]
            if d not in ("obj", "iobj"): continue
            role = "od" if d == "obj" else "oi"
            h = toks[i][6]
            if L[h] in GUSTAR and low[i] in CLITICS: role = "oi"; d = "iobj"
            if t[3] != "PRON" or low[i] not in CLITICS:
                if any(toks[c][5] == "case" and low[c] not in ("a", "al") for c in children[i]): continue
            role_en = "Direct object" if role == "od" else "Indirect object"
            if t[3] == "PRON" and low[i] in CLITICS:
                ref = None
                for c in children[h]:           # doubled object: le dije a María
                    if c != i and toks[c][5] == d and toks[c][0].lower() not in CLITICS:
                        ref = "refers to " + subtree_text(toks, children, c); break
                if not ref:
                    if low[i] in ("me", "nos"): ref = "me" if low[i] == "me" else "us"
                    elif low[i] in ("te", "os"): ref = "you" if low[i] == "te" else "you (plural)"
                    elif low[i] == "se" and d == "iobj" and i + 1 < N and low[i + 1] in ("lo", "la", "los", "las"):
                        ref = "him / her / you (usted) / them — se replaces le / les"
                    elif low[i] in ("lo", "la", "los", "las"):
                        want = {"lo": "ms", "la": "fs", "los": "mp", "las": "fp"}[low[i]]
                        local = [toks[i2][0] for i2 in range(i - 1, -1, -1) if toks[i2][3] == "NOUN" and gn_class(toks[i2]) == want]
                        cand = [hh for hh in reversed(history[-40:]) if hh[3] == want]
                        if local: ref = f"probably refers to \"{local[0]}\""
                        elif cand: ref = f"probably refers to \"{cand[0][2]}\""
                        elif low[i] == "lo": ref = "probably refers to an idea / something just said (neuter lo)"
                    elif low[i] in ("le", "les"):
                        ref = "(to) him / her / you (usted)" if low[i] == "le" else "(to) them / you (ustedes)"
                desc = f"{role_en} pronoun"
                if low[i] == "se" and d == "iobj": desc = "Indirect object pronoun (se = le / les)"
                info[i]["o"] = role
                info[i]["r"] = desc + (": " + ref if ref else "")
            elif t[3] in ("NOUN", "PROPN", "PRON", "NUM"):
                span = subtree_text(toks, children, i)
                info[i]["o"] = role
                info[i]["r"] = f"{role_en}: \"{span}\"" + (f" (verb: {toks[h][0]})" if toks[h][3] in ("VERB", "AUX") else "")

        for i, t in enumerate(toks):
            c = gn_class(t)
            if t[3] == "NOUN" and c: history.append((pi, i, t[0], c))

        out_toks = []
        for i, t in enumerate(toks):
            row = [t[0], 1 if t[1] else 0]
            if info[i]: row.append(info[i])
            out_toks.append(row)
        out_paras.append({"s": sent_starts, "t": out_toks})
    return out_paras, notes

# ---------------------------------------------------------------- fixed expressions (Wiktionary multi-word entries)
STOP = set("""a al ante bajo con contra de del desde en entre hacia hasta para por según sin sobre tras
el la lo los las un una unos unas y o u e ni que se me te nos os le les mi tu su sus mis tus
es ser son era fue estar está hay haber ha he no sí si como más muy ya tan""".split())
SKIP_PHRASE_RE = re.compile(r"^(Used other than|contraction|abbreviation|alternative form|alternative spelling|plural of|feminine|masculine|form of|misspelling|synonym of|clipping of|ellipsis of|reflexive of|gender neutral)", re.I)
COMMON_V = {"ser", "estar", "haber", "tener", "hacer", "ir", "dar", "poner", "decir", "ver", "llevar", "quedar", "venir", "salir"}

def load_blacklist():
    p = os.path.join(HERE, "phrase_blacklist.txt")
    if not os.path.exists(p): return set()
    return {l.strip() for l in open(p, encoding="utf-8") if l.strip() and not l.startswith("#")}

BLACK = load_blacklist()

def phrase_gloss(entries):
    out = []
    for e in entries:
        qs = e.get("q") or [""] * len(e["glosses"])
        for g, q in zip(e["glosses"], qs):
            if SKIP_PHRASE_RE.match(g): continue
            if BAD_Q.search(q or "") or BAD_G.search(g): continue
            g = re.sub(r"\[[^\]]*\]", "", g)
            g = re.sub(r"\s+", " ", g).strip(" ;,")
            if g and g not in out: out.append(g)
    return out

def load_phrases():
    by_first = collections.defaultdict(list)
    for head, entries in W.items():
        if head in BLACK: continue
        words = head.lower().split()
        if len(words) < 2 or len(words) > 6: continue
        if not re.fullmatch(r"[a-záéíóúñü ]+", head.lower()): continue
        poss = [e for e in entries if e["pos"] not in ("prop", "proverb", "name")]
        if not poss: continue
        gl = phrase_gloss(poss)
        if not gl: continue
        if not [w for w in words if w not in STOP]: continue
        if len(words) == 2 and words[0] in COMMON_V and words[1] in STOP: continue
        pattern = []
        for k, w in enumerate(words):
            refl = False
            if k == 0 and w.endswith("se") and len(w) > 4 and w[:-2].endswith(("ar", "er", "ir", "ír")):
                w = w[:-2]; refl = True
            pattern.append((w, refl))
        by_first[pattern[0][0]].append({"p": pattern, "h": head, "g": join_glosses(gl[:3], 160)})
    return by_first

PHRASES = load_phrases()

def match_phrases(paras, notes):
    for pi, toks in enumerate(paras):
        N = len(toks)
        low = [t[0].lower() for t in toks]
        L = [fix_lemma(t[0], t[2], t[3]) if re.search(r"\w", t[0]) else t[0] for t in toks]
        for i in range(N):
            for key in {low[i], L[i]}:
                for ph in PHRASES.get(key, []):
                    j = i; idx = []; ok = True
                    for k, (w, refl) in enumerate(ph["p"]):
                        if k > 0:
                            while j < N and low[j] in CLITICS and w not in CLITICS: j += 1
                        if j >= N: ok = False; break
                        if not (low[j] == w or (L[j] == w and toks[j][3] in ("VERB", "AUX", "NOUN", "ADJ"))):
                            ok = False; break
                        if refl:
                            has = (j > 0 and low[j - 1] in REFLEX) or (j > 1 and low[j - 2] in REFLEX and low[j - 1] in CLITICS) \
                                or (re.search(r"(me|te|se|nos|os)(lo|la|los|las|le|les)?$", low[j]) and low[j] != L[j])
                            if not has: ok = False; break
                        idx.append(j); j += 1
                    if ok:
                        notes.add("c", ph["h"], ph["g"], [f"{pi}:{x}" for x in idx])

# ---------------------------------------------------------------- main
def main():
    eps = json.load(open(os.path.join(WEB, "..", "web_shared", "transcripts.json"), encoding="utf-8"))["episodes"]
    os.makedirs(os.path.join(WEB, "ann"), exist_ok=True)
    stats = collections.Counter()
    for e in eps:
        paras = json.load(open(os.path.join(NLP, f"{e['n']}.json"), encoding="utf-8"))
        out, notes = build_episode(paras)
        match_phrases(paras, notes)
        for ni, nt in enumerate(notes.items):
            for ref in nt["x"]:
                p, t = map(int, ref.split(":"))
                row = out[p]["t"][t]
                if len(row) == 2: row.append({})
                row[2].setdefault("g", []).append(ni)
            stats[nt["k"]] += 1
        notes_out = [{"k": n["k"], "t": n["t"], "d": n["d"]} for n in notes.items]
        json.dump({"n": e["n"], "paras": out, "notes": notes_out},
                  open(os.path.join(WEB, "ann", f"{e['n']}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
    json.dump(LEX, open(os.path.join(WEB, "lex.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("notes:", dict(stats), "lex:", len(LEX), dict(STATS))

if __name__ == "__main__":
    main()
