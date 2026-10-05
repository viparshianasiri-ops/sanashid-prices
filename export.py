# -*- coding: utf-8 -*-
"""خروجی پلتفرم ساناشید: از radar.db دو فایل prices.json و leads.json می‌سازد.
اجرا:  python platform_export.py <پوشهٔ رادار> <پوشهٔ خروجی>
پوشهٔ رادار باید radar.py ، radar.db (و در صورت وجود radar.db-wal / radar.db-shm) و sources.json داشته باشد.
به فایل‌های اصلی دست نمی‌زند؛ روی یک کپی موقت کار می‌کند."""
import json, os, shutil, sys, tempfile

src = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
out = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else src)
work = tempfile.mkdtemp(prefix="sana_export_")
for f in ("radar.py", "radar.db", "radar.db-wal", "radar.db-shm", "sources.json"):
    p = os.path.join(src, f)
    if os.path.exists(p):
        shutil.copy(p, os.path.join(work, f))
        os.chmod(os.path.join(work, f), 0o644)
sys.path.insert(0, work)
import radar  # noqa: E402

c = radar.db()
radar.load_last_usd()
snap = c.execute("SELECT MAX(ts) FROM status").fetchone()[0] or 0

# قیمت عمدهٔ جهانی: آخرین ردیف‌های ثبت‌شده در تاریخچهٔ شاخص
last = c.execute("SELECT MAX(ts) FROM index_history WHERE grp LIKE 'S|%'").fetchone()[0]
if last:
    rows = c.execute("SELECT grp, median FROM index_history WHERE grp LIKE 'S|%' AND ts=? ORDER BY rowid", (last,)).fetchall()
    radar.STATE["spot"] = {"items": [{"name": r["grp"][2:], "usd": r["median"], "high": r["median"], "low": r["median"]}
                                     for r in rows], "source": "InfoLink", "ts": last}

d = radar.build_payload()
d["snapshot"] = d["now"] = d["last_run"] = snap
d["running"], d["next_run"] = False, None
for s in d["sources"]:
    s.pop("ms", None)
hist = {}
for r in c.execute("SELECT item_id, ts, price FROM history WHERE item_id IN "
                   "(SELECT item_id FROM history GROUP BY item_id HAVING COUNT(*)>1) ORDER BY item_id, ts"):
    hist.setdefault(str(r["item_id"]), []).append([r["ts"], r["price"]])
glob = {str(i["id"]) for i in d["items"] if i["m"] == "g"}
active = {str(i["id"]) for i in d["items"]}
d["hist"] = {k: ([[t, p / 100.0] for t, p in v] if k in glob else v) for k, v in hist.items() if k in active}

leads = [{"p": r["phone"], "n": r["name"] or "", "a": r["address"] or "", "r": r["region"] or "", "s": r["source"] or ""}
         for r in c.execute("SELECT * FROM leads ORDER BY (address=''), (phone LIKE '09%'), substr(phone,-3), phone")]
label = (radar.load_config().get("leads") or {}).get("label", "داروخانه")

os.makedirs(out, exist_ok=True)
with open(os.path.join(out, "prices.json"), "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
with open(os.path.join(out, "leads.json"), "w", encoding="utf-8") as f:
    json.dump({"ts": snap, "label": label, "items": leads}, f, ensure_ascii=False, separators=(",", ":"))
print(json.dumps({"snapshot": snap, "items": len(d["items"]), "leads": len(leads), "hist": len(d["hist"]),
                  "sources_ok": sum(1 for s in d["sources"] if s["ok"]), "sources": len(d["sources"])}))
