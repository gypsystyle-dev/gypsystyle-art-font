"""gypsystyle.art — устанавливаемый шрифт из однолинейного GS Line.

Линии из spike/fonts/gs-line/gs-line.json обводятся пером с круглыми концами
(skia-pathops), перекрытия сливаются, результат — OTF (CFF) пяти весов + WOFF2.
Запуск: <venv>/bin/python tools/font/build_otf.py  (нужны fonttools, skia-pathops, brotli)
"""
import json, re, sys
from pathlib import Path
import pathops
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'sources/centerlines.json'
OUT = ROOT / 'fonts'
UPM, SCALE = 1000, 0.92        # знаки на 8 % мельче: рядом с Outfit (сайт) шрифт выглядел крупнее
S = 35.0 * SCALE               # прописная 20 ед. источника → 644
TRACK = -12                    # трекинг чуть плотнее, ед. на знак (1.100, 17.10.2026)
CORNER_DEG = 35                # излом больше — угол, меньше — сглаживаем
VERSION = '1.500'
# толщина пера, ед. на 1000; потолок задаёт «е»: три штриха и два просвета на высоте строчных 462 (1.400)
WEIGHTS = [('Thin', 100, 25), ('Light', 300, 55), ('Medium', 500, 75), ('Bold', 700, 108), ('Black', 900, 138)]
FAMILY, PS = 'gypsystyle.art', 'GypsyStyleArt'
COPY = ('Copyright 2013 The Exo 2 Project Authors (https://github.com/googlefonts/Exo-2.0). '
        'Copyright 2026 Vsevolod Belikov (Gypsy Style), https://gypsystyle.art')
OFL_URL = 'https://openfontlicense.org'
TOK = re.compile(r'([MLQ])|(-?\d+(?:\.\d+)?)')


def src_path(d, dx):
    """SVG M/L/Q (y вниз) → pathops.Path в единицах шрифта (y вверх), сдвиг dx."""
    p, cmd, nums = pathops.Path(), None, []
    def pt(i): return (nums[i] * S + dx, -nums[i + 1] * S)
    def flush():
        if cmd == 'M': p.moveTo(*pt(0))
        elif cmd == 'L': p.lineTo(*pt(0))
        elif cmd == 'Q': p.quadTo(*pt(0), *pt(2))
    for c, n in TOK.findall(d):
        if c:
            cmd, nums = c, []
        else:
            nums.append(float(n))
            need = {'M': 2, 'L': 2, 'Q': 4}[cmd]
            if len(nums) == need:
                flush(); nums = []
                if cmd == 'M': cmd = 'L'
    return p


def dots(d, dx, w):
    """Отрезки нулевой длины (точки у i, !) skia не обводит — рисуем круг вручную."""
    out = pathops.Path()
    for m in re.finditer(r'M(-?[\d.]+),(-?[\d.]+) L(-?[\d.]+),(-?[\d.]+)', d):
        x1, y1, x2, y2 = map(float, m.groups())
        if abs(x1 - x2) + abs(y1 - y2) < 1e-6:
            cx, cy, r, k = (x1 + x2) / 2 * S + dx, -(y1 + y2) / 2 * S, w / 2, 0.5523 * w / 2
            out.moveTo(cx + r, cy)
            out.cubicTo(cx + r, cy + k, cx + k, cy + r, cx, cy + r)
            out.cubicTo(cx - k, cy + r, cx - r, cy + k, cx - r, cy)
            out.cubicTo(cx - r, cy - k, cx - k, cy - r, cx, cy - r)
            out.cubicTo(cx + k, cy - r, cx + r, cy - k, cx + r, cy)
            out.close()
    return out


