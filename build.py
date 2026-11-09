"""Build the monthly 물가 브리핑 from ECOS data.
Usage: python3 build.py data.json sectors.json OUT_DIR
  data.json    : output of fetch_ecos.py
  sectors.json : {"품목명": "농축수산물"|"공업제품"|"서비스"|"전기·가스·수도"} for the selected items
                 (pass a path that does not exist on the first pass; build writes items.json so you can classify)
Writes OUT_DIR/summary.json, OUT_DIR/items.json, OUT_DIR/email.html
"""
import sys, json, os, datetime, html

data = json.load(open(sys.argv[1]))
sectors = json.load(open(sys.argv[2])) if os.path.exists(sys.argv[2]) else {}
OUT = sys.argv[3]
os.makedirs(OUT, exist_ok=True)

def shift(ym, k):
    y, m = int(ym[:4]), int(ym[4:]); m -= k
    while m <= 0: m += 12; y -= 1
    return "%04d%02d" % (y, m)

def val(rows, code):
    for r in rows or []:
        if r["ITEM_CODE1"] == code and r["DATA_VALUE"] not in (None, ""):
            return float(r["DATA_VALUE"])
    return None

def yoy(a, b):
    return None if a is None or b is None else round((a / b - 1) * 100 + 1e-9, 1)

def ymk(ym): return "%s년 %d월" % (ym[:4], int(ym[4:]))

M = data["cpi_month"]; P = shift(M, 1); M12 = shift(M, 12); P12 = shift(M, 13)
sp = data["cpi_special"]
def sp_yoy(code, cur, base): return yoy(val(sp.get(cur), code), val(sp.get(base), code))

cpi = sp_yoy("00", M, M12); cpi_prev = sp_yoy("00", P, P12)
core = sp_yoy("QB", M, M12); core2 = sp_yoy("DB", M, M12)
groups = [(c, n) for c, n in [("211", "농축수산물"), ("2111", "농산물"), ("2112", "축산물"), ("2113", "수산물"),
          ("212", "공업제품"), ("2121", "가공식품"), ("2125", "석유류"), ("213", "전기·가스·수도"),
          ("22", "서비스"), ("221", "집세"), ("222", "공공서비스"), ("223", "개인서비스"), ("2231", "외식")]]
group_rows = [{"code": c, "name": n, "yoy": sp_yoy(c, M, M12)} for c, n in groups]

# item level: rank by contribution-like score (index change x weight)
a = {r["ITEM_CODE1"]: r for r in data["cpi_items"][M]}
b = {r["ITEM_CODE1"]: r for r in data["cpi_items"][M12]}
items = []
for c, r in a.items():
    if len(c) >= 6 and c in b and r["DATA_VALUE"] and b[c]["DATA_VALUE"]:
        A, B, w = float(r["DATA_VALUE"]), float(b[c]["DATA_VALUE"]), float(r["WGT"] or 0)
        items.append({"code": c, "name": r["ITEM_NAME1"], "w": w, "yoy": yoy(A, B), "score": (A - B) * w})
items.sort(key=lambda x: x["score"])
up = [x for x in items[::-1] if x["yoy"] > 0][:12]
down = [x for x in items if x["yoy"] < 0][:8]
sel = up + down
json.dump([{"name": x["name"], "code": x["code"], "yoy": x["yoy"]} for x in sel],
          open(os.path.join(OUT, "items.json"), "w"), ensure_ascii=False, indent=1)
for x in sel:
    x["sector"] = sectors.get(x["name"], "기타")
top = max(up, key=lambda x: x["yoy"]) if up else None

# PPI
pt = data["ppi_total"]; PM = data["ppi_month"]
pv = lambda ym: float(pt[ym][0]["DATA_VALUE"]) if pt.get(ym) else None
ppi = yoy(pv(PM), pv(shift(PM, 12))); ppi_prev = yoy(pv(shift(PM, 1)), pv(shift(PM, 13)))

def fmt(x): return "확인 불가" if x is None else ("%.1f%%" % x)

# judgement
if cpi is None or core is None:
    verdict, reason = "확인 불가", "물가상승률이나 근원물가 값을 확인하지 못해 판단을 보류했어요."
