"""用变位表核对 / 纠正 spaCy 给出的动词形式（语气 · 时态 · 人称）。
标签 tag = (Mood, Tense, Person, Number)，非限定形式为 ('Inf',) ('Ger',) ('Part',)"""
import functools, unicodedata, re, logging, sys, os
logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_conj as bc
from verbecc import CompleteConjugator
_cg = None
P6 = [('1', 'Sing'), ('2', 'Sing'), ('3', 'Sing'), ('1', 'Plur'), ('2', 'Plur'), ('3', 'Plur')]
KEY = {'ip': ('Ind', 'Pres'), 'is': ('Ind', 'Past'), 'ii': ('Ind', 'Imp'), 'if': ('Ind', 'Fut'), 'cp': ('Cnd', None),
       'sp': ('Sub', 'Pres'), 'si': ('Sub', 'Imp'), 'si2': ('Sub', 'Imp')}

@functools.lru_cache(None)
def table(lemma):
    global _cg
    if _cg is None: _cg = CompleteConjugator(lang='es')
    try: base, c = bc.conj_one(_cg, lemma)
    except Exception: return None
    if not c: return None
    t = {}
    add = lambda f, tg: [t.setdefault(x.strip(), set()).add(tg) for x in f.split('/') if x.strip()]
    for k, forms in c['f'].items():
        if k in KEY:
            for (p, n), f in zip(P6, forms): add(f, KEY[k] + (p, n))
        elif k == 'ia':
            for (p, n), f in zip([('2', 'Sing'), ('3', 'Sing'), ('1', 'Plur'), ('2', 'Plur'), ('3', 'Plur')], forms): add(f, ('Imp', None, p, n))
    if base == 'haber': add('hay', ('Ind', 'Pres', '3', 'Sing'))
    if c.get('g'): add(c['g'], ('Ger',))
    if c.get('pp'):
        pp = c['pp']; add(pp, ('Part',))
        if pp.endswith('o'):
            for suf in ('a', 'os', 'as'): add(pp[:-1] + suf, ('Part',))
    add(base, ('Inf',))
    return t

def strip_acc(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').replace('ñ', 'ñ')

CL = r'(me|te|se|nos|os|lo|la|los|las|le|les)'
def candidates(form):
    out = [form]; f = form
    for _ in range(2):
        m = re.match(r'^(.+?)' + CL + '$', f)
        if not m or len(m.group(1)) < 2: break
        f = m.group(1)
        out += [f, strip_acc(f)]
        if f.endswith('mo'): out.append(f + 's')         # vámonos → vamos
        if f.endswith(('a', 'e', 'i')) and m.group(2) == 'os': out.append(f + 'd')   # sentaos → sentad
    return out

def tag_of(m):
    vf = m.get('VerbForm')
    if vf in ('Inf', 'Ger', 'Part'): return (vf,)
    mood, tense = m.get('Mood'), m.get('Tense')
    if mood == 'Sub' and tense == 'Past': tense = 'Imp'
    if mood in ('Cnd', 'Imp'): tense = None
    return (mood, tense, m.get('Person'), m.get('Number'))

def lookup(form, lemma):
    tb = table(lemma)
    if not tb: return None
    for k, f in enumerate(candidates(form.lower())):
        if f in tb:
            if k == 0: return tb[f]
            # 带了后置代词（dale, cuéntame, valóralo）：只能是命令式 / 不定式 / 副动词
            h = {t for t in tb[f] if t[0] in ("Imp", "Inf", "Ger")}
            return h or tb[f]
    return None

def correct(form, lemma, m):
    """返回 (tags, status)：tags 是这个词形可能的分析（第一项是选定的），status ∈ ok / fixed / unknown"""
    hits = lookup(form, lemma)
    tg = tag_of(m)
    if not hits: return [tg], 'unknown'
    if tg in hits:
        return [tg] + sorted(hits - {tg}, key=str), 'ok'
    hs = sorted(hits, key=str)
    # 尽量贴近 spaCy 的判断：先保语气，再保时态
    for keep in (lambda h: h[:2] == tg[:2], lambda h: h[:1] == tg[:1], lambda h: True):
        sel = [h for h in hs if keep(h)]
        if sel: break
    # 同一词形的句中优先级：陈述式 > 虚拟式 > 命令式（spaCy 已经判错时用最常见的读法）
    order = {'Ind': 0, 'Cnd': 1, 'Sub': 2, 'Imp': 3, 'Inf': 0, 'Ger': 0, 'Part': 0}
    sel.sort(key=lambda h: (order.get(h[0], 9), str(h)))
    best = sel[0]
    return [best] + [h for h in hs if h != best], 'fixed'