def _subpaths(d):
    """Опорные точки подпутей: концы отрезков и середины квадратичных кривых (единицы источника)."""
    subs, cur, cmd, nums, last = [], None, None, [], None
    for c, n in TOK.findall(d):
        if c:
            cmd, nums = c, []
            continue
        nums.append(float(n))
        need = {'M': 2, 'L': 2, 'Q': 4}[cmd]
        if len(nums) < need:
            continue
        if cmd == 'M':
            cur = [(nums[0], nums[1])]; subs.append(cur); cmd = 'L'
        elif cmd == 'L':
            cur.append((nums[0], nums[1]))
        else:
            (x0, y0), (cx, cy), (x1, y1) = cur[-1], (nums[0], nums[1]), (nums[2], nums[3])
            cur.append((0.25 * x0 + 0.5 * cx + 0.25 * x1, 0.25 * y0 + 0.5 * cy + 0.25 * y1))
            cur.append((x1, y1))
        nums = []
    return subs


RDP_TOL = 0.12                 # допуск упрощения, единицы источника (прописная 20)


def _rdp(pts, tol):
    import math
    if len(pts) < 3: return list(pts)
    a, b = pts[0], pts[-1]
    L = math.dist(a, b) or 1e-9
    far, idx = 0, 0
    for i in range(1, len(pts) - 1):
        d = abs((b[0] - a[0]) * (a[1] - pts[i][1]) - (a[0] - pts[i][0]) * (b[1] - a[1])) / L
        if d > far: far, idx = d, i
    if far <= tol: return [a, b]
    return _rdp(pts[:idx + 1], tol)[:-1] + _rdp(pts[idx:], tol)


def _dehook(q, closed):
    """Крючки автотрассировки: короткий отрезок на конце открытой линии с резким поворотом."""
    import math
    if closed or len(q) < 4: return q
    def turn(a, b, c):
        v1, v2 = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
        cc = (v1[0] * v2[0] + v1[1] * v2[1]) / ((math.hypot(*v1) * math.hypot(*v2)) or 1)
        return math.degrees(math.acos(max(-1, min(1, cc))))
    if math.dist(q[-1], q[-2]) < 0.9 and turn(q[-3], q[-2], q[-1]) > 60: q = q[:-1]
    if math.dist(q[0], q[1]) < 0.9 and turn(q[2], q[1], q[0]) > 60: q = q[1:]
    return q


def smooth_path(d, dx):
    """Источник — ломаная из коротких кривых с изломами на стыках (автотрассировка).
    Сохраняем настоящие углы, остальное проводим заново сплайном Катмулла — Рома."""
    import math
    out = pathops.Path()
    for pts in _subpaths(d):
        q = [pts[0]]
        for pt in pts[1:]:
            if math.dist(pt, q[-1]) > 0.08: q.append(pt)
        length = sum(math.dist(q[i], q[i + 1]) for i in range(len(q) - 1))
        if len(q) < 3 or length < 0.5:          # прямая или точка — как в источнике
            out.moveTo(*(q[0][0] * S + dx, -q[0][1] * S))
            for pt in (q[1:] or [(pts[-1][0], pts[-1][1])]): out.lineTo(pt[0] * S + dx, -pt[1] * S)
            continue
        closed = math.dist(q[0], q[-1]) < 0.15
        if closed: q[-1] = q[0]
        q = _dehook(q, closed)
        n = len(q)
        def ang(i):
            a = q[i - 1] if i > 0 else (q[-2] if closed else None)
            b = q[i + 1] if i < n - 1 else (q[1] if closed else None)
            if a is None or b is None: return 180
            v1, v2 = (q[i][0] - a[0], q[i][1] - a[1]), (b[0] - q[i][0], b[1] - q[i][1])
            c = (v1[0] * v2[0] + v1[1] * v2[1]) / (math.hypot(*v1) * math.hypot(*v2) or 1)
            return math.degrees(math.acos(max(-1, min(1, c))))
        corner = [ang(i) > CORNER_DEG for i in range(n)]
        if closed: corner[-1] = corner[0]
        # упрощение дрожащих участков между углами (Рамер — Дуглас — Пекер), углы остаются
        keep, start = [], 0
        for i in range(1, n):
            if corner[i] or i == n - 1:
                keep += _rdp(q[start:i + 1], RDP_TOL)[:-1]; start = i
        keep.append(q[-1])
        cset = {q[i] for i in range(n) if corner[i]}
        q, n = keep, len(keep)
        corner = [pt in cset or i in (0, n - 1) and not closed for i, pt in enumerate(q)]
        if closed: corner[0] = corner[-1] = q[0] in cset
        # лёгкое выравнивание шума внутри гладких участков
        sm = list(q)
        for i in range(1, n - 1):
            if not corner[i] and not corner[i - 1] and not corner[i + 1]:
                sm[i] = (0.6 * q[i][0] + 0.2 * (q[i - 1][0] + q[i + 1][0]), 0.6 * q[i][1] + 0.2 * (q[i - 1][1] + q[i + 1][1]))
        q = sm
        def tan(i):
            if corner[i] or i == 0 or i == n - 1:
                return None
            return ((q[i + 1][0] - q[i - 1][0]) / 2, (q[i + 1][1] - q[i - 1][1]) / 2)
        F = lambda pt: (pt[0] * S + dx, -pt[1] * S)
        out.moveTo(*F(q[0]))
        for i in range(n - 1):
            a, b = q[i], q[i + 1]
            ta = tan(i) or (b[0] - a[0], b[1] - a[1])
            tb = tan(i + 1) or (b[0] - a[0], b[1] - a[1])
            c1 = (a[0] + ta[0] / 3, a[1] + ta[1] / 3)
            c2 = (b[0] - tb[0] / 3, b[1] - tb[1] / 3)
            out.cubicTo(*F(c1), *F(c2), *F(b))
        if closed: out.close()
    return out