elif cpi >= 2 and core >= 2:
    verdict = "📈 물가가 계속 오르는 흐름"
    reason = "전체 물가가 %s 올랐고, 날씨나 국제유가에 따라 크게 출렁이는 농산물·석유류를 빼고 봐도 %s 올랐어요. 일시적인 요인이 아니라 물가 전반이 꾸준히 오르고 있다는 뜻이에요." % (fmt(cpi), fmt(core))
elif cpi >= 2:
    verdict = "〰️ 잠깐 출렁인 것으로 보임"
    reason = "전체 물가는 %s 올랐지만 농산물·석유류를 뺀 근원물가는 %s로 2%%보다 낮아요. 일부 품목 가격이 튄 영향이 커 보여요." % (fmt(cpi), fmt(core))
else:
    verdict = "✅ 물가 안정권"
    reason = "전체 물가 상승률이 %s로 한국은행 물가안정목표인 2%%보다 낮아요." % fmt(cpi)

if cpi is not None and cpi_prev is not None:
    d = round(cpi - cpi_prev, 1)
    chg = "전월(%s, %s)보다 %s%.1f%%p" % (ymk(P), fmt(cpi_prev), "↑ " if d > 0 else ("↓ " if d < 0 else "변동 없음 "), abs(d)) if d else "전월(%s, %s)과 같아요" % (ymk(P), fmt(cpi_prev))
    if d: chg += (" 높아졌어요" if d > 0 else " 낮아졌어요")
else:
    chg = "전월 비교: 확인 불가"

if ppi is None:
    ppi_view, ppi_why = "확인 불가", "생산자물가 값을 확인하지 못했어요."
elif ppi > 0:
    ppi_view = "앞으로 1~3개월 사이 소비자물가에 상승 압력이 있을 것으로 예상"
    ppi_why = "기업이 물건을 만들 때 드는 값이 1년 전보다 %s 비싸져서, 이 부담이 시차를 두고 소비자 가격에 옮겨붙기 쉬워요." % fmt(ppi)
    if ppi_prev is not None and ppi < ppi_prev:
        ppi_why += " 다만 오름폭은 전월(%s)보다 줄었어요." % fmt(ppi_prev)
else:
    ppi_view = "소비자물가 하락 요인으로 작용할 것으로 예상"
    ppi_why = "기업의 생산 비용이 1년 전보다 내려가(%s) 소비자 가격을 올릴 압력이 약해져요." % fmt(ppi)

subject = "[물가 브리핑] %s 소비자물가 %s 상승" % (ymk(M), "확인 불가" if cpi is None else "%.1f%%" % cpi)
today = datetime.date.today().isoformat()
summary = dict(subject=subject, cpi_month=M, ppi_month=PM, cpi=cpi, cpi_prev=cpi_prev, core=core, core2=core2,
               verdict=verdict, reason=reason, change=chg, top=top, ppi=ppi, ppi_prev=ppi_prev,
               ppi_view=ppi_view, ppi_why=ppi_why, groups=group_rows, items=sel, generated=today)
json.dump(summary, open(os.path.join(OUT, "summary.json"), "w"), ensure_ascii=False, indent=1)

# ---------- email ----------
e = html.escape
RED, BLUE, INK, MUTED, LINE, BG = "#c62828", "#1565c0", "#1d2433", "#5f6b7a", "#e3e7ee", "#f4f6fa"
def color(x): return RED if x and x > 0 else (BLUE if x and x < 0 else INK)
def sign(x): return "확인 불가" if x is None else ("%+.1f%%" % x)

def big(label, value, sub):
    return ('<td class="stack" width="33%%" valign="top" style="padding:6px;">'
            '<div style="background:#ffffff;border:1px solid %s;border-radius:10px;padding:14px 12px;">'
            '<div style="font-size:12px;color:%s;">%s</div>'
            '<div style="font-size:30px;font-weight:800;color:%s;line-height:1.2;margin:4px 0;">%s</div>'
            '<div style="font-size:12px;color:%s;line-height:1.4;">%s</div></div></td>') % (LINE, MUTED, label, INK, value, MUTED, sub)

