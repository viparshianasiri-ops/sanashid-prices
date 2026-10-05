#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
رادار قیمت خورشیدی ساناشید
--------------------------
قیمت پنل، اینورتر، باتری، استراکچر و سایر تجهیزات خورشیدی را از چند سایت
جمع می‌کند، هر کالا را با کالاهای هم‌رده مقایسه می‌کند و در یک صفحهٔ زنده نشان می‌دهد.

فقط به پایتون ۳.۸ یا بالاتر نیاز دارد (هیچ بستهٔ اضافه‌ای لازم نیست).
اجرا:  python radar.py
"""
import gzip
import html as htmlmod
import json
import logging
import os
import re
import sqlite3
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zlib
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "sources.json")
DB_PATH = os.path.join(HERE, "radar.db")
LOG_PATH = os.path.join(HERE, "radar.log")
DASHBOARD_PATH = os.path.join(HERE, "dashboard.html")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
HOST_DELAY = 1.2          # فاصلهٔ بین دو درخواست به یک سایت (ثانیه)
HOST_DELAYS = {"api.torob.com": 3.0, "torob.com": 3.0, "www.made-in-china.com": 2.5}   # ترب درخواست‌های پشت‌سرهم را مسدود می‌کند (خطای 490)
MIN_GROUP = 5
MIN_GROUP_GLOBAL = 3      # حداقل کالا برای قیمت جهانیِ هر گروه             # حداقل تعداد کالای هم‌رده برای امتیازدهی
OPPORTUNITY = 0.15        # حداقل ۱۵٪ زیر میانهٔ بازار = فرصت
SUSPICIOUS = 0.40         # ۴۰٪ یا بیشتر زیر میانه = قیمت مشکوک

log = logging.getLogger("radar")

# --------------------------------------------------------------------------
# تنظیمات
# --------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "interval_minutes": 30,
    "host": "127.0.0.1",
    "port": 8765,
    "version": 5,
    "queries": ["پنل خورشیدی", "اینورتر خورشیدی", "سانورتر", "باتری خورشیدی",
                "باتری لیتیومی خورشیدی", "استراکچر پنل خورشیدی", "شارژ کنترلر خورشیدی",
                "سازه پنل خورشیدی", "استراکچر خورشیدی", "پایه پنل خورشیدی", "کلمپ پنل خورشیدی",
                "ریل پنل خورشیدی"],
    "torob": {"enabled": True, "pages_per_query": 4, "sellers": True, "seller_products_per_run": 60},
    "emalls": {"enabled": True, "pages": [
        "https://emalls.ir/لیست-قیمت_پنل-خورشیدی-و-کنترلر~Category~51720"]},
    "divar": {"enabled": True, "city_ids": ["1"]},
    "digikala": {"enabled": True, "pages_per_query": 2},
    "sheypoor": {"enabled": True},
    "shops": [
        {"name": "سولارنیرو", "url": "https://www.solarniroo.com", "pages": ["https://www.solarniroo.com/list/"]},
        {"name": "هورایش", "url": "https://hoorayesh.com", "pages": [
            "https://hoorayesh.com/solar-products-prise/", "https://hoorayesh.com/product-category/سازه-خورشیدی/",
            "https://hoorayesh.com/shop/", "https://hoorayesh.com/product-category/solar-panel/",
            "https://hoorayesh.com/product-category/solar-battery/", "https://hoorayesh.com/product-category/solar-inverter/",
            "https://hoorayesh.com/product-category/solar-controller/"]},
        {"name": "تک اینورتر", "url": "https://takinverter.com"},
        {"name": "ایمن سولار", "url": "https://imensolar.ir"},
        {"name": "نوین سولار", "url": "https://novinsolar.com"},
        {"name": "آریا نوین پارس", "url": "https://arianovinparse.ir"},
        {"name": "ساناشید خاورمیانه", "url": "https://sanashid.com"},
        {"name": "سولار گستران", "url": "https://solargostaran.com"},
        {"name": "سولار آریو", "url": "https://novinario.com"},
        {"name": "ماناسازان", "url": "https://manasazan.ir"},
        {"name": "خورشید لاله‌زار", "url": "https://www.khorshidlalezar.ir"},
        # --- استراکچر و سازه ---
        {"name": "اورهان (سازه)", "url": "https://www.orhanco.com", "pages": ["https://www.orhanco.com/solar-panel-structure/"]},
        {"name": "آراپل مارکت (سازه)", "url": "https://arapelmarket.com", "pages": ["https://arapelmarket.com/product-category/power-solar/structure/"]},
        {"name": "تکسا رسام کاسپین (سازه)", "url": "https://texa-co.ir", "pages": ["https://texa-co.ir/category/solar-structure/"]},
        {"name": "پروسازه (سازه)", "url": "https://prosazeh.com", "pages": ["https://prosazeh.com/product-category/استراکچر-و-پایه-پنل-خورشیدی/"]},
        {"name": "آهن وان (سازه)", "url": "https://ahan1.com", "mode": "html", "pages": ["https://ahan1.com/Category/metal-structure/solar-panel-structure/"]},
        {"name": "سولار سازه", "url": "https://www.solarsaze.com"},
        {"name": "شاهین فلز سپاهان (کلمپ)", "url": "https://shahinfelezsepahan.com", "pages": ["https://shahinfelezsepahan.com/steel/solar-panel-clamps/"]},
        {"name": "درفک سازه رایان", "url": "https://dorfaksazehrayan.com"},
        {"name": "آموت (پایه پنل)", "url": "https://amootsec.com", "mode": "html", "pages": ["https://amootsec.com/pr/576/پایه-پنل-خورشیدی-یا-استراکچر-خورشیدی"]},
        # --- فروشگاه‌های عمومی خورشیدی ---
        {"name": "سولار پرتو سبز", "url": "https://www.solarparto.com"},
        {"name": "شاهدژ سولار", "url": "https://shahdejsolar.ir"},
        {"name": "زیپا", "url": "https://zipa.shop"},
        {"name": "مستر انرژی پلاس", "url": "https://mrenergyplus.com"},
        {"name": "همیار سولار", "url": "https://hamyarsolar.com"},
        {"name": "تکسان صنعت", "url": "https://techsunsanat.ir", "pages": ["https://techsunsanat.ir/shop/"]},
        {"name": "دکتر باتری", "url": "https://doctor-battery.com"},
        {"name": "تابش الکتریک", "url": "https://tabesh-electric.com"},
        {"name": "ایرمان مارکت", "url": "https://irman-market.ir"},
        {"name": "فروشگاه سانورتر", "url": "https://ssunverter.ir"},
        {"name": "سول ایران", "url": "https://sol-iran.com"},
        {"name": "الک ۷۲۴", "url": "https://elec724.com"},
        {"name": "سوراسل", "url": "https://sunbattery.ir"},
        {"name": "پنل خورشیدی ۲", "url": "https://panelkhorshidi2.ir"},
        {"name": "لیمو سولار", "url": "https://limoo.solar"},
        {"name": "ایران صنعت", "url": "https://www.iransanatgroup.com"},
        {"name": "پندار الکترونیک", "url": "https://pendarelectronic.com"},
        {"name": "پنل خورشیدی دات کام", "url": "https://panelkhorshidi.com"},
        {"name": "افق زرفام", "url": "https://ofoghzarfam.com"},
        {"name": "برق‌رسان", "url": "https://barghresun.com"},
        {"name": "سونر شاپ", "url": "https://sonershop.ir"},
        {"name": "نورسان", "url": "https://noursun.com"},
    ],
    "removed": [],
    "usd": {"manual_toman": 0},
    # قیمت دلاریِ واقعی: فروشگاهِ رسمیِ خودِ سازنده‌ها (قیمت به دلار روی سایتشان) + قیمت عمدهٔ جهانی پنل
    "global": {"enabled": True, "spot": True, "stores": [
        {"name": "PowMr (سازنده)", "url": "https://powmr.com"},
        {"name": "Easun Power (سازنده)", "url": "https://www.easunpower.com"},
        {"name": "SunGoldPower (سازنده)", "url": "https://sungoldpower.com"},
        {"name": "Renogy (سازنده)", "url": "https://www.renogy.com"},
        {"name": "Rich Solar (سازنده)", "url": "https://richsolar.com"},
        {"name": "ECO-WORTHY (سازنده)", "url": "https://www.eco-worthy.com"},
        {"name": "BougeRV (سازنده)", "url": "https://www.bougerv.com"},
        {"name": "LiTime (سازندهٔ باتری)", "url": "https://www.litime.com"},
        {"name": "Vatrer (سازندهٔ باتری)", "url": "https://www.vatrerpower.com"},
    ]},
    # قیمت دلاریِ مدل‌های برند (فروشنده‌های چینی در Made-in-China، قیمت FOB). هر مدل را می‌توانید اضافه یا حذف کنید.
    #   panel: وات پنل   |   inverter: توان به کیلووات   |   must: کلمه‌هایی که باید در عنوان آگهی باشد
    # فهرست تماس روزانه: هر روز چند داروخانهٔ تهران (غیرتکراری) از فهرست‌های عمومی
    "leads": {"enabled": True, "per_day": 10, "label": "داروخانه", "keyword": "داروخانه", "pages": [
        "https://balad.ir/blog/tehran-pharmacy-list/",
        "https://www.drsaina.com/pharmacy/tehran-list",
        "https://www.bank-mobile.ir/pharmacy-tehran",
        "https://adorateb.com/pharmacy-cat/استان-تهران/",
        "https://tehranmoble.ir/blog/tehran-boarding-pharmacies/",
        "https://digidaroo.org/لیست-داروخانه-های-دولتی-تهران/",
        "https://mag.sabads.com/blog/the-best-pharmacy-in-tehran/",
    ]},
    "fob": {"enabled": True, "models": [
        {"label": "Jinko 625W", "q": "Jinko 625W Solar Panel", "cat": "panel", "brand": "Jinko", "watts": 625},
        {"label": "Jinko 585W", "q": "Jinko 585W Solar Panel", "cat": "panel", "brand": "Jinko", "watts": 585},
        {"label": "Jinko 715W", "q": "Jinko 715W Solar Panel", "cat": "panel", "brand": "Jinko", "watts": 715},
        {"label": "Longi 550W", "q": "Longi 550W Solar Panel", "cat": "panel", "brand": "Longi", "watts": 550},
        {"label": "Longi 585W", "q": "Longi 585W Solar Panel", "cat": "panel", "brand": "Longi", "watts": 585},
        {"label": "Longi 630W", "q": "Longi 630W Solar Panel", "cat": "panel", "brand": "Longi", "watts": 630},
        {"label": "JA Solar 550W", "q": "JA Solar 550W Solar Panel", "cat": "panel", "brand": "JA Solar", "watts": 550},
        {"label": "JA Solar 590W", "q": "JA Solar 590W Solar Panel", "cat": "panel", "brand": "JA Solar", "watts": 590},
        {"label": "JA Solar 625W", "q": "JA Solar 625W Solar Panel", "cat": "panel", "brand": "JA Solar", "watts": 625},
        {"label": "Trina 580W", "q": "Trina 580W Solar Panel", "cat": "panel", "brand": "Trina", "watts": 580},
        {"label": "Trina 620W", "q": "Trina 620W Solar Panel", "cat": "panel", "brand": "Trina", "watts": 620},
        {"label": "Trina 700W", "q": "Trina 700W Solar Panel", "cat": "panel", "brand": "Trina", "watts": 700},
        {"label": "Canadian Solar 600W", "q": "Canadian Solar 600W Solar Panel", "cat": "panel", "brand": "Canadian", "watts": 600},
        {"label": "Risen 700W", "q": "Risen 700W Solar Panel", "cat": "panel", "brand": "Risen", "watts": 700},
        {"label": "Growatt SPF 6000 ES Plus", "q": "Growatt SPF 6000 ES Plus", "cat": "inverter", "brand": "Growatt", "kw": 6, "must": ["growatt", "6000"]},
        {"label": "Growatt SPE 12000 ES", "q": "Growatt SPE 12000 ES", "cat": "inverter", "brand": "Growatt", "kw": 12, "must": ["growatt", "12000"]},
        {"label": "Growatt MOD 10KTL3-X", "q": "Growatt MOD 10KTL3-X", "cat": "inverter", "brand": "Growatt", "kw": 10, "must": ["growatt", "mod", "10k"]},
        {"label": "Growatt MID 25KTL3-X", "q": "Growatt MID 25KTL3-X", "cat": "inverter", "brand": "Growatt", "kw": 25, "must": ["growatt", "25k"]},
        {"label": "Deye 8kW Hybrid", "q": "Deye SUN-8K-SG01LP1 hybrid inverter", "cat": "inverter", "brand": "Deye", "kw": 8, "must": ["deye", "8k"]},
        {"label": "Deye 12kW Hybrid", "q": "Deye SUN-12K-SG04LP3 hybrid inverter", "cat": "inverter", "brand": "Deye", "kw": 12, "must": ["deye", "12k"]},
        {"label": "MUST PV18 5.2kW", "q": "MUST PV18-5248 PRO inverter", "cat": "inverter", "brand": "Must", "kw": 5.2, "must": ["must", "pv18"]},
    ]},      # اگر عددی بگذارید (مثلاً 105000) همان به‌جای نرخ خودکار استفاده می‌شود
}

DEAD_SHOPS = {"shop:wiksolar.com", "shop:solarsepehr.ir", "shop:systemartan.com"}
_cfg_lock = threading.RLock()


def load_config():
    with _cfg_lock:
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, encoding="utf-8-sig") as f:
                    user = json.load(f)
                for k, v in user.items():
                    if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                        cfg[k].update(v)
                    else:
                        cfg[k] = v
            except Exception as e:  # فایل خراب: با پیش‌فرض ادامه بده
                log.error("sources.json could not be read: %s", e)
            # سایت‌های پیش‌فرضِ جدید را به فهرست قبلی کاربر اضافه کن (مگر خودش حذفشان کرده باشد)
            have = {shop_id(s) for s in cfg["shops"]} | set(cfg.get("removed") or [])
            new = [s for s in DEFAULT_CONFIG["shops"] if shop_id(s) not in have]
            old_version = int(cfg.get("version") or 1) if "version" in user else 1
            if old_version < DEFAULT_CONFIG["version"]:      # یک‌بار: عبارت‌ها و صفحه‌های جدید را اضافه کن
                cfg["shops"] = [sh for sh in cfg["shops"] if shop_id(sh) not in DEAD_SHOPS]   # دامنه‌هایی که وجود ندارند
                if cfg["torob"].get("seller_products_per_run", 0) > 60:
                    cfg["torob"]["seller_products_per_run"] = 60
                cfg["queries"] = cfg["queries"] + [q for q in DEFAULT_CONFIG["queries"] if q not in cfg["queries"]]
                defaults = {shop_id(d): d for d in DEFAULT_CONFIG["shops"]}
                for sh in cfg["shops"]:
                    for pg in defaults.get(shop_id(sh), {}).get("pages", []):
                        if pg not in sh.setdefault("pages", []):
                            sh["pages"].append(pg)
                cfg["version"] = DEFAULT_CONFIG["version"]
            if new or old_version < DEFAULT_CONFIG["version"]:
                cfg["shops"] = cfg["shops"] + json.loads(json.dumps(new))
                save_config(cfg)
        else:
            save_config(cfg)
        return cfg


def save_config(cfg):
    with _cfg_lock:
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)


# --------------------------------------------------------------------------
# ابزار متن و عدد
# --------------------------------------------------------------------------
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_CHARS = str.maketrans({"ي": "ی", "ك": "ک", "ـ": "", "\u200c": " ", "\u200f": "", "\u200e": "",
                        "\xa0": " ", "٬": ",", "،": ","})


def norm(s):
    """متن را برای جستجو یکدست می‌کند (ارقام لاتین، حروف فارسی استاندارد، حروف کوچک)."""
    if not s:
        return ""
    s = str(s).translate(_DIGITS).translate(_CHARS).lower()
    return re.sub(r"\s+", " ", s).strip()


def clean_title(s):
    s = htmlmod.unescape(str(s or "")).replace("\u200c", " ").replace("\xa0", " ")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()[:220]


_PRICE_RE = re.compile(r"(\d{1,3}(?:[,.]\d{3})+|\d{4,})\s*(تومان|تومن|ریال|toman|rial|irt|irr)")


def parse_prices(text):
    """همهٔ قیمت‌های داخل متن را به تومان برمی‌گرداند."""
    out = []
    for num, unit in _PRICE_RE.findall(norm(text)):
        try:
            v = int(re.sub(r"[,.]", "", num))
        except ValueError:
            continue
        if unit in ("ریال", "rial", "irr"):
            v //= 10
        if 1000 <= v <= 50_000_000_000:
            out.append(v)
    return out


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# دسته‌بندی و استخراج مشخصات از عنوان کالا
# --------------------------------------------------------------------------
CATEGORIES = {
    "panel": "پنل خورشیدی",
    "inverter": "اینورتر / سانورتر",
    "battery": "باتری",
    "structure": "استراکچر و سازه",
    "controller": "شارژ کنترلر",
    "cable": "کابل و اتصالات",
    "package": "پکیج کامل",
    "other": "سایر",
}

_CAT_WORDS = [
    ("package", ["پکیج", "نیروگاه", "سیستم کامل", "برق اضطراری", "package", " kit", "bundle", "power station",
                 "solar system", "generator"]),
    ("other", ["چراغ", "پروژکتور", "پمپ", "آبگرمکن", "پاوربانک", "پاور بانک", "دوربین", "لامپ",
               "فن ", "شارژر", "ریسه", "یخچال", "کولر"]),
    ("structure", ["استراکچر", "سازه", "پایه پنل", "پایه نصب", "ریل", "کلمپ", "structure", "mounting", "mount", "bracket",
                   "racking"]),
    ("cable", ["کابل", "کانکتور", "mc4", "فیوز", "تابلو", "کلید", "سیم ", "ارستر", "دیود", "cable",
               "جعبه", "باکس"]),
    ("inverter", ["اینورتر", "سانورتر", "سانوتر", "اینورتور", "inverter", "مبدل"]),
    ("controller", ["شارژ کنترل", "کنترل شارژ", "شارژکنترل", "کنترلر", "controller", "mppt", "pwm"]),
    ("battery", ["باتری", "باطری", "battery", "lifepo4", "لیتیوم"]),
    ("panel", ["پنل", "پانل", "ماژول", "panel", "module", "سلول خورشیدی"]),
]

BRANDS = {
    "Longi": ["longi", "لانجی", "لونجی"], "Jinko": ["jinko", "جینکو"], "JA Solar": ["ja solar", "jasolar", "جی ای سولار"],
    "Trina": ["trina", "ترینا"], "Canadian": ["canadian", "کانادین"], "Risen": ["risen", "رایسن"],
    "Yingli": ["yingli", "یینگلی", "ینگلی"], "Tongwei": ["tongwei", "tw solar", "تانگ وی"],
    "Astronergy": ["astronergy", "آسترونرژی"], "DMEGC": ["dmegc"], "Restar": ["restar", "ری استار", "ریستار"],
    "Suntech": ["suntech", "سانتک"], "Shinsung": ["shinsung", "شینسونگ"], "Tabaan": ["tabaan", "تابان"],
    "Growatt": ["growatt", "گرووات", "گرووت"], "Deye": ["deye", "دی یی"], "Sofar": ["sofar", "سوفار"],
    "GoodWe": ["goodwe", "گودوی"], "Huawei": ["huawei", "هواوی"], "Sungrow": ["sungrow", "سانگرو"],
    "Voltronic": ["voltronic", "ولترونیک", "axpert"], "Must": ["must "], "Sako": ["sako", "ساکو"],
    "SRNE": ["srne"], "Solis": ["solis", "سولیس"], "Kstar": ["kstar", "کی استار"], "Carspa": ["carspa", "کارسپا"],
    "Epever": ["epever", "epsolar", "ای پی اور"], "Victron": ["victron", "ویکترون"],
    "Pylontech": ["pylontech", "پایلون"], "Dyness": ["dyness", "داینس"], "BYD": ["byd"],
    "Saba": ["صبا باتری", "صباباتری", "saba"], "Faran": ["فاران", "faran"], "Narada": ["narada", "نارادا"],
    "Hi-Tech": ["hitech", "hi-tech", "های تک"], "Felicity": ["felicity", "فلیسیتی"],
}


_SOLAR_RE = re.compile(r"خورشیدی|سولار|solar|فتوولتا|photovolt|mc4|سانورتر|sunverter|pv ")
_EXCLUDE_RE = re.compile(r"خودرو|فندکی|درایو|کنترل دور|موتور برق|ژنراتور|استابلایزر|لپ ?تاپ|پاور ?بانک|میلی ?آمپر|"
                         r"18650|قلمی|موبایل|گوشی|ساعت مچی|آتش ?نشانی|هوزریل|تاچ پنل|پنل ال ای دی|پنل led|"
                         r"بک ?لایت|فول ?لایت|پنل توکار|پنل روکار|مانیتور|^یو ?پی ?اس|^ups|wifi|breaker|heater|gloves|"
                         r"freight|wagon|charger|fridge|refrigerator|cover\b|\bcap\b|cable|adapter|trolling")
_PANEL_HINT_RE = re.compile(r"مونو|پلی ?کریستال|mono|poly|bifacial|بایفیشال|کریستال")


def is_relevant(title, hint, e):
    """آیا این کالا واقعاً به برق خورشیدی مربوط است؟ (فروشگاه‌های عمومی کالاهای نامربوط زیادی دارند)"""
    t, h = norm(title), norm(hint)
    solar = bool(_SOLAR_RE.search(t + " ") or _SOLAR_RE.search(h + " "))
    if _EXCLUDE_RE.search(t) and not solar:
        return False
    cat = e["category"]
    if cat in ("inverter", "controller", "battery"):
        return solar or e["qty"] is not None
    if cat == "panel":
        return solar or (e["qty"] is not None and bool(_PANEL_HINT_RE.search(t)))
    if cat == "structure":
        return solar or "پنل" in t
    return solar


def classify(title_n, hint=""):
    if _EXCLUDE_RE.search(title_n) and not _SOLAR_RE.search(title_n + " "):
        return "other"
    if re.search(r"\b(mount|mounts|mounting|bracket|brackets|racking)\b", title_n):
        return "structure"
    best, pos = None, 10 ** 9
    for cat, words in _CAT_WORDS:
        for w in words:
            i = title_n.find(w)
            if 0 <= i < pos:
                best, pos = cat, i
    if best:
        return best
    h = norm(hint)
    for cat, words in _CAT_WORDS:
        if any(w in h for w in words):
            return cat
    return "other"


def find_brand(title_n):
    t = title_n + " "
    for brand, aliases in BRANDS.items():
        if any(a in t for a in aliases):
            return brand
    return ""


_RE_KWH = re.compile(r"(\d+(?:\.\d+)?)\s*(?:kwh|کیلو ?وات ?ساعت)")
_RE_KW = re.compile(r"(\d+(?:\.\d+)?)\s*(?:kw|kva|کیلو ?وات|کاوا|کیلو ?ولت ?آمپر)")
_RE_W = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*(?:watts?|wp|w|وات)(?![a-z\u0600-\u06ff])")
_RE_AH = re.compile(r"(\d+(?:\.\d+)?)\s*(?:ah|آمپر ?ساعت|امپر ?ساعت|آمپر|امپر)")
_RE_A = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*(?:amps?|a|آمپر|امپر)(?![a-z\u0600-\u06ff])")
_RE_V = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*(?:volts?|v|ولت)(?![a-z\u0600-\u06ff])")
_RE_SLOTS = re.compile(r"(\d+)\s*-?\s*(?:پنل|پانل|عدد پنل|تایی|عددی|panels?\b)")
_RE_PACK = re.compile(r"(\d+)\s*-?\s*(?:pack|packs|pcs|pieces|sets)\b|\bx\s*(\d+)\b|\b(\d+)\s*x\s")
_BATT_V = {2, 6, 12, 12.8, 24, 25.6, 36, 48, 51.2}


def enrich(title, hint="", price=None):
    """از عنوان کالا: دسته، برند، مشخصات، مقدار واحد (برای قیمتِ واحد) و گروه مقایسه را درمی‌آورد."""
    t = norm(title)
    cat = classify(t, hint)
    specs, qty, unit, group = [], None, "", ""
    kwh = _RE_KWH.search(t)
    t_nokwh = _RE_KWH.sub(" ", t)
    kw = _RE_KW.search(t_nokwh)
    w = _RE_W.search(t_nokwh)
    v = _RE_V.search(t)
    pack = _RE_PACK.search(t)
    multi_pack = bool(pack) and any(g and int(g) > 1 for g in pack.groups())    # بستهٔ چندتایی: مقایسهٔ واحد غلط می‌شود

    if cat == "panel":
        watts = num(w.group(1)) if w else (num(kw.group(1)) * 1000 if kw else None)
        if watts and 5 <= watts <= 800:
            specs.append("%g وات" % watts)
            qty, unit = watts, "تومان بر وات"
            band = "کوچک (تا ۶۰ وات)" if watts <= 60 else "متوسط (۶۰ تا ۳۰۰ وات)" if watts <= 300 else "بزرگ (بالای ۳۰۰ وات)"
            group = "پنل " + band
        if "مونو" in t or "mono" in t:
            specs.append("مونو")
        elif "پلی" in t or "poly" in t:
            specs.append("پلی")
    elif cat == "inverter":
        p = num(kw.group(1)) if kw else (num(w.group(1)) / 1000 if w and num(w.group(1)) >= 300 else None)
        kind = ("هیبرید" if ("هیبرید" in t or "hybrid" in t) else
                "پمپ" if "پمپ" in t else
                "آنگرید" if re.search(r"آن ?گرید|on ?-?grid|متصل به شبکه", t) else
                "آفگرید" if re.search(r"آف ?گرید|off ?-?grid|منفصل", t) else
                "شبه‌سینوسی" if "شبه سینوسی" in t else
                "سانورتر" if re.search(r"سانورتر|سانوتر|sunverter|اینورتر ?شارژر|با شارژر|mppt|inverter.?charger|"
                                         r"all.in.one|solar charger", t) else "عمومی")
        if kind != "عمومی":
            specs.append(kind)
        if p and 0.3 <= p <= 500:
            specs.append("%g کیلووات" % p)
            qty, unit = p, "تومان بر کیلووات"
            band = "تا ۲ کیلووات" if p < 2 else "۲ تا ۶ کیلووات" if p <= 6 else "۶ تا ۱۵ کیلووات" if p <= 15 else "بالای ۱۵ کیلووات"
            group = "اینورتر %s، %s" % (kind, band)
    elif cat == "battery":
        chem = ("لیتیومی" if re.search(r"لیتیوم|lithium|lifepo4|li-ion|دیواری|رک مونت|rack|wall|pylontech|dyness", t) else
                "ژل" if ("ژل" in t or "gel" in t) else "لیتیومی" if kwh else "سرب‌اسید")
        specs.append(chem)
        ah = _RE_AH.search(t)
        volts = num(v.group(1)) if v else None
        if volts not in _BATT_V:
            volts = None
        wh = None
        if kwh:
            wh = num(kwh.group(1)) * 1000
        elif ah:
            a = num(ah.group(1))
            if volts is None and chem != "لیتیومی" and a and price and price / a > 700_000:
                chem = specs[0] = "لیتیومی"      # خیلی گران‌تر از سرب‌اسید: لیتیومی با ولتاژ نامعلوم، مقایسه نشود
            if volts is None and chem != "لیتیومی":
                volts = 12.0
            if a and volts and 4 <= a <= 3000:
                wh = a * volts
        if ah:
            specs.append("%g آمپرساعت" % num(ah.group(1)))
        if volts:
            specs.append("%g ولت" % volts)
        if wh and 20 <= wh <= 500_000:
            qty, unit = wh / 1000.0, "تومان بر کیلووات‌ساعت"
            group = "باتری " + chem
            if chem != "لیتیومی":
                group += " کوچک (زیر ۴۰ آمپرساعت)" if wh < 480 else ""
    elif cat == "controller":
        a = _RE_A.search(t)
        kind = "MPPT" if "mppt" in t else "PWM" if "pwm" in t else ""
        if kind:
            specs.append(kind)
        if a and 5 <= num(a.group(1)) <= 250:
            specs.append("%g آمپر" % num(a.group(1)))
            qty, unit = num(a.group(1)), "تومان بر آمپر"
            group = "شارژ کنترلر " + (kind or "عمومی")
    elif cat == "structure":
        part = re.search(r"کلمپ|بست|پیچ|مهره|ریل|ناودانی|پروفیل", t) and not re.search(r"سازه|استراکچر|پایه", t)
        s = None if part else _RE_SLOTS.search(t)
        if not s and not part:
            w_ = re.search(r"\b(single|dual|double|triple)\b", t)
            if w_:
                s = re.match(r"(\d)", {"single": "1", "dual": "2", "double": "2", "triple": "3"}[w_.group(1)])
        if part:
            specs.append("اتصالات سازه")
        if s and 1 <= int(s.group(1)) <= 60:
            specs.append("%s پنل" % s.group(1))
            qty, unit = int(s.group(1)), "تومان بر هر پنل"
            group = "استراکچر (به ازای هر پنل)"
        elif kw and 1 <= num(kw.group(1)) <= 5000 and not part:
            specs.append("%g کیلووات" % num(kw.group(1)))
            qty, unit = num(kw.group(1)), "تومان بر کیلووات"
            group = "استراکچر (به ازای هر کیلووات)"
        if re.search(r"شیروانی|سقف شیبدار", t):
            specs.append("شیروانی")
        elif "زمینی" in t:
            specs.append("زمینی")
        if "آلومینیوم" in t or "آلمینیوم" in t:
            specs.append("آلومینیوم")
        elif "گالوانیزه" in t:
            specs.append("گالوانیزه")
    if multi_pack:
        qty, unit, group = None, "", ""
    return {"category": cat, "brand": find_brand(t), "specs": specs, "qty": qty, "unit": unit, "group": group}


# --------------------------------------------------------------------------
# دریافت صفحه از اینترنت
# --------------------------------------------------------------------------
_host_lock = threading.Lock()
_host_next = {}


def quote_url(url):
    return urllib.parse.quote(url, safe=":/?&=%~+#@,;!$'()*[]")


def http_get(url, payload=None, headers=None, timeout=20, retries=1):
    host = urllib.parse.urlsplit(url).netloc
    last_err = None
    for attempt in range(retries + 1):
        with _host_lock:
            now = time.time()
            at = max(now, _host_next.get(host, 0))
            _host_next[host] = at + HOST_DELAYS.get(host, HOST_DELAY)
        if at > now:
            time.sleep(at - now)
        h = {"User-Agent": UA, "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.6",
             "Accept-Encoding": "gzip, deflate",
             "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        try:
            req = urllib.request.Request(quote_url(url), data=data, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                enc = (r.headers.get("Content-Encoding") or "").lower()
                if enc == "gzip":
                    raw = gzip.decompress(raw)
                elif enc == "deflate":
                    try:
                        raw = zlib.decompress(raw)
                    except zlib.error:
                        raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                charset = r.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (400, 401, 403, 404, 410):
                break
        except Exception as e:
            last_err = e
        time.sleep(1.5 * (attempt + 1))
    raise last_err


def explain(e):
    """پیام خطای قابل‌فهم برای صفحه."""
    if isinstance(e, urllib.error.HTTPError):
        m = {403: "سایت دسترسی برنامه را مسدود کرد (403)", 404: "نشانی پیدا نشد (404)",
             429: "تعداد درخواست زیاد بود (429)"}
        return m.get(e.code, "خطای سایت (%s)" % e.code)
    s = str(e)
    if "timed out" in s or "timeout" in s.lower():
        return "سایت پاسخ نداد (اینترنت یا فیلترشکن را بررسی کنید)"
    if "getaddrinfo" in s or "Name or service" in s or "resolution" in s:
        return "نشانی سایت پیدا نشد (اتصال اینترنت را بررسی کنید)"
    if "refused" in s or "unreachable" in s or "reset" in s:
        return "اتصال به سایت برقرار نشد"
    if "CERTIFICATE" in s.upper() or "SSL" in s.upper():
        return "خطای اتصال امن (SSL)"
    return s[:160] or e.__class__.__name__


def walk(obj):
    """همهٔ دیکشنری‌های داخل یک JSON تو در تو را برمی‌گرداند."""
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            yield o
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)


def item(title, url, price, seller="", image="", in_stock=True, hint=""):
    return {"title": clean_title(title), "url": url, "price": int(price), "seller": seller,
            "image": image or "", "in_stock": bool(in_stock), "hint": hint}


# --------------------------------------------------------------------------
# منبع ۱: ترب
# --------------------------------------------------------------------------
def scrape_torob(cfg):
    tc = cfg["torob"]
    api = tc.get("api", "https://api.torob.com/v4/base-product/search/")
    out, errors = {}, []
    for q in cfg["queries"]:
        url = api + "?" + urllib.parse.urlencode({"page": 0, "sort": "popularity", "size": 24, "q": q})
        for _ in range(int(tc.get("pages_per_query", 4))):
            try:
                data = json.loads(http_get(url, headers={"Referer": "https://torob.com/"}))
            except Exception as e:
                errors.append(e)
                break
            results = data.get("results") or []
            for r in results:
                price = r.get("price") or 0
                name = r.get("name1") or r.get("name2") or ""
                path = r.get("web_client_absolute_url") or ""
                if not name or not path or not price or price < 1000:
                    continue
                link = urllib.parse.urljoin("https://torob.com", path)
                out[link] = item(name, link, price, seller="ترب " + clean_title(r.get("shop_text") or ""),
                                 image=r.get("image_url") or "",
                                 in_stock=(r.get("stock_status") or "") != "ناموجود")
            url = data.get("next")
            if not url or not results:
                break
    if not out and errors:
        raise errors[0]
    return list(out.values())


# --------------------------------------------------------------------------
# منبع ۲: دیوار
# --------------------------------------------------------------------------
_PRK_RE = re.compile(r"/p/([0-9a-fA-F-]{20,40})/")


def scrape_torob_sellers(cfg):
    """برای هر کالای ترب، قیمتِ تک‌تکِ فروشگاه‌هایی که آن را می‌فروشند را می‌گیرد.
    هر فروشگاه یک منبع جداست؛ در هر اجرا بخشی از کالاها (قدیمی‌ترین‌ها) تازه می‌شوند."""
    tc = cfg["torob"]
    api = tc.get("details_api", "https://api.torob.com/v4/base-product/details/")
    limit = int(tc.get("seller_products_per_run", 250))
    with _db_lock:
        rows = db().execute("SELECT url, title, category FROM items WHERE source='torob' AND active=1").fetchall()
        done = dict(db().execute("SELECT prk, ts FROM seller_fetch").fetchall())
    products = []
    for r in rows:
        m = _PRK_RE.search(r["url"])
        if m and r["category"] != "other":
            products.append((done.get(m.group(1), 0), m.group(1), r["url"], r["title"]))
    if not products:
        raise RuntimeError("هنوز کالایی از ترب نیامده است؛ بعد از پاسخ ترب، فروشنده‌ها هم می‌آیند")
    products.sort()
    out, errors, fails = [], [], 0
    for _, prk, url, title in products[:limit]:
        try:
            data = json.loads(http_get(api + "?" + urllib.parse.urlencode({"prk": prk, "source": "next_desktop"}),
                                       headers={"Referer": "https://torob.com/"}))
        except Exception as e:
            errors.append(e)
            fails += 1
            if fails >= 2:      # ترب مسدود کرده است: ادامه نده تا وضع بدتر نشود
                break
            continue
        offers = ((data.get("products_info") or {}).get("result")) if isinstance(data.get("products_info"), dict) else None
        if not offers:
            offers = [d for d in walk(data) if d.get("shop_name") and d.get("price")]
        base_title = data.get("name1") or title
        for o in offers:
            price, shop = num(o.get("price")), clean_title(o.get("shop_name") or "")
            if not price or price < 1000 or not shop:
                continue
            link = urllib.parse.urljoin("https://torob.com", o.get("page_url") or url)
            it = item(o.get("name1") or base_title, link, price, seller=shop,
                      in_stock=o.get("availability", True) is not False)
            it["uid"] = "%s|%s" % (prk, o.get("shop_id") or shop)
            out.append(it)
        with _db_lock:
            db().execute("INSERT OR REPLACE INTO seller_fetch VALUES(?,?)", (prk, int(time.time())))
            db().commit()
    if not out and errors:
        raise errors[0]
    return out


def scrape_divar(cfg):
    dc = cfg["divar"]
    api = dc.get("api", "https://api.divar.ir/v8/postlist/w/search")
    out, errors = {}, []
    for q in cfg["queries"]:
        body = {"city_ids": [str(c) for c in dc.get("city_ids", ["1"])],
                "search_data": {"form_data": {"data": {"category": {"str": {"value": "ROOT"}}}}, "query": q}}
        try:
            data = json.loads(http_get(api, payload=body, headers={"Origin": "https://divar.ir",
                                                                   "Referer": "https://divar.ir/"}))
        except Exception as e:
            errors.append(e)
            continue
        for d in walk(data):
            title = d.get("title")
            desc = " ".join(str(d.get(k) or "") for k in ("middle_description_text", "top_description_text",
                                                           "bottom_description_text"))
            if not isinstance(title, str) or not desc.strip():
                continue
            token = d.get("token") or ((d.get("action") or {}).get("payload") or {}).get("token")
            prices = parse_prices(desc)
            if not token or not prices:
                continue
            link = "https://divar.ir/v/" + str(token)
            img = d.get("image_url")
            if isinstance(img, list):
                img = (img[0] or {}).get("src") if img and isinstance(img[0], dict) else ""
            out[link] = item(title, link, prices[0], seller="آگهی دیوار", image=img if isinstance(img, str) else "")
    if not out and errors:
        raise errors[0]
    return list(out.values())


# --------------------------------------------------------------------------
# استخراج عمومی کالا از هر صفحهٔ HTML (ایمالز و فروشگاه‌های غیر ووکامرس)
# --------------------------------------------------------------------------
class _Cards(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens = []      # ["a", href, title_attr, [texts]]  یا  ["t", text]
        self.skip = 0
        self.anchor = None
        self.ld = []
        self._ld = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and "ld+json" in (a.get("type") or ""):
            self._ld = []
            return
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
        elif tag == "a" and a.get("href"):
            self.anchor = ["a", a["href"], a.get("title") or a.get("aria-label") or "", [], ""]
            self.tokens.append(self.anchor)
        elif tag == "img" and self.anchor is not None:
            self.anchor[4] = self.anchor[4] or a.get("alt") or ""
        elif tag in ("del", "s", "strike"):
            self.tokens.append(["del", 1])
        elif tag in ("li", "article", "tr"):
            self.tokens.append(["sep"])

    def handle_endtag(self, tag):
        if tag == "script" and self._ld is not None:
            self.ld.append("".join(self._ld))
            self._ld = None
        elif tag in ("script", "style", "noscript", "svg"):
            self.skip = max(0, self.skip - 1)
        elif tag == "a":
            self.anchor = None
            self.tokens.append(["sep_a"])
        elif tag in ("del", "s", "strike"):
            self.tokens.append(["del", 0])

    def handle_data(self, data):
        if self._ld is not None:
            self._ld.append(data)
            return
        if self.skip or not data.strip():
            return
        if self.anchor is not None:
            self.anchor[3].append(data)
        if self.tokens and self.tokens[-1][0] == "t":
            self.tokens[-1][1] += " " + data
        else:
            self.tokens.append(["t", data])


_NAV = ("سبد", "ورود", "ثبت نام", "تماس", "درباره", "مقایسه", "علاقه", "افزودن", "مشاهده", "ادامه", "خرید")


def extract_products(page_html, base_url, seller):
    """کالاها را از HTML درمی‌آورد: اول داده‌های ساختاریافته (JSON-LD)، بعد حدس از روی لینک و قیمت."""
    p = _Cards()
    try:
        p.feed(page_html)
    except Exception:
        pass
    found = {}

    for block in p.ld:
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        for d in walk(data):
            if d.get("@type") not in ("Product", ["Product"]):
                continue
            offers = d.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = num(offers.get("price") or offers.get("lowPrice"))
            url = d.get("url") or offers.get("url")
            if not (price and url and d.get("name")):
                continue
            if str(offers.get("priceCurrency", "")).upper() == "IRR":
                price /= 10
            if price >= 1000:
                link = urllib.parse.urljoin(base_url, url)
                img = d.get("image")
                img = img[0] if isinstance(img, list) and img else img
                found[link] = item(d["name"], link, price, seller=seller, image=img if isinstance(img, str) else "",
                                   in_stock="OutOfStock" not in str(offers.get("availability", "")))

    # حدس از روی ترتیب «لینکِ کالا» و «قیمت» در صفحه
    cur, in_del, cand = None, False, {}
    for tok in p.tokens:
        kind = tok[0]
        if kind == "a":
            title = ""
            for raw in (" ".join(tok[3]), tok[2], tok[4]):      # متن لینک، بعد title، بعد alt عکس
                raw = clean_title(_PRICE_RE.sub(" ", clean_title(raw).translate(_DIGITS))).strip(" -|،")
                if len(raw) >= 10 and not any(raw.startswith(n) for n in _NAV) and classify(norm(raw)) != "other":
                    title = raw
                    break
            href = urllib.parse.urljoin(base_url, tok[1])
            if title and href.startswith("http"):
                cur = cand.setdefault(href, {"title": title, "prices": []})
        elif kind == "del":
            in_del = bool(tok[1])
        elif kind == "t" and cur is not None and not in_del:
            cur["prices"].extend(parse_prices(tok[1]))
    for href, c in cand.items():
        if c["prices"] and href not in found:
            found[href] = item(c["title"], href, min(c["prices"][:3]), seller=seller)

    # جدول قیمت بدون لینک (مثل صفحه‌های «لیست قیمت»): هر ردیف = نام + قیمت
    if not found:
        row = []
        for tok in p.tokens + [["sep"]]:
            if tok[0] == "sep":
                text = " ".join(row)
                prices = parse_prices(text)
                name = clean_title(_PRICE_RE.sub("", norm(text)))
                if prices and len(name) >= 8 and classify(norm(name)) != "other":
                    key = base_url + "#" + name[:80]
                    found.setdefault(key, dict(item(name, base_url, prices[-1], seller=seller), uid=key))
                row = []
            elif tok[0] == "t":
                row.append(tok[1])
    return list(found.values())


def scrape_pages(pages, seller, paginate=True, max_pages=8):
    out, errors = {}, []
    for start in pages:
        url = start
        for n in range(1, max_pages + 1):
            try:
                page = http_get(url)
            except Exception as e:
                if n == 1:
                    errors.append(e)
                break
            before = len(out)
            for it in extract_products(page, url, seller):
                out.setdefault(it["url"] + "|" + it["title"], it)
            nxt = "/page/%d" % (n + 1)
            if not paginate or len(out) == before or nxt not in page:
                break
            url = start.rstrip("/") + nxt + "/"
    if not out and errors:
        raise errors[0]
    return list(out.values())


def scrape_emalls(cfg):
    ec = cfg["emalls"]
    pages = list(ec.get("pages") or [])
    pages += ["https://emalls.ir/لیست-قیمت~kw~" + q for q in cfg["queries"]]
    items = scrape_pages(pages, "ایمالز", paginate=False)
    if not items:
        raise RuntimeError("کالایی در صفحه‌های ایمالز پیدا نشد (ساختار صفحه عوض شده است)")
    return items


# --------------------------------------------------------------------------
# منبع ۳: فروشگاه‌ها (ووکامرس به‌صورت خودکار، وگرنه خواندن صفحه)
# --------------------------------------------------------------------------
_CURRENCY = {"IRT": 1, "IRR": 0.1, "IRHT": 1000, "IRHR": 100, "TOMAN": 1}


def woo_api(base, seller):
    out = []
    for path in ("/wp-json/wc/store/v1/products", "/wp-json/wc/store/products"):
        try:
            for page in range(1, 21):
                data = json.loads(http_get("%s%s?per_page=100&page=%d" % (base, path, page)))
                if not isinstance(data, list) or not data:
                    break
                for pr in data:
                    prices = pr.get("prices") or {}
                    raw = num(prices.get("price"))
                    if not raw:
                        continue
                    price = raw / (10 ** int(prices.get("currency_minor_unit") or 0))
                    price *= _CURRENCY.get(str(prices.get("currency_code", "IRT")).upper(), 1)
                    if price < 1000:
                        continue
                    cats = " ".join(c.get("name", "") for c in pr.get("categories") or [])
                    imgs = pr.get("images") or []
                    out.append(item(pr.get("name", ""), pr.get("permalink") or base, price, seller=seller,
                                    image=(imgs[0].get("thumbnail") or imgs[0].get("src", "")) if imgs else "",
                                    in_stock=pr.get("is_in_stock", True), hint=cats))
                if len(data) < 100:
                    break
            if out:
                return out
        except urllib.error.HTTPError as e:
            log.info("woo api %s%s: %s", base, path, e)
        except ValueError as e:              # پاسخ JSON نبود: این سایت ووکامرس نیست
            log.info("woo api %s%s: not json (%s)", base, path, e)
            break
    return out


def scrape_shop(shop):
    base = shop["url"].rstrip("/")
    name = shop.get("name") or urllib.parse.urlsplit(base).netloc
    items = []
    if shop.get("mode", "auto") in ("auto", "woo"):
        items = woo_api(base, name)
    pages = shop.get("pages") or ([] if items else [base + "/shop/", base + "/"])
    if pages:
        seen = {i["url"] for i in items}
        try:
            for it in scrape_pages(pages, name):
                if it["url"] not in seen or it["url"] in pages:
                    items.append(it)
        except Exception:
            if not items:
                raise
    if not items:
        raise RuntimeError("قیمتی در این سایت پیدا نشد (شاید قیمت‌ها «تماس بگیرید» هستند)")
    return items


def _solar_related(title):
    t = norm(title)
    return classify(t) != "other" or "خورشیدی" in t or "سولار" in t or "solar" in t


def scrape_digikala(cfg):
    dc = cfg["digikala"]
    api = dc.get("api", "https://api.digikala.com/v1/search/")
    out, errors = {}, []
    for q in cfg["queries"]:
        for page in range(1, int(dc.get("pages_per_query", 2)) + 1):
            try:
                data = json.loads(http_get(api + "?" + urllib.parse.urlencode({"q": q, "page": page})))
            except Exception as e:
                errors.append(e)
                break
            products = ((data.get("data") or {}).get("products")) or []
            for pr in products:
                price = num((((pr.get("default_variant") or {}) if isinstance(pr.get("default_variant"), dict)
                              else {}).get("price") or {}).get("selling_price"))
                title = pr.get("title_fa") or ""
                uri = (pr.get("url") or {}).get("uri") or ("/product/dkp-%s/" % pr.get("id"))
                if not price or not title or not _solar_related(title):
                    continue
                link = urllib.parse.urljoin("https://www.digikala.com", uri)
                img = (((pr.get("images") or {}).get("main") or {}).get("url") or [""])
                out[link] = item(title, link, price / 10, seller="دیجی‌کالا",          # قیمت دیجی‌کالا به ریال است
                                 image=img[0] if isinstance(img, list) and img else "",
                                 in_stock=pr.get("status", "marketable") == "marketable")
            if not products:
                break
    if not out and errors:
        raise errors[0]
    return list(out.values())


def scrape_sheypoor(cfg):
    pages = ["https://www.sheypoor.com/s/iran?q=" + q.replace(" ", "+") for q in cfg["queries"]]
    pages += ["https://www.sheypoor.com/l/" + q.replace(" ", "-") for q in cfg["queries"][:3]]
    items = [i for i in scrape_pages(pages, "آگهی شیپور", paginate=False) if _solar_related(i["title"])]
    if not items:
        raise RuntimeError("آگهی‌ای در صفحه‌های شیپور پیدا نشد (ساختار صفحه عوض شده است)")
    return items


def global_id(store):
    return "g:" + urllib.parse.urlsplit(store["url"]).netloc.replace("www.", "")


def scrape_shopify(store):
    """فروشگاهِ رسمیِ سازنده (Shopify): قیمت‌ها همان دلاری است که روی سایت خودشان نوشته‌اند. قیمت به سِنت ذخیره می‌شود."""
    base = store["url"].rstrip("/")
    out = []
    for page in range(1, 5):
        data = json.loads(http_get("%s/products.json?limit=250&page=%d" % (base, page), timeout=30))
        prods = data.get("products") or []
        for p in prods:
            title = p.get("title") or ""
            tags = p.get("tags") or []
            hint = "%s %s" % (p.get("product_type") or "", " ".join(tags) if isinstance(tags, list) else tags)
            variants = p.get("variants") or []
            imgs = p.get("images") or []
            for v in variants[:12]:
                price = num(v.get("price"))
                if not price or price < 1:
                    continue
                vt = str(v.get("title") or "")
                single = len(variants) == 1 or vt.lower() == "default title"
                link = "%s/products/%s" % (base, p.get("handle"))
                it = item(title if single else "%s — %s" % (title, vt), link if single else "%s?variant=%s" % (link, v.get("id")),
                          round(price * 100), seller=store.get("name") or base,
                          image=(imgs[0].get("src") if imgs else ""), in_stock=v.get("available", True), hint=hint)
                it["uid"] = str(v.get("id") or it["url"])
                out.append(it)
        if len(prods) < 250:
            break
    if not out:
        raise RuntimeError("قیمتی از این سایت دریافت نشد")
    return out


class _Rows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def update_spot(cfg):
    """قیمت عمدهٔ جهانیِ پنل (دلار بر وات) از جدول هفتگیِ InfoLink."""
    if not (cfg.get("global") or {}).get("spot", True):
        return
    try:
        p = _Rows()
        p.feed(http_get("https://www.infolink-group.com/spot-price/", retries=0, timeout=25))
        spot = []
        for row in p.rows:
            text = " | ".join(row)
            if not re.search(r"module", row[0], re.I) or "USD" not in text.upper():
                continue
            nums = [float(x) for x in re.findall(r"(?<![\d.])0\.\d{2,4}(?![\d])", text)]
            if not nums:
                continue
            avg = nums[2] if len(nums) >= 3 else nums[-1]
            if 0.03 <= avg <= 1.5 and len(spot) < 4:
                spot.append({"name": row[0][:70], "usd": avg, "high": nums[0], "low": nums[1] if len(nums) > 1 else avg})
        if spot:
            STATE["spot"] = {"items": spot, "source": "InfoLink", "ts": int(time.time())}
            log.info("SPOT %s", ", ".join("%s=$%.3f" % (x["name"][:30], x["usd"]) for x in spot))
        else:
            log.warning("SPOT infolink: no USD module rows found (%d table rows)", len(p.rows))
    except Exception as e:
        log.warning("SPOT infolink failed: %s: %s", e.__class__.__name__, e)


_USD_RE = re.compile(r"US\s*\$\s*([\d,]+(?:\.\d+)?)(?:\s*-\s*(?:US\s*\$\s*)?([\d,]+(?:\.\d+)?))?", re.I)
_MOQ_RE = re.compile(r"([\d,]+)\s*(wp|watts?|w|kw|pieces?|pcs|sets?|units?)\b", re.I)


def _title_has_watts(title_n, watts):
    """آیا عنوان آگهی این توان را پوشش می‌دهد؟ (مثلاً «615-635 Watt» یا «620W 625W 630W»)"""
    nums = [int(x) for x in re.findall(r"(?<!\d)(\d{3})(?!\d)", title_n)]
    if watts in nums:
        return True
    return any(int(a) <= watts <= int(b) for a, b in re.findall(r"(\d{3})\s*(?:-|~|to)\s*(\d{3})", title_n))


def scrape_fob(cfg):
    """قیمت دلاریِ مدل‌های برند از فروشنده‌های چینی (Made-in-China). قیمت‌ها FOB و به دلار خودِ آگهی است."""
    out, errors = {}, []
    for m in (cfg.get("fob") or {}).get("models", []):
        url = "https://www.made-in-china.com/products-search/hot-china-products/%s.html" % re.sub(r"[^A-Za-z0-9.]+", "_", m["q"]).strip("_")
        try:
            page = http_get(url, timeout=30)
        except Exception as e:
            errors.append(e)
            if len(errors) >= 3 and not out:
                break
            continue
        p = _Cards()
        try:
            p.feed(page)
        except Exception:
            pass
        cur, cards = None, []
        for tok in p.tokens:
            if tok[0] == "a":
                text = clean_title(" ".join(tok[3]) or tok[2] or tok[4])
                href = urllib.parse.urljoin(url, tok[1])
                if "/product/" in href and len(text) >= 15:
                    cur = {"title": text, "url": href.split("?")[0], "lo": None, "hi": None, "moq": ""}
                    cards.append(cur)
                elif cur is not None and not cur.get("seller") and ".made-in-china.com" in href and \
                        re.search(r"co\.|ltd|limited|company|technolog", text, re.I):
                    cur["seller"] = text[:60]
            elif tok[0] == "t" and cur is not None:
                if cur["lo"] is None:
                    pm = _USD_RE.search(tok[1])
                    if pm:
                        cur["lo"] = float(pm.group(1).replace(",", ""))
                        cur["hi"] = float((pm.group(2) or pm.group(1)).replace(",", ""))
                if not cur["moq"] and "moq" in tok[1].lower():
                    mm = _MOQ_RE.search(tok[1])
                    cur["moq"] = (mm.group(1) + " " + mm.group(2)) if mm else ""
        must = [w.lower() for w in m.get("must") or [m["brand"].lower().split()[0]]]
        for c in cards:
            if c["lo"] is None:
                continue
            tn = norm(c["title"])
            if not all(w in tn for w in must):
                continue
            mid = (c["lo"] + c["hi"]) / 2
            if m["cat"] == "panel":
                w = int(m["watts"])
                if not _title_has_watts(tn, w):
                    continue
                if c["hi"] <= 2:                       # قیمت به ازای هر وات
                    piece, rng = mid * w, "$%.3f–%.3f هر وات" % (c["lo"], c["hi"])
                elif 15 <= mid <= 600:                 # قیمت به ازای هر پنل
                    piece, rng = mid, "$%.0f–%.0f هر پنل" % (c["lo"], c["hi"])
                else:
                    continue
                qty, unit = float(w), "تومان بر وات"
                if not 0.04 <= piece / w <= 1.0:
                    continue
            else:
                kw = float(m["kw"])
                if not 15 * kw <= mid <= 900 * kw:     # بازهٔ معقول برای اینورتر (دلار بر کیلووات)
                    continue
                piece, rng, qty, unit = mid, "$%.0f–%.0f هر دستگاه" % (c["lo"], c["hi"]), kw, "تومان بر کیلووات"
            specs = [rng] + (["حداقل سفارش " + c["moq"]] if c["moq"] else []) + ["FOB چین"]
            it = item("%s — %s" % (m["label"], c["title"]), c["url"], round(piece * 100),
                      seller=c.get("seller") or "فروشندهٔ Made-in-China")
            it["uid"] = m["label"] + "|" + c["url"]
            it["force"] = {"category": m["cat"], "brand": m["brand"], "specs": specs, "qty": qty, "unit": unit,
                           "group": "FOB|" + m["label"]}
            out[it["uid"]] = it
    if not out:
        raise errors[0] if errors else RuntimeError("آگهی قیمت‌داری برای مدل‌ها پیدا نشد (ساختار صفحه عوض شده است)")
    return list(out.values())


# --------------------------------------------------------------------------
# فهرست تماس روزانه (داروخانه‌های تهران از فهرست‌های عمومی)
# --------------------------------------------------------------------------
class _Lines(HTMLParser):
    """متن صفحه را خط‌به‌خط می‌کند؛ خانه‌های یک ردیفِ جدول با « | » در یک خط می‌مانند."""
    BLOCK = {"tr", "li", "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "br", "article", "section", "table", "ul"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines, self.buf, self.skip = [], [], 0

    def _flush(self):
        text = " ".join("".join(self.buf).split())
        if text.strip(" |"):
            self.lines.append(text)
        self.buf = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
        elif tag in self.BLOCK:
            self._flush()
        elif tag in ("td", "th"):
            self.buf.append(" | ")
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            if href.startswith("tel:"):
                self.buf.append(" " + href[4:] + " ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)


_TEL_RE = re.compile(r"(?<!\d)(?:\+98|0098|0)?\s*(?:21)?[\s\-–)]{0,2}([2-9]\d{3})[\s\-–]?(\d{4})(?!\d)")
_MOB_RE = re.compile(r"(?<!\d)(?:\+98|0098|0)(9\d{9})(?!\d)")
_ADDR_RE = re.compile(r"خیابان|خ |بلوار|میدان|کوچه|پلاک|بزرگراه|شهرک|نبش|روبه ?رو|روبرو|تقاطع|چهارراه|جنب|فلکه")


def extract_leads(page_html, keyword="داروخانه"):
    p = _Lines()
    try:
        p.feed(page_html)
        p._flush()
    except Exception:
        pass
    lines = [norm(x) for x in p.lines]
    name_re = re.compile(re.escape(keyword) + r"\s+[^|،,:؛(]{2,45}")
    has_phone = [bool(_TEL_RE.search(x) or _MOB_RE.search(x)) for x in lines]
    out = {}
    for idx, line in enumerate(lines):
        phones = ["021" + a + b for a, b in _TEL_RE.findall(_MOB_RE.sub(" ", line))] + ["0" + m for m in _MOB_RE.findall(line)]
        if not phones:
            continue
        name, address, start = "", "", idx
        for j in range(idx, max(-1, idx - 7), -1):
            if j < idx and has_phone[j]:          # به رکورد قبلی رسیدیم
                break
            m = name_re.search(lines[j])
            if m:
                name = re.split(r"\s(?:تلفن|شماره|آدرس|نشانی|تماس)(?:\s|$)", _TEL_RE.split(m.group(0))[0] + " ")[0].strip(" -–|.")
                start = j
                break
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if not name and len(cells) >= 3:          # ردیف جدول که ستون نامش کلمهٔ «داروخانه» ندارد
            cand = [c for c in cells if 3 <= len(c) <= 40 and not re.search(r"\d{3}", c) and not _ADDR_RE.search(c)]
            if cand:
                name = keyword + " " + cand[0]
        if len(name) < len(keyword) + 3:
            continue
        for j in range(start, idx + 1):
            for seg in lines[j].split("|"):
                if not address and _ADDR_RE.search(seg) and len(seg) >= 10:
                    address = re.sub(r"^\s*(آدرس|نشانی)\s*:?\s*", "", _TEL_RE.sub("", seg)).strip(" -–:،,")[:160]
        reg = re.search(r"منطقه\s*(\d{1,2})", " ".join(lines[start:idx + 1]))
        extra = (" · تلفن دوم: " + phones[1]) if len(phones) > 1 else ""       # هر داروخانه فقط یک ردیف
        out.setdefault(phones[0], {"phone": phones[0], "name": name[:60], "address": address + extra,
                                   "region": reg.group(1) if reg else ""})
    return list(out.values())


def scrape_leads(cfg):
    lc = cfg["leads"]
    found, errors = {}, []
    for url in lc.get("pages", []):
        try:
            page = http_get(url, timeout=30)
        except Exception as e:
            errors.append(e)
            log.info("leads %s: %s", url, e)
            continue
        got = extract_leads(page, lc.get("keyword", "داروخانه"))
        log.info("leads %s: %d numbers", url, len(got))
        host = urllib.parse.urlsplit(url).netloc.replace("www.", "")
        for g in got:
            found.setdefault(g["phone"], dict(g, source=host))
    if not found:
        raise errors[0] if errors else RuntimeError("شماره‌ای در صفحه‌ها پیدا نشد")
    now = int(time.time())
    with _db_lock:
        c = db()
        for g in found.values():
            c.execute("INSERT OR IGNORE INTO leads(phone,name,address,region,source,first_seen) VALUES(?,?,?,?,?,?)",
                      (g["phone"], g["name"], g["address"], g["region"], g["source"], now))
        c.commit()
        return c.execute("SELECT COUNT(*) FROM leads").fetchone()[0]


def maybe_scrape_leads(cfg):
    """فهرست داروخانه‌ها روزی یک بار تازه می‌شود (نه هر ۳۰ دقیقه)."""
    if not (cfg.get("leads") or {}).get("enabled", True):
        return
    with _db_lock:
        st = db().execute("SELECT last_ok, ok FROM status WHERE source='leads'").fetchone()
        have = db().execute("SELECT COUNT(*) FROM leads WHERE day IS NULL").fetchone()[0]
    if st and st["last_ok"] and time.time() - st["last_ok"] < 20 * 3600 and have >= 10:
        return
    t0 = time.time()
    try:
        n = scrape_leads(cfg)
        set_status("leads", "فهرست تماس (داروخانه‌ها)", True, n, "", int((time.time() - t0) * 1000))
        log.info("OK   %-28s %4d numbers in bank", "leads", n)
    except Exception as e:
        set_status("leads", "فهرست تماس (داروخانه‌ها)", False, 0, explain(e), int((time.time() - t0) * 1000))
        log.warning("FAIL %-28s %s: %s", "leads", e.__class__.__name__, e)


def leads_payload(day=None, more=False):
    """فهرست تماس یک روز. برای امروز، اگر کم باشد از شماره‌های استفاده‌نشده پر می‌شود (هر شماره فقط یک بار)."""
    cfg = load_config()
    per_day = int((cfg.get("leads") or {}).get("per_day", 10))
    today = time.strftime("%Y-%m-%d")
    day = day if re.match(r"^\d{4}-\d{2}-\d{2}$", day or "") else today
    with _db_lock:
        c = db()
        if day == today:
            have = c.execute("SELECT COUNT(*) FROM leads WHERE day=?", (today,)).fetchone()[0]
            need = per_day if more else max(0, per_day - have)
            if need:
                rows = c.execute("SELECT phone FROM leads WHERE day IS NULL ORDER BY (address='') , (phone LIKE '09%'), "
                                 "substr(phone, -3), phone LIMIT ?", (need,)).fetchall()
                for r in rows:
                    c.execute("UPDATE leads SET day=? WHERE phone=?", (today, r["phone"]))
                c.commit()
        items = [dict(r) for r in c.execute("SELECT * FROM leads WHERE day=? ORDER BY rowid", (day,)).fetchall()]
        stats = dict(c.execute("SELECT COUNT(*) total, SUM(day IS NULL) unused, SUM(status!='') called, "
                               "SUM(status='interested') interested FROM leads").fetchone())
        days = [r["day"] for r in c.execute("SELECT DISTINCT day FROM leads WHERE day IS NOT NULL ORDER BY day DESC LIMIT 30")]
    return {"day": day, "today": today, "items": items, "stats": stats, "days": days, "per_day": per_day,
            "label": (cfg.get("leads") or {}).get("label", "داروخانه"),
            "enabled": (cfg.get("leads") or {}).get("enabled", True)}


def shop_id(shop):
    return "shop:" + urllib.parse.urlsplit(shop["url"]).netloc.replace("www.", "")


# --------------------------------------------------------------------------
# پایگاه داده
# --------------------------------------------------------------------------
_db_lock = threading.RLock()
_db = None


def db():
    global _db
    if _db is None:
        _db = sqlite3.connect(DB_PATH, check_same_thread=False)
        _db.row_factory = sqlite3.Row
        _db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS items(
          id INTEGER PRIMARY KEY, key TEXT UNIQUE, source TEXT, seller TEXT, title TEXT, url TEXT, image TEXT,
          category TEXT, brand TEXT, specs TEXT, qty REAL, unit TEXT, grp TEXT,
          price INTEGER, prev_price INTEGER, changed_at INTEGER, in_stock INTEGER,
          first_seen INTEGER, last_seen INTEGER, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS history(item_id INTEGER, ts INTEGER, price INTEGER);
        CREATE INDEX IF NOT EXISTS ix_hist ON history(item_id, ts);
        CREATE TABLE IF NOT EXISTS seller_fetch(prk TEXT PRIMARY KEY, ts INTEGER);
        CREATE TABLE IF NOT EXISTS index_history(grp TEXT, ts INTEGER, median REAL, n INTEGER, usd REAL);
        CREATE TABLE IF NOT EXISTS leads(phone TEXT PRIMARY KEY, name TEXT, address TEXT, region TEXT, source TEXT,
          first_seen INTEGER, day TEXT, status TEXT DEFAULT '', note TEXT DEFAULT '', updated INTEGER);
        CREATE INDEX IF NOT EXISTS ix_index ON index_history(grp, ts);
        CREATE TABLE IF NOT EXISTS status(source TEXT PRIMARY KEY, name TEXT, ts INTEGER, ok INTEGER,
          count INTEGER, error TEXT, ms INTEGER, last_ok INTEGER);
        """)
    return _db