_REFIT = {}


LINES = (0.0, -14.36, -20.54, -20.82, 6.18)   # базовая, строчные, прописные, выносные вверх и вниз (ед. источника)
LINE_TOL = 1.0
OVERSHOOT = 10                                # круглые формы выходят за линию на 10 ед., как положено


def _snap_lines(paths, ch):
    """Автотрассировка не попадала в линии (вершина A, низ L, З…): узлы рядом с линией — на линию,
    вместе с соседними ручками; круглые экстремумы — с нахлёстом OVERSHOOT наружу."""
    top_line = LINES[2] if (ch.isupper() or ch.isdigit()) else LINES[3]
    lines = [LINES[4], 0.0, top_line] + ([LINES[1]] if ch.islower() else [])
    ov = OVERSHOOT / S
    out = []
    for start, segs, closed in paths:
        nodes = [start] + [sg[2] for sg in segs]; n = len(nodes); dys = [0.0] * n
        for i, (x, y) in enumerate(nodes):
            line = next((L for L in lines if abs(y - L) < LINE_TOL), None)
            if line is None: continue
            nb = []
            if i > 0 or closed: nb.append(nodes[i - 1] if i > 0 else nodes[-2])
            if i < n - 1 or closed: nb.append(nodes[i + 1] if i < n - 1 else nodes[1])
            if any(q[1] < y - 0.3 for q in nb) and any(q[1] > y + 0.3 for q in nb): continue
            is_top = all(q[1] >= y - 0.3 for q in nb)
            prev_seg = segs[i - 1] if i > 0 else (segs[-1] if closed else None)
            next_seg = segs[i] if i < n - 1 else (segs[0] if closed else None)
            rnd = bool(prev_seg and prev_seg[0] is not None and next_seg and next_seg[0] is not None)
            rnd = rnd and all(abs(q[1] - y) > 1.0 for q in nb[:2])      # круг уходит от линии с обеих сторон, а не перекладина
            target = line + ((-ov if is_top else ov) if rnd else 0)
            dys[i] = target - y
        if closed: dys[0] = dys[-1] = dys[0] or dys[-1]
        nn = [(x, y + dy) for (x, y), dy in zip(nodes, dys)]
        ns = []
        for i, (c1, c2, _) in enumerate(segs):
            if c1 is not None:
                c1 = (c1[0], c1[1] + dys[i]); c2 = (c2[0], c2[1] + dys[i + 1])
                # узел на линии — почти горизонтальная ручка становится строго горизонтальной (перекладины F, Г)
                if dys[i] and abs(c1[1] - nn[i][1]) < 1.2: c1 = (c1[0], nn[i][1])
                if dys[i + 1] and abs(c2[1] - nn[i + 1][1]) < 1.2: c2 = (c2[0], nn[i + 1][1])
            ns.append((c1, c2, nn[i + 1]))
        out.append((nn[0], ns, closed))
    return out