order = ["농축수산물", "공업제품", "전기·가스·수도", "서비스", "기타"]
rows = ""
for s in order:
    its = [x for x in sel if x["sector"] == s]
    if not its: continue
    rows += '<tr><td colspan="2" style="padding:10px 8px 4px;font-weight:700;font-size:13px;color:%s;border-bottom:1px solid %s;">%s</td></tr>' % (INK, LINE, s)
    for x in sorted(its, key=lambda x: -x["yoy"]):
        rows += '<tr><td style="padding:6px 8px;font-size:14px;border-bottom:1px solid %s;">%s</td><td align="right" style="padding:6px 8px;font-size:14px;font-weight:700;color:%s;border-bottom:1px solid %s;">%s</td></tr>' % (LINE, e(x["name"]), color(x["yoy"]), LINE, sign(x["yoy"]))
grows = "".join('<tr><td style="padding:5px 8px;font-size:13px;border-bottom:1px solid %s;%s">%s</td><td align="right" style="padding:5px 8px;font-size:13px;font-weight:700;color:%s;border-bottom:1px solid %s;">%s</td></tr>'
                % (LINE, "" if len(g["code"]) <= 3 else "padding-left:20px;color:%s;" % MUTED, g["name"], color(g["yoy"]), LINE, sign(g["yoy"])) for g in group_rows)

def section(title, body):
    return ('<tr><td style="padding:8px 16px;"><div style="background:#ffffff;border:1px solid %s;border-radius:10px;padding:16px;">'
            '<div style="font-size:16px;font-weight:800;color:%s;margin-bottom:8px;">%s</div>%s</div></td></tr>') % (LINE, INK, title, body)
P_ = lambda t: '<p style="margin:0 0 8px;font-size:14px;line-height:1.6;color:%s;">%s</p>' % (INK, t)
note = lambda t: '<p style="margin:8px 0 0;font-size:12px;line-height:1.5;color:%s;">%s</p>' % (MUTED, t)

body = ""
body += section("1. 소비자물가 상승률 <span style='font-weight:400;font-size:12px;color:%s'>(%s 기준)</span>" % (MUTED, ymk(M)),
    P_("우리가 사는 물건과 서비스 값이 1년 전보다 <b style='color:%s'>%s</b> 올랐어요." % (color(cpi), fmt(cpi))) + P_(chg + "."))
body += section("2. 근원물가 <span style='font-weight:400;font-size:12px;color:%s'>(%s 기준)</span>" % (MUTED, ymk(M)),
    P_("농산물 및 석유류 제외 지수: <b>%s</b> (전년동월대비)" % fmt(core)) + P_("참고, 식료품 및 에너지 제외 지수: <b>%s</b>" % fmt(core2))
    + note("근원물가는 날씨나 국제유가처럼 갑자기 출렁이는 품목을 빼고 본 물가예요. 물가의 기본 흐름을 보여줘요."))
body += section("3. 물가 흐름 판단", '<div style="font-size:18px;font-weight:800;margin-bottom:6px;">%s</div>' % verdict + P_(reason))
body += section("4. 가장 많이 오른 품목 <span style='font-weight:400;font-size:12px;color:%s'>(%s 기준)</span>" % (MUTED, ymk(M)),
    (P_("<b style='font-size:18px'>%s</b> <b style='color:%s;font-size:18px'>%s</b> (전년동월대비)" % (e(top["name"]), RED, sign(top["yoy"]))) if top else P_("확인 불가"))
    + note("아래 주요 등락품목 가운데 상승률이 가장 높은 품목이에요."))
body += section("5. 주요 등락품목 <span style='font-weight:400;font-size:12px;color:%s'>(%s, 전년동월대비)</span>" % (MUTED, ymk(M)),
    '<table width="100%%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">%s</table>' % rows
    + '<div style="font-size:13px;font-weight:700;margin:16px 0 4px;">부문별 물가</div><table width="100%%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">%s</table>' % grows
    + note("<span style='color:%s'>빨간색</span>은 상승, <span style='color:%s'>파란색</span>은 하락이에요. 품목은 보도자료 표를 옮긴 것이 아니라, 품목별 지수로 계산한 전년동월대비 등락률에 가중치를 곱한 영향이 큰 순서로 상승 12개, 하락 8개를 골랐어요. 품목의 부문 구분은 편집자 분류예요." % (RED, BLUE)))