def save_items(source, raw_items, run_ts, rolling=False):
    seen = set()
    prepared = []
    glob = source.startswith("g:")          # بازار جهانی: قیمت به سِنتِ دلار
    for r in raw_items:
        if not r["title"] or r["price"] < (100 if glob else 1000):
            continue
        if not glob and len(set(str(r["price"]))) == 1 and r["price"] > 99999:      # ۱۱۱۱۱۱۱۱۱۱ = قیمت ساختگی
            continue
        e = enrich(r["title"], r.get("hint", ""), None if glob else r["price"])
        if r.get("force"):                    # مدل‌های برند: دسته و گروه از قبل مشخص است
            e = dict(e, **r["force"])
            prepared.append((r, e, True))
            continue
        prepared.append((r, e, is_relevant(r["title"], r.get("hint", ""), e)))
    # اگر بیشترِ کالاهای یک سایت خورشیدی باشد، آن سایت «فروشگاه خورشیدی» است و بقیهٔ کالاهایش هم می‌ماند
    solar_store = bool(prepared) and sum(1 for p in prepared if p[2]) >= 0.6 * len(prepared)
    with _db_lock:
        c = db()
        for r, e, ok in prepared:
            if not ok and not (solar_store and not _EXCLUDE_RE.search(norm(r["title"]))):
                continue
            key = source + "|" + (r.get("uid") or r["url"])
            if key in seen:
                continue
            seen.add(key)
            row = c.execute("SELECT id, price FROM items WHERE key=?", (key,)).fetchone()
            common = (r["seller"], r["title"], r["url"], r["image"], e["category"], e["brand"],
                      json.dumps(e["specs"], ensure_ascii=False), e["qty"], e["unit"], e["group"],
                      r["price"], int(r["in_stock"]), run_ts)
            if row is None:
                cur = c.execute(
                    "INSERT INTO items(seller,title,url,image,category,brand,specs,qty,unit,grp,price,in_stock,"
                    "last_seen,key,source,first_seen,active) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                    common + (key, source, run_ts))
                c.execute("INSERT INTO history VALUES(?,?,?)", (cur.lastrowid, run_ts, r["price"]))
            else:
                c.execute("UPDATE items SET seller=?,title=?,url=?,image=?,category=?,brand=?,specs=?,qty=?,unit=?,"
                          "grp=?,price=?,in_stock=?,last_seen=?,active=1 WHERE id=?", common + (row["id"],))
                if row["price"] != r["price"]:
                    c.execute("UPDATE items SET prev_price=?, changed_at=? WHERE id=?",
                              (row["price"], run_ts, row["id"]))
                    c.execute("INSERT INTO history VALUES(?,?,?)", (row["id"], run_ts, r["price"]))
        if seen:      # منبعِ چرخشی (فروشندگان ترب) هر بار فقط بخشی را تازه می‌کند: ۳۶ ساعت مهلت
            c.execute("UPDATE items SET active=0 WHERE source=? AND last_seen<?",
                      (source, run_ts - 36 * 3600 if rolling else run_ts))
        c.commit()
    return len(seen)


def reclassify_all():
    """هنگام شروع: کالاهای ذخیره‌شدهٔ قبلی را با قواعد فعلی دوباره دسته‌بندی و نامربوط‌ها را حذف می‌کند."""
    with _db_lock:
        c = db()
        rows = c.execute("SELECT id, source, title, price FROM items WHERE active=1 AND grp NOT LIKE 'FOB|%'").fetchall()
        by_src = {}
        for r in rows:
            e = enrich(r["title"], "", None if r["source"].startswith("g:") else r["price"])
            by_src.setdefault(r["source"], []).append((r, e, is_relevant(r["title"], "", e)))
        for src, lst in by_src.items():
            solar_store = sum(1 for p in lst if p[2]) >= 0.6 * len(lst)
            for r, e, ok in lst:
                fake = not src.startswith("g:") and len(set(str(r["price"]))) == 1 and r["price"] > 99999
                if fake or (not ok and not (solar_store and not _EXCLUDE_RE.search(norm(r["title"])))):
                    c.execute("UPDATE items SET active=0 WHERE id=?", (r["id"],))
                else:
                    c.execute("UPDATE items SET category=?,brand=?,specs=?,qty=?,unit=?,grp=? WHERE id=?",
                              (e["category"], e["brand"], json.dumps(e["specs"], ensure_ascii=False),
                               e["qty"], e["unit"], e["group"], r["id"]))
        c.commit()


def set_status(source, name, ok, count, error, ms):
    now = int(time.time())
    with _db_lock:
        c = db()
        prev = c.execute("SELECT last_ok, count FROM status WHERE source=?", (source,)).fetchone()
        last_ok = now if ok else (prev["last_ok"] if prev else None)
        if not ok and prev:
            count = prev["count"]
        c.execute("INSERT OR REPLACE INTO status VALUES(?,?,?,?,?,?,?,?)",
                  (source, name, now, int(ok), count, error, ms, last_ok))
        c.commit()


# --------------------------------------------------------------------------
# امتیازدهی (مثل دلال: هر کالا فقط با کالاهای هم‌ردهٔ خودش مقایسه می‌شود)
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# نرخ دلار بازار آزاد (برای نمایش قیمت دلاری)
# --------------------------------------------------------------------------
def _usd_tgju():
    data = json.loads(http_get("https://call1.tgju.org/ajax.json", retries=0, timeout=12))
    p = ((data.get("current") or {}).get("price_dollar_rl") or {}).get("p")
    return int(re.sub(r"[^\d]", "", str(p))) / 10          # ریال به تومان


def _usd_nobitex():
    data = json.loads(http_get("https://api.nobitex.ir/market/stats?srcCurrency=usdt&dstCurrency=rls",
                               retries=0, timeout=12))
    return float(((data.get("stats") or {}).get("usdt-rls") or {}).get("latest")) / 10


def _usd_wallex():
    data = json.loads(http_get("https://api.wallex.ir/v1/markets", retries=0, timeout=12))
    return float(data["result"]["symbols"]["USDTTMN"]["stats"]["lastPrice"])


USD_SOURCES = [("دلار بازار آزاد (tgju)", _usd_tgju), ("تتر نوبیتکس", _usd_nobitex), ("تتر والکس", _usd_wallex)]


def update_usd(cfg):
    manual = num((cfg.get("usd") or {}).get("manual_toman")) or 0
    if manual > 0:
        STATE["usd"] = {"rate": manual, "source": "نرخ دستی", "ts": int(time.time())}
        return
    for name, fn in USD_SOURCES:
        try:
            rate = fn()
            if 10_000 <= rate <= 50_000_000:
                STATE["usd"] = {"rate": round(rate), "source": name, "ts": int(time.time())}
                log.info("USD  %s = %d toman", name, rate)
                return
            log.warning("USD  %s: out of range (%s)", name, rate)
        except Exception as e:
            log.warning("USD  %s failed: %s: %s", name, e.__class__.__name__, e)


def load_last_usd():
    with _db_lock:
        r = db().execute("SELECT ts, median FROM index_history WHERE grp='__usd__' ORDER BY ts DESC LIMIT 1").fetchone()
    if r and not STATE.get("usd"):
        STATE["usd"] = {"rate": r["median"], "source": "آخرین نرخ ذخیره‌شده", "ts": r["ts"]}


def group_stats(rows, glob=False):
    """میانهٔ قیمتِ واحد در هر گروه. glob=False: بازار ایران (تومان)؛ glob=True: سایت سازنده‌ها (دلار)."""
    groups, cat_of, unit_of, pieces = {}, {}, {}, {}
    for r in rows:
        if r["source"].startswith("g:") != glob:
            continue
        if r["grp"] and r["qty"] and r["in_stock"]:
            price = r["price"] / (100.0 if glob else 1)
            groups.setdefault(r["grp"], []).append(price / r["qty"])
            pieces.setdefault(r["grp"], []).append(price)
            cat_of[r["grp"]], unit_of[r["grp"]] = r["category"], r["unit"]
    return {g: {"n": len(v), "median": statistics.median(v), "unit": unit_of[g], "cat": cat_of[g],
                "min": min(v), "max": max(v), "pmed": statistics.median(pieces[g]), "pmin": min(pieces[g]),
                "pmax": max(pieces[g])} for g, v in groups.items()}


def record_indices():
    """بعد از هر بروزرسانی، قیمت بازارِ هر گروه و نرخ دلار را ثبت می‌کند (برای نمایش تغییر ۲۴ ساعته)."""
    now = int(time.time())
    usd = (STATE.get("usd") or {}).get("rate")
    with _db_lock:
        c = db()
        rows = c.execute("SELECT source, grp, qty, in_stock, price, category, unit FROM items WHERE active=1").fetchall()
        for g, st in group_stats(rows).items():
            if st["n"] >= MIN_GROUP:
                c.execute("INSERT INTO index_history VALUES(?,?,?,?,?)", (g, now, st["median"], st["n"], usd))
        for g, st in group_stats(rows, True).items():
            if st["n"] >= (1 if g.startswith("FOB|") else MIN_GROUP_GLOBAL):
                c.execute("INSERT INTO index_history VALUES(?,?,?,?,?)", ("G|" + g, now, st["median"], st["n"], usd))
        for x in (STATE.get("spot") or {}).get("items", []):
            c.execute("INSERT INTO index_history VALUES(?,?,?,?,?)", ("S|" + x["name"], now, x["usd"], 0, usd))
        if usd:
            c.execute("INSERT INTO index_history VALUES('__usd__',?,?,0,?)", (now, usd, usd))
        c.execute("DELETE FROM index_history WHERE ts<?", (now - 400 * 86400,))
        c.commit()


def index_changes():
    """برای هر گروه: مقدارِ حدود ۲۴ ساعت پیش (یا قدیمی‌ترین ثبت، اگر تاریخچه کوتاه‌تر است)."""
    now = int(time.time())
    out = {}
    with _db_lock:
        c = db()
        for r in c.execute("SELECT DISTINCT grp FROM index_history").fetchall():
            g = r["grp"]
            ref = c.execute("SELECT ts, median, usd FROM index_history WHERE grp=? AND ts<=? ORDER BY ts DESC LIMIT 1",
                            (g, now - 86400)).fetchone()
            if ref is None:
                ref = c.execute("SELECT ts, median, usd FROM index_history WHERE grp=? ORDER BY ts LIMIT 1",
                                (g,)).fetchone()
            if ref:
                out[g] = {"ts": ref["ts"], "median": ref["median"], "usd": ref["usd"]}
    return out


def build_payload():
    with _db_lock:
        rows = db().execute("SELECT * FROM items WHERE active=1").fetchall()
        status = [dict(r) for r in db().execute("SELECT * FROM status ORDER BY name").fetchall()]
    stats = group_stats(rows)
    gstats = group_stats(rows, True)
    refs = index_changes()
    usd = STATE.get("usd") or {}
    spot = STATE.get("spot")
    if spot:
        spot = dict(spot, items=[dict(x, ref=refs.get("S|" + x["name"])) for x in spot["items"]])
    items, cats = [], {}
    for r in rows:
        glob = r["source"].startswith("g:")
        price = r["price"] / 100.0 if glob else r["price"]
        unit_price = price / r["qty"] if r["qty"] else None
        score = diff = None
        flag = ""
        st = (gstats if glob else stats).get(r["grp"])
        if st and unit_price and st["n"] >= (MIN_GROUP_GLOBAL if glob else MIN_GROUP) and st["median"] > 0:
            diff = (st["median"] - unit_price) / st["median"]      # مثبت = ارزان‌تر از بازار
            score = int(max(0, min(100, round(50 + 200 * diff))))
            if r["in_stock"]:
                flag = "sus" if diff >= SUSPICIOUS else "opp" if diff >= OPPORTUNITY else ""
        items.append({
            "id": r["id"], "t": r["title"], "u": r["url"], "src": r["source"], "sel": r["seller"],
            "cat": r["category"], "br": r["brand"], "sp": json.loads(r["specs"] or "[]"),
            "p": price, "m": "g" if glob else "ir",
            "up": (round(unit_price, 3) if glob else round(unit_price)) if unit_price else None,
            "un": r["unit"].replace("تومان", "دلار") if glob else r["unit"], "g": r["grp"],
            "s": score, "d": round(diff, 4) if diff is not None else None, "f": flag,
            "st": r["in_stock"], "pp": (r["prev_price"] / 100.0 if glob and r["prev_price"] else r["prev_price"]),
            "ch": r["changed_at"], "fs": r["first_seen"],
        })
        if not glob:
            c = cats.setdefault(r["category"], {"n": 0, "opp": 0})
            c["n"] += 1
            c["opp"] += flag == "opp"
    return {
        "items": items,
        "groups": {g: {"n": s["n"], "median": round(s["median"]), "unit": s["unit"], "cat": s["cat"],
                       "min": round(s["min"]), "max": round(s["max"]), "ref": refs.get(g)}
                   for g, s in stats.items()},
        # قیمت جهانی هر گروه: میانهٔ قیمتِ دلاریِ سایتِ خودِ سازنده‌ها (بدون هیچ تبدیلی از تومان)
        "gg": {g: {"n": s["n"], "median": round(s["median"], 4), "unit": s["unit"].replace("تومان", "دلار"),
                   "cat": s["cat"], "min": round(s["min"], 4), "max": round(s["max"], 4), "ref": refs.get("G|" + g),
                   "pmed": round(s["pmed"], 2), "pmin": round(s["pmin"], 2), "pmax": round(s["pmax"], 2)}
               for g, s in gstats.items() if s["n"] >= (1 if g.startswith("FOB|") else MIN_GROUP_GLOBAL)},
        "fob": {"FOB|" + m["label"]: {"label": m["label"], "cat": m["cat"], "brand": m["brand"],
                                       "watts": m.get("watts"), "kw": m.get("kw")}
                for m in (load_config().get("fob") or {}).get("models", [])},
        "spot": spot, "min_group_global": MIN_GROUP_GLOBAL,
        "usd": dict(usd, ref=refs.get("__usd__")) if usd else None,
        "cats": cats, "cat_names": CATEGORIES, "sources": status,
        "running": STATE["running"], "last_run": STATE["last_run"], "next_run": STATE["next_run"],
        "now": int(time.time()), "interval": STATE["interval"], "min_group": MIN_GROUP,
        "sellers": len({r["seller"] for r in rows
                        if r["seller"] and r["source"] not in ("torob", "divar", "sheypoor", "emalls")
                        and not r["source"].startswith("g:")}),
    }


# --------------------------------------------------------------------------
# زمان‌بندی
# --------------------------------------------------------------------------
STATE = {"running": False, "last_run": None, "next_run": None, "interval": 30, "payload": None, "usd": None,
         "spot": None}
_wake = threading.Event()
_payload_lock = threading.Lock()


def refresh_payload():
    data = json.dumps(build_payload(), ensure_ascii=False).encode("utf-8")
    with _payload_lock:
        STATE["payload"] = data


def jobs_for(cfg):
    jobs = []
    if cfg["torob"].get("enabled"):
        jobs.append(("torob", "ترب", lambda: scrape_torob(cfg)))
    if cfg["emalls"].get("enabled"):
        jobs.append(("emalls", "ایمالز", lambda: scrape_emalls(cfg)))
    if cfg["divar"].get("enabled"):
        jobs.append(("divar", "دیوار", lambda: scrape_divar(cfg)))
    if cfg["digikala"].get("enabled"):
        jobs.append(("digikala", "دیجی‌کالا", lambda: scrape_digikala(cfg)))
    if cfg["sheypoor"].get("enabled"):
        jobs.append(("sheypoor", "شیپور", lambda: scrape_sheypoor(cfg)))
    for shop in cfg.get("shops", []):
        if shop.get("enabled", True):
            jobs.append((shop_id(shop), shop.get("name") or shop["url"], lambda s=shop: scrape_shop(s)))
    g = cfg.get("global") or {}
    if g.get("enabled", True):
        for store in g.get("stores", []):
            jobs.append((global_id(store), store.get("name") or store["url"], lambda s=store: scrape_shopify(s)))
    if (cfg.get("fob") or {}).get("enabled", True):
        jobs.append(("g:fob", "مدل‌های برند (Made-in-China)", lambda: scrape_fob(cfg)))
    return jobs


def run_job(job, run_ts):
    sid, name, fn = job
    t0 = time.time()
    try:
        raw = fn()
        n = save_items(sid, raw, run_ts, rolling=(sid == "torobshops"))
        set_status(sid, name, True, n, "", int((time.time() - t0) * 1000))
        log.info("OK   %-28s %4d items  %.1fs", sid, n, time.time() - t0)
    except Exception as e:
        set_status(sid, name, False, 0, explain(e), int((time.time() - t0) * 1000))
        log.warning("FAIL %-28s %s: %s", sid, e.__class__.__name__, e)
    refresh_payload()


def run_all():
    cfg = load_config()
    STATE["interval"] = cfg["interval_minutes"]
    STATE["running"] = True
    refresh_payload()
    run_ts = int(time.time())
    update_usd(cfg)
    update_spot(cfg)
    refresh_payload()
    jobs = jobs_for(cfg)
    wanted = {j[0] for j in jobs} | {"torobshops", "leads"}
    with _db_lock:   # منبع‌هایی که حذف شده‌اند دیگر نمایش داده نشوند
        for r in db().execute("SELECT source FROM status").fetchall():
            if r["source"] not in wanted:
                db().execute("DELETE FROM status WHERE source=?", (r["source"],))
                db().execute("UPDATE items SET active=0 WHERE source=?", (r["source"],))
        db().commit()
    log.info("run started: %d sources", len(jobs))
    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(lambda j: run_job(j, run_ts), jobs))
    if cfg["torob"].get("enabled") and cfg["torob"].get("sellers", True):
        run_job(("torobshops", "فروشندگان ترب", lambda: scrape_torob_sellers(cfg)), run_ts)
    STATE["running"] = False
    STATE["last_run"] = int(time.time())
    try:
        maybe_scrape_leads(cfg)
    except Exception:
        log.exception("leads failed")
    try:
        record_indices()
    except Exception:
        log.exception("record_indices failed")
    refresh_payload()
    log.info("run finished")