def _vmap(paths, w, ch):
    """Круглое перо выходит за осевую линию на w/2. Чтобы внешний край ложился ровно на линии
    (базовая, строчные, прописные, выносные), осевая сжимается по вертикали кусочно-линейно:
    нижние линии сдвигаются вверх на w/2, верхние — вниз на w/2, между ними — линейно; выше верхней
    и ниже нижней — сдвиг без сжатия (диакритика, хвосты)."""
    h = w / 2 / S
    base, xh, cap, asc, desc = 0.0, LINES[1], LINES[2], LINES[3], LINES[4]
    top = cap if (ch.isupper() or ch.isdigit()) else asc
    # опорные пары (было → стало), y источника растёт вниз
    if ch.islower():
        pairs = [(desc, desc - h), (base, base - h), (xh, xh + h), (top, top + h)]
    else:
        pairs = [(desc, desc - h), (base, base - h), (top, top + h)]
    pairs.sort()
    def m(y):
        if y <= pairs[0][0]: return y + (pairs[0][1] - pairs[0][0])
        if y >= pairs[-1][0]: return y + (pairs[-1][1] - pairs[-1][0])
        for (a0, b0), (a1, b1) in zip(pairs, pairs[1:]):
            if a0 <= y <= a1:
                t = (y - a0) / (a1 - a0) if a1 != a0 else 0
                return b0 + (b1 - b0) * t
        return y
    P = lambda pt: None if pt is None else (pt[0], m(pt[1]))
    zone_top = xh if ch.islower() else top
    out = []
    for st, sg, cl in _snap_lines(paths, ch):
        ys = [st[1]] + [q[1] for c1, c2, e in sg for q in (c1, c2, e) if q is not None]
        if max(ys) < zone_top - 0.3:
            # диакритика и точки целиком над буквой: вверх на w/2, чтобы зазор до буквы был одинаковым во всех весах
            U = lambda pt: None if pt is None else (pt[0], pt[1] - h)
            out.append((U(st), [(U(c1), U(c2), U(e)) for c1, c2, e in sg], cl))
        else:
            out.append((P(st), [(P(c1), P(c2), P(e)) for c1, c2, e in sg], cl))
    return out


def refit_path(d, dx, w, ch=''):
    """Линии по правилам векторного рисунка: минимум узлов, экстремумы, перегибы (refit.py).
    Перестройка не зависит от веса — считается один раз на знак; выравнивание по линиям — для веса.
    Возвращает каждую линию отдельным путём (обводятся по одной) и центры точек."""
    import refit
    if d not in _REFIT: _REFIT[d] = refit.refit(d)
    F = lambda pt: (pt[0] * S + dx, -pt[1] * S)
    subs, dots = [], []
    for start, segs, closed in _vmap(_REFIT[d], w, ch):
        if len(segs) == 1 and segs[0][0] is None and abs(start[0] - segs[0][2][0]) + abs(start[1] - segs[0][2][1]) < 0.5:
            dots.append(((start[0] + segs[0][2][0]) / 2, (start[1] + segs[0][2][1]) / 2)); continue
        out = pathops.Path()
        out.moveTo(*F(start))
        for c1, c2, end in segs:
            if c1 is None: out.lineTo(*F(end))
            else: out.cubicTo(*F(c1), *F(c2), *F(end))
        if closed: out.close()
        subs.append(out)
    return subs, dots


DOT_MIN = 60          # точки не тоньше 60 ед. и чуть крупнее пера: иначе в Thin они пропадают


def _circle(cx, cy, r):
    k = 0.5523 * r; c = pathops.Path()
    c.moveTo(cx + r, cy); c.cubicTo(cx + r, cy + k, cx + k, cy + r, cx, cy + r)
    c.cubicTo(cx - k, cy + r, cx - r, cy + k, cx - r, cy); c.cubicTo(cx - r, cy - k, cx - k, cy - r, cx, cy - r)
    c.cubicTo(cx + k, cy - r, cx + r, cy - k, cx + r, cy); c.close()
    return c


