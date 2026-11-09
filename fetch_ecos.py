"""Fetch CPI (901Y009 item-level, 901Y010 special) and PPI (404Y014) from BOK ECOS.
Usage: python3 fetch_ecos.py [API_KEY] > data.json   (default key 'sample', 10 rows/call)"""
import sys, json, urllib.request, time
KEY = sys.argv[1] if len(sys.argv) > 1 else "sample"
PAGE = 10 if KEY == "sample" else 1000
BASE = "https://ecos.bok.or.kr/api/StatisticSearch/%s/json/kr/%d/%d/%s/M/%s/%s%s"

def get(stat, s, e, item="", start=1, end=None):
    url = BASE % (KEY, start, end or start + PAGE - 1, stat, s, e, ("/" + item) if item else "")
    for t in range(4):
        try:
            d = json.load(urllib.request.urlopen(url, timeout=30))
            break
        except Exception:
            time.sleep(2 ** t)
    else:
        raise RuntimeError(url)
    if "StatisticSearch" not in d:
        return 0, []
    return d["StatisticSearch"]["list_total_count"], d["StatisticSearch"]["row"]

def get_all(stat, ym, item=""):
    total, rows = get(stat, ym, ym, item)
    st = 1 + PAGE
    while st <= total:
        rows += get(stat, ym, ym, item, st)[1]
        st += PAGE
    return rows

def shift(ym, k):
    y, m = int(ym[:4]), int(ym[4:])
    m -= k
    while m <= 0:
        m += 12; y -= 1
    return "%04d%02d" % (y, m)

def latest(stat, item, back=6):
    import datetime
    now = datetime.date.today().strftime("%Y%m")
    for k in range(back):
        ym = shift(now, k)
        if get(stat, ym, ym, item)[1]:
            return ym
    return None

out = {}
cpi_m = latest("901Y009", "0")
ppi_m = latest("404Y014", "*AA")
out["cpi_month"], out["ppi_month"] = cpi_m, ppi_m
months = [cpi_m, shift(cpi_m, 1), shift(cpi_m, 12), shift(cpi_m, 13)]
out["cpi_special"] = {ym: get_all("901Y010", ym) for ym in months}
out["cpi_items"] = {ym: get_all("901Y009", ym) for ym in [cpi_m, shift(cpi_m, 12)]}
out["cpi_total"] = {ym: get("901Y009", ym, ym, "0")[1] for ym in months}
pm = [ppi_m, shift(ppi_m, 1), shift(ppi_m, 12), shift(ppi_m, 13)]
out["ppi_total"] = {ym: get("404Y014", ym, ym, "*AA")[1] for ym in pm}
json.dump(out, sys.stdout, ensure_ascii=False)