def scheduler(once=False):
    while True:
        try:
            run_all()
        except Exception:
            log.exception("run crashed")
            STATE["running"] = False
        if once:
            return
        wait = max(5, int(STATE["interval"])) * 60
        STATE["next_run"] = int(time.time()) + wait
        refresh_payload()
        _wake.wait(wait)
        _wake.clear()


# --------------------------------------------------------------------------
# سرور صفحهٔ زنده
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        gz = len(body) > 2000 and "gzip" in (self.headers.get("Accept-Encoding") or "")
        if gz:
            body = gzip.compress(body, 5)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path in ("/", "/index.html"):
            with open(DASHBOARD_PATH, "rb") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        fm = re.match(r"^/fonts/([A-Za-z0-9_.-]+\.(woff2?|ttf))$", path)
        if fm:
            fp = os.path.join(HERE, "fonts", fm.group(1))
            if os.path.isfile(fp):
                with open(fp, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "font/" + fm.group(2))
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                self.wfile.write(body)
                return
            return self.send(404, {"error": "not found"})
        if path == "/favicon.ico":
            return self.send(200, b"", "image/x-icon")
        if path == "/api/data":
            with _payload_lock:
                data = STATE["payload"]
            return self.send(200, data or b"{}")
        if path == "/api/leads":
            return self.send(200, leads_payload(urllib.parse.parse_qs(query).get("day", [""])[0]))
        if path == "/api/history":
            try:
                iid = int(urllib.parse.parse_qs(query).get("id", ["0"])[0])
            except ValueError:
                iid = 0
            with _db_lock:
                rows = db().execute("SELECT ts, price FROM history WHERE item_id=? ORDER BY ts", (iid,)).fetchall()
            return self.send(200, [[r["ts"], r["price"]] for r in rows])
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if self.headers.get("X-Radar") != "1":      # فقط از خودِ صفحه پذیرفته می‌شود
            return self.send(403, {"error": "forbidden"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except Exception:
            body = {}
        if self.path == "/api/leads/more":
            return self.send(200, leads_payload(more=True))
        if self.path == "/api/leads/status":
            if body.get("status") not in ("", "called", "noanswer", "interested", "rejected"):
                return self.send(400, {"error": "bad status"})
            with _db_lock:
                db().execute("UPDATE leads SET status=?, note=?, updated=? WHERE phone=?",
                             (body.get("status"), str(body.get("note") or "")[:300], int(time.time()), str(body.get("phone"))))
                db().commit()
            return self.send(200, {"ok": True})
        if self.path == "/api/refresh":
            if not STATE["running"]:
                _wake.set()
            return self.send(200, {"ok": True})
        if self.path == "/api/shops":
            url = str(body.get("url") or "").strip()
            if url and not re.match(r"https?://", url):
                url = "https://" + url
            parts = urllib.parse.urlsplit(url)
            if not parts.netloc or "." not in parts.netloc:
                return self.send(400, {"error": "نشانی سایت درست نیست"})
            base = "%s://%s" % (parts.scheme, parts.netloc)
            cfg = load_config()
            shop = next((s for s in cfg["shops"] if shop_id(s) == shop_id({"url": base})), None)
            if shop is None:
                shop = {"name": str(body.get("name") or parts.netloc.replace("www.", ""))[:60], "url": base}
                cfg["shops"].append(shop)
                cfg["removed"] = [r for r in cfg.get("removed") or [] if r != shop_id(shop)]
            if parts.path.strip("/"):
                shop.setdefault("pages", [])
                if url not in shop["pages"]:
                    shop["pages"].append(url)
            save_config(cfg)
            if not STATE["running"]:
                _wake.set()
            return self.send(200, {"ok": True})
        if self.path == "/api/shops/remove":
            cfg = load_config()
            cfg["shops"] = [s for s in cfg["shops"] if shop_id(s) != body.get("id")]
            if str(body.get("id", "")).startswith("shop:") and body["id"] not in cfg.setdefault("removed", []):
                cfg["removed"].append(body["id"])
            if body.get("id") == "g:fob":
                cfg["fob"]["enabled"] = False
            if str(body.get("id", "")).startswith("g:"):
                cfg["global"]["stores"] = [st for st in cfg["global"]["stores"] if global_id(st) != body["id"]]
            if body.get("id") == "torobshops":
                cfg["torob"]["sellers"] = False
            for k in ("torob", "emalls", "divar", "digikala", "sheypoor"):
                if body.get("id") == k:
                    cfg[k]["enabled"] = False
            save_config(cfg)
            with _db_lock:
                db().execute("UPDATE items SET active=0 WHERE source=?", (body.get("id"),))
                db().execute("DELETE FROM status WHERE source=?", (body.get("id"),))
                db().commit()
            refresh_payload()
            return self.send(200, {"ok": True})
        self.send(404, {"error": "not found"})


def main():
    once = "--once" in sys.argv
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")])
    cfg = load_config()
    STATE["interval"] = cfg["interval_minutes"]
    db()
    reclassify_all()
    load_last_usd()
    refresh_payload()
    if once:
        scheduler(once=True)
        return
    host, port = cfg.get("host", "127.0.0.1"), int(cfg.get("port", 8765))
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError:
        print("Port %d is busy - the radar is probably already running. Opening the page..." % port)
        webbrowser.open("http://127.0.0.1:%d/" % port)
        return
    threading.Thread(target=scheduler, daemon=True).start()
    url = "http://127.0.0.1:%d/" % port
    print("\n  Sanashid Solar Price Radar is running:  %s\n  Keep this window open. Press Ctrl+C to stop.\n" % url)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped.")


if __name__ == "__main__":
    main()