body += section("6. 생산자물가 <span style='font-weight:400;font-size:12px;color:%s'>(%s 기준)</span>" % (MUTED, ymk(PM)),
    P_("생산자물가지수 전년동월대비: <b style='color:%s'>%s</b> (전월 %s: %s)" % (color(ppi), fmt(ppi), ymk(shift(PM, 1)), fmt(ppi_prev)))
    + P_("<b>%s</b>" % ppi_view) + P_(ppi_why)
    + note("생산자물가는 기업끼리 거래하는 물건값이에요. 보통 몇 달 뒤 소비자물가에 반영돼요."))
src = ("<b>소비자물가</b>: 국가데이터처 「%s 소비자물가동향」 공표 통계. 한국은행 경제통계시스템(ECOS) 통계표 901Y009(소비자물가지수), 901Y010(특수분류)에서 조회해 지수로 등락률을 계산했어요. "
       "보도자료 원문: <a href='https://mods.go.kr/board.es?mid=a10301040100&bid=a103010401' style='color:%s'>국가데이터처 보도자료 &gt; 물가/가계</a>. 발표일: 확인 불가 (ECOS 조회일 %s)<br><br>"
       "<b>생산자물가</b>: 한국은행 「%s 생산자물가지수」. ECOS 통계표 404Y014(생산자물가지수, 총지수)에서 조회해 계산했어요. "
       "보도자료 원문: <a href='https://www.bok.or.kr/portal/singl/newsData/list.do?menuNo=201150&searchCnd=1&searchKwd=%%EC%%83%%9D%%EC%%82%%B0%%EC%%9E%%90%%EB%%AC%%BC%%EA%%B0%%80' style='color:%s'>한국은행 보도자료</a>. 발표일: 확인 불가 (ECOS 조회일 %s)<br><br>"
       "해외 서버에서는 보도자료 게시판이 열리지 않아 공식 통계 API 값을 썼어요. 보도자료 수치와 소수점 반올림에서 0.1%%p 정도 차이가 날 수 있어요.") % (ymk(M), MUTED, today, ymk(PM), MUTED, today)
body += '<tr><td style="padding:12px 20px 24px;font-size:12px;line-height:1.6;color:%s;"><div style="font-weight:700;margin-bottom:4px;">출처</div>%s</td></tr>' % (MUTED, src)

email = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s</title><style>@media only screen and (max-width:520px){.stack{display:block!important;width:100%%!important;box-sizing:border-box;}}</style></head>
<body style="margin:0;padding:0;background:%s;font-family:-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;color:%s;">
<table width="100%%" cellpadding="0" cellspacing="0" style="background:%s;"><tr><td align="center">
<table width="100%%" cellpadding="0" cellspacing="0" style="max-width:600px;">
<tr><td style="padding:24px 20px 8px;"><div style="font-size:12px;color:%s;letter-spacing:1px;">월간 물가 브리핑 · %s 기준</div>
<div style="font-size:22px;font-weight:800;margin-top:4px;line-height:1.35;">%s 물가, 1년 전보다 %s 올랐어요</div></td></tr>
<tr><td style="padding:4px 10px;"><table width="100%%" cellpadding="0" cellspacing="0"><tr>%s%s%s</tr></table></td></tr>
%s</table></td></tr></table></body></html>""" % (
    e(subject), BG, INK, BG, MUTED, ymk(M), ymk(M), fmt(cpi),
    big("① 소비자물가 (전년동월비)", fmt(cpi), chg),
    big("② 근원물가 (농산물·석유류 제외)", fmt(core), "식료품·에너지 제외 %s" % fmt(core2)),
    big("③ 물가 흐름", verdict.split(" ")[0], " ".join(verdict.split(" ")[1:])), body)
open(os.path.join(OUT, "email.html"), "w").write(email)
print(subject)
