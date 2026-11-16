"""对 transcripts.json 每段西语跑 spaCy，结果存 nlp/<n>.json"""
import json, sys, os, spacy
model = sys.argv[1] if len(sys.argv) > 1 else "es_core_news_md"
out = sys.argv[2] if len(sys.argv) > 2 else "/home/claude/ann/nlp"
os.makedirs(out, exist_ok=True)
nlp = spacy.load(model)
eps = json.load(open("/home/claude/esp_listen/web/transcripts.json", encoding="utf-8"))["episodes"]
for e in eps:
    f = f"{out}/{e['n']}.json"
    if os.path.exists(f): continue
    paras = []
    for doc in nlp.pipe([p["es"] for p in e["paras"]], batch_size=32):
        toks = [[t.text, t.whitespace_, t.lemma_, t.pos_, str(t.morph), t.dep_, t.head.i, int(t.is_sent_start or t.i == 0)] for t in doc]
        paras.append(toks)
    json.dump(paras, open(f, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(e["n"], len(paras), flush=True)