def outline(d, dx, w, ch=''):
    subs, dots = refit_path(d, dx, w, ch)
    ops = []
    for p in subs:                     # каждая линия обводится отдельно: самопересечение петли («&») не заливается
        p.stroke(w, pathops.LineCap.ROUND_CAP, pathops.LineJoin.ROUND_JOIN, 4)
        p.convertConicsToQuads()
        p.fillType = pathops.FillType.WINDING
        ops.append(pathops.simplify(p, fix_winding=True))
    r = max(w * 1.15, DOT_MIN) / 2
    for (x, y) in dots:
        cy = r if abs(y) < 3 else -y * S          # точка у базовой — низом на линию
        ops.append(_circle(x * S + dx, cy, r))
    res = pathops.Path()
    if not ops: return pathops.Path()
    builder = pathops.OpBuilder(fix_winding=True, keep_starting_points=False)
    for q in ops: builder.add(q, pathops.PathOp.UNION)
    return builder.resolve()


def _zone(ch):
    return (0, round(_META['xHeight'] * S)) if ch.islower() else (0, round(_META['capHeight'] * S))


def _sides(ch, rec):
    import spacing
    y0, y1 = _zone(ch)
    rows = spacing.profile(rec, y0, y1)
    depth = spacing.DEPTH * (y1 - y0)
    aL, eL = spacing.white(rows, 'L', depth)
    aR, eR = spacing.white(rows, 'R', depth)
    return aL, eL, aR, eR, (y1 - y0)


def respace(ch, rec, w):
    """Отступы по площади белого; площадь откалибрована по «n» / «H» этого веса (spacing.py)."""
    import spacing
    from fontTools.pens.transformPen import TransformPen
    aL, eL, aR, eR, H = _sides(ch, rec)
    if eL is None:     # нет чернил в зоне — оставляем прежнюю ширину
        bp = BoundsPen(None); rec.replay(bp)
        return rec, round((bp.bounds[2] if bp.bounds else 0) + w / 2)
    target = _AREA['lc' if ch.islower() else 'uc']
    lsb = max(spacing.MIN_SB, (target - aL) / H)
    rsb = max(spacing.MIN_SB, (target - aR) / H)
    out = RecordingPen()
    rec.replay(TransformPen(out, (1, 0, 0, 1, lsb - eL, 0)))
    return out, round(lsb + (eR - eL) + rsb)


_META, _AREA = {}, {}


def calibrate(glyphs, w):
    """Площадь = белое + отступ × высота у «n» и «H», отступы которых берём из прежней сборки."""
    for key, ch in (('lc', 'n'), ('uc', 'H')):
        left, right, d = glyphs[ch]
        rec = RecordingPen(); outline(d, -left * S + (w + TRACK) / 2, w, ch).draw(rec)
        bp = BoundsPen(None); rec.replay(bp)
        adv = (right - left) * S + w + TRACK
        sb = (bp.bounds[0] + (adv - bp.bounds[2])) / 2           # средний прежний отступ
        aL, eL, aR, eR, H = _sides(ch, rec)
        _AREA[key] = (aL + aR) / 2 + sb * H


def build(meta, glyphs, style, wclass, w):
    _META.update(meta); calibrate(glyphs, w)
    order, cmap, charstrings, metrics = ['.notdef'], {}, {}, {}
    # .notdef — пустой прямоугольник
    pen = T2CharStringPen(500, None)
    for a, b, c, e in [(50, 0, 450, 700)]:
        pen.moveTo((a, b)); pen.lineTo((c, b)); pen.lineTo((c, e)); pen.lineTo((a, e)); pen.closePath()
        pen.moveTo((a + w, b + w)); pen.lineTo((a + w, e - w)); pen.lineTo((c - w, e - w)); pen.lineTo((c - w, b + w)); pen.closePath()
    charstrings['.notdef'] = pen.getCharString(); metrics['.notdef'] = (500, 50)
    ymax, ymin = 0, 0
    for ch, (left, right, d) in sorted(glyphs.items(), key=lambda kv: ord(kv[0])):
        name = 'space' if ch == ' ' else 'uni%04X' % ord(ch)
        adv = round((right - left) * S + w + TRACK)
        if ch == ' ': adv = round(0.26 * UPM + w / 2)     # пробел ≈ четверть кегля (был 0,4)
        rec = RecordingPen()
        if d:
            outline(d, -left * S + (w + TRACK) / 2, w, ch).draw(rec)
        if ch.isalnum() and d:
            rec, adv = respace(ch, rec, w)
        bp = BoundsPen(None); rec.replay(bp)
        pen = T2CharStringPen(adv, None); rec.replay(pen)
        charstrings[name] = pen.getCharString()
        lsb = round(bp.bounds[0]) if bp.bounds else 0
        if bp.bounds: ymax, ymin = max(ymax, bp.bounds[3]), min(ymin, bp.bounds[1])
        metrics[name] = (adv, lsb); order.append(name); cmap[ord(ch)] = name
    if 0xA0 not in cmap:   # неразрывный пробел — как пробел (подписи Keepers с NBSP)
        cmap[0xA0] = 'space'
    fb = FontBuilder(UPM, isTTF=False)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    ribbi = style == 'Bold'
    psname = f'{PS}-{style}'
    names = dict(
        familyName=FAMILY if ribbi else f'{FAMILY} {style}', styleName='Bold' if ribbi else 'Regular',
        uniqueFontIdentifier=f'{VERSION};GYPS;{psname}', fullName=f'{FAMILY} {style}', psName=psname,
        version=f'Version {VERSION}', copyright=COPY, manufacturer='Gypsy Style', designer='Vsevolod Belikov',
        description='Monoline typeface from the Keepers photobook app: Latin, Spanish, Cyrillic (Russian). '
                    'Single-line centerlines derived from Exo 2 Extra Light, expanded with a round pen.',
        vendorURL='https://gypsystyle.art', designerURL='https://gypsystyle.art',
        licenseDescription='This Font Software is licensed under the SIL Open Font License, Version 1.1. '
                           'This license is available with a FAQ at: https://openfontlicense.org',
        licenseInfoURL=OFL_URL, typographicFamily=FAMILY, typographicSubfamily=style)
    fb.setupNameTable(names)
    fb.setupCFF(psname, {'FullName': f'{FAMILY} {style}', 'FamilyName': FAMILY, 'Weight': style,
                         'Copyright': COPY, 'version': VERSION}, charstrings, {})
    fb.setupHorizontalMetrics(metrics)
    # середина прописных = середина строки (asc − desc = прописная 644); высота строки как у Outfit (1260)
    asc, desc = 952, 308
    fb.setupHorizontalHeader(ascent=asc, descent=-desc, lineGap=0)
    fb.setupOS2(version=4, sTypoAscender=asc, sTypoDescender=-desc, sTypoLineGap=0,
                usWinAscent=max(asc, round(ymax) + 10), usWinDescent=max(desc, round(-ymin) + 10),
                usWeightClass=wclass, achVendID='GYPS', sxHeight=round(meta['xHeight'] * S),
                sCapHeight=round(meta['capHeight'] * S), fsType=0,
                fsSelection=(0x20 if ribbi else 0) | 0x80)
    fb.setupPost()
    fb.font['head'].macStyle = 1 if ribbi else 0
    fb.font['head'].fontRevision = float(VERSION)
    return fb.font


def main():
    data = json.loads(SRC.read_text())
    import extra_glyphs
    data['glyphs'].update(extra_glyphs.extras(data['glyphs']))   # € × стрелки ° © № — только в шрифте, Keepers не трогаем
    (OUT / 'otf').mkdir(parents=True, exist_ok=True); (OUT / 'woff2').mkdir(parents=True, exist_ok=True)
    for style, wclass, w in WEIGHTS:
        f = build(data['meta'], data['glyphs'], style, wclass, w)
        otf = OUT / 'otf' / f'{PS}-{style}.otf'
        f.save(otf)
        f2 = TTFont(otf); f2.flavor = 'woff2'; f2.save(OUT / 'woff2' / f'{PS}-{style}.woff2')
        print(style, otf.stat().st_size, 'bytes,', len(f2.getGlyphOrder()), 'glyphs')


if __name__ == '__main__':
    main()
