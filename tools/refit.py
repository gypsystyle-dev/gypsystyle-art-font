"""Перестройка однолинейных глифов по правилам векторного рисунка (17.10.2026).

Источник GS Line — автотрассировка: кривые из 20–30 коротких кусков с изломами.
Правила (OH no Type «drawing vectors», Scanner Licker «Bézier OCD»): минимум узлов,
узлы в экстремумах с горизонтальной или вертикальной ручкой, узлы в перегибах,
гладкий узел — ручки на одной прямой, прямые — прямые.

Вход: строка SVG-пути глифа (единицы источника, y вниз). Выход: список подпутей,
каждый — ('line'|'curve', ...) в тех же единицах: [(start, [(c1, c2, end) | (None, None, end)], closed)].
"""
import math, re

TOK = re.compile(r'([MLQ])|(-?\d+(?:\.\d+)?)')
CORNER_DEG = 40       # излом больше — настоящий угол
CLOSE_GAP = 2.5       # концы ближе — контур замкнут (у «о» шов 0,5, у «ф» разрыв у ножки 1,7, у «Ю» 2,2)
SNAP_CURVE = 1.2      # то же для кривых: середина В и B
SNAP = 0.6            # конец линии ближе к соседней линии — притягиваем (перекладина «в» торчала за ножку)
STRAIGHT_TOL = 0.30   # отклонение от хорды меньше — участок прямой
AXIS_DEG = 5          # прямая ближе к горизонтали или вертикали — выпрямляем по оси
FIT_TOL = 0.30        # допуск подгонки кривой, иначе дополнительный узел
STEP = 0.2            # шаг выборки, единицы источника (прописная 20)


def subpaths(d):
    subs, cur, cmd, nums = [], None, None, []
    for c, n in TOK.findall(d):
        if c:
            cmd, nums = c, []; continue
        nums.append(float(n))
        need = {'M': 2, 'L': 2, 'Q': 4}[cmd]
        if len(nums) < need: continue
        if cmd == 'M':
            cur = [(nums[0], nums[1])]; subs.append(cur); cmd = 'L'
        elif cmd == 'L':
            cur.append((nums[0], nums[1]))
        else:
            p0, c, p1 = cur[-1], (nums[0], nums[1]), (nums[2], nums[3])
            for t in (0.25, 0.5, 0.75, 1.0):
                u = 1 - t
                cur.append((u * u * p0[0] + 2 * u * t * c[0] + t * t * p1[0], u * u * p0[1] + 2 * u * t * c[1] + t * t * p1[1]))
        nums = []
    return subs


def _len(pts): return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _turn(a, b, c):
    v1, v2 = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
    n = math.hypot(*v1) * math.hypot(*v2)
    if n == 0: return 0
    return math.degrees(math.acos(max(-1, min(1, (v1[0] * v2[0] + v1[1] * v2[1]) / n))))


def _resample(pts, step):
    out, acc = [pts[0]], 0.0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]; L = math.dist(a, b)
        t = step - acc
        while t <= L:
            out.append((a[0] + (b[0] - a[0]) * t / L, a[1] + (b[1] - a[1]) * t / L)); t += step
        acc = (acc + L) % step if L else acc
    if math.dist(out[-1], pts[-1]) > 1e-6: out.append(pts[-1])
    return out


def _smooth(pts, passes, closed, pinned=()):
    p = list(pts); pin = set(pinned)
    for _ in range(passes):
        q = list(p); n = len(p)
        rng = range(n) if closed else range(1, n - 1)
        for i in rng:
            if i in pin: continue
            a, b = p[(i - 1) % n], p[(i + 1) % n]
            q[i] = (0.25 * a[0] + 0.5 * p[i][0] + 0.25 * b[0], 0.25 * a[1] + 0.5 * p[i][1] + 0.25 * b[1])
        p = q
    return p


def _rdp_corners(pts, closed):
    """Индексы настоящих углов по огрублённой ломаной."""
    n = len(pts); idx = []
    k = 4  # окно ±0,8 ед.
    for i in range(n):
        if not closed and (i < k or i > n - 1 - k): continue
        a, b, c = pts[(i - k) % n], pts[i], pts[(i + k) % n]
        if _turn(a, b, c) > CORNER_DEG: idx.append(i)
    # из группы соседних — самый острый
    out = []
    for i in idx:
        if out and i - out[-1] <= k:
            j = out[-1]
            if _turn(pts[(i - k) % n], pts[i], pts[(i + k) % n]) > _turn(pts[(j - k) % n], pts[j], pts[(j + k) % n]): out[-1] = i
        else: out.append(i)
    return out


def _bez(p0, c1, c2, p3, t):
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * p3[1])


def _fit(pts, t0, t1):
    """Кубическая с фиксированными концами и направлениями касательных (Schneider, Graphics Gems I)."""
    p0, p3 = pts[0], pts[-1]
    L = [0.0]
    for i in range(1, len(pts)): L.append(L[-1] + math.dist(pts[i - 1], pts[i]))
    u = [l / L[-1] for l in L] if L[-1] else [0] * len(pts)
    chord = math.dist(p0, p3)
    for _ in range(4):
        C = [[0, 0], [0, 0]]; X = [0, 0]
        for p, t in zip(pts, u):
            b0, b1, b2, b3 = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3
            A1, A2 = (t0[0] * b1, t0[1] * b1), (-t1[0] * b2, -t1[1] * b2)
            tmp = (p[0] - (p0[0] * (b0 + b1) + p3[0] * (b2 + b3)), p[1] - (p0[1] * (b0 + b1) + p3[1] * (b2 + b3)))
            C[0][0] += A1[0] * A1[0] + A1[1] * A1[1]; C[0][1] += A1[0] * A2[0] + A1[1] * A2[1]
            C[1][1] += A2[0] * A2[0] + A2[1] * A2[1]
            X[0] += A1[0] * tmp[0] + A1[1] * tmp[1]; X[1] += A2[0] * tmp[0] + A2[1] * tmp[1]
        C[1][0] = C[0][1]
        det = C[0][0] * C[1][1] - C[0][1] * C[1][0]
        if abs(det) > 1e-12:
            a1 = (X[0] * C[1][1] - X[1] * C[0][1]) / det; a2 = (C[0][0] * X[1] - C[1][0] * X[0]) / det
        else:
            a1 = a2 = chord / 3
        if a1 < chord * 0.05 or a2 < chord * 0.05 or a1 > chord * 1.5 or a2 > chord * 1.5:
            a1 = a2 = chord / 3
        c1 = (p0[0] + t0[0] * a1, p0[1] + t0[1] * a1); c2 = (p3[0] - t1[0] * a2, p3[1] - t1[1] * a2)
        # перепараметризация: ближайшая точка на кривой (Ньютон, 1 шаг)
        nu = []
        for p, t in zip(pts, u):
            q = _bez(p0, c1, c2, p3, t)
            h = 1e-4; qa = _bez(p0, c1, c2, p3, min(1, t + h)); qb = _bez(p0, c1, c2, p3, max(0, t - h))
            d1 = ((qa[0] - qb[0]) / (2 * h), (qa[1] - qb[1]) / (2 * h))
            den = d1[0] ** 2 + d1[1] ** 2
            nu.append(min(1, max(0, t - ((q[0] - p[0]) * d1[0] + (q[1] - p[1]) * d1[1]) / den)) if den else t)
        u = nu
    err, worst = 0, 0
    for i, (p, t) in enumerate(zip(pts, u)):
        e = math.dist(p, _bez(p0, c1, c2, p3, t))
        if e > err: err, worst = e, i
    return (c1, c2, p3), err, worst


def _unit(v):
    n = math.hypot(*v); return (v[0] / n, v[1] / n) if n else (1, 0)


def _tan(pts, i, back=3):
    n = len(pts)
    a, b = pts[max(0, i - back)], pts[min(n - 1, i + back)]
    return _unit((b[0] - a[0], b[1] - a[1]))


def _run(pts, kinds):
    """pts — гладкий участок без углов; kinds[i] — 'x'|'y'|'i' для внутренних узлов."""
    out = []
    breaks = [0] + sorted(kinds) + [len(pts) - 1]
    for a, b in zip(breaks, breaks[1:]):
        seg = pts[a:b + 1]
        def tangent(i, at_start):
            k = kinds.get(i)
            t = _tan(pts, i)
            if k == 'x': t = (0.0, 1.0 if t[1] >= 0 else -1.0)      # экстремум по x — касательная вертикальна
            elif k == 'y': t = (1.0 if t[0] >= 0 else -1.0, 0.0)    # экстремум по y — горизонтальна
            elif i == 0: t = _unit((pts[min(3, len(pts) - 1)][0] - pts[0][0], pts[min(3, len(pts) - 1)][1] - pts[0][1]))
            elif i == len(pts) - 1: t = _unit((pts[-1][0] - pts[max(0, len(pts) - 4)][0], pts[-1][1] - pts[max(0, len(pts) - 4)][1]))
            return t
        out += _fit_split(seg, tangent(a, True), tangent(b, False), 0)
    return out


def _fit_split(seg, t0, t1, depth):
    if len(seg) < 3 or math.dist(seg[0], seg[-1]) < 1e-6:
        return [(None, None, seg[-1])]
    dev = max((abs((seg[-1][0] - seg[0][0]) * (seg[0][1] - p[1]) - (seg[0][0] - p[0]) * (seg[-1][1] - seg[0][1])) / (math.dist(seg[0], seg[-1]) or 1)) for p in seg)
    if dev < STRAIGHT_TOL * 0.5:
        return [(None, None, seg[-1])]
    cubic, err, worst = _fit(seg, t0, t1)
    if err <= FIT_TOL or depth >= 2 or worst < 3 or worst > len(seg) - 4:
        return [cubic]
    tm = _tan(seg, worst)
    return _fit_split(seg[:worst + 1], t0, tm, depth + 1) + _fit_split(seg[worst:], tm, t1, depth + 1)


def _features(pts):
    """Экстремумы по x и y и перегибы внутри гладкого участка (индексы → вид)."""
    n = len(pts); kinds = {}
    if n < 7: return kinds
    tx = [pts[min(n - 1, i + 2)][0] - pts[max(0, i - 2)][0] for i in range(n)]
    ty = [pts[min(n - 1, i + 2)][1] - pts[max(0, i - 2)][1] for i in range(n)]
    def zero_cross(arr, kind, eps=0.04):
        # смена знака производной, в том числе через плоский участок — узел в середине плато
        sign, last = 0, None
        for i in range(n):
            sg = 1 if arr[i] > eps else (-1 if arr[i] < -eps else 0)
            if sg:
                if sign and sg != sign and last is not None:
                    j = (last + i) // 2
                    if 2 < j < n - 3: kinds[j] = kind
                sign, last = sg, i
    zero_cross(tx, 'x'); zero_cross(ty, 'y')
    # перегибы: смена знака кривизны с запасом
    cr = []
    for i in range(n):
        a, b, c = pts[max(0, i - 4)], pts[i], pts[min(n - 1, i + 4)]
        cr.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
    sign, last = 0, None
    for i in range(4, n - 4):
        s = 1 if cr[i] > 0.02 else (-1 if cr[i] < -0.02 else 0)
        if s and sign and s != sign and last is not None:
            j = (last + i) // 2
            if j not in kinds: kinds[j] = 'i'
        if s: sign, last = s, i
    # слишком близкие узлы — оставляем экстремум
    out, prev = {}, None
    for i in sorted(kinds):
        if prev is not None and _len(pts[prev:i + 1]) < 1.2:
            if kinds[i] != 'i' and out.get(prev) == 'i': out.pop(prev); out[i] = kinds[i]; prev = i
            continue
        out[i] = kinds[i]; prev = i
    return out


def _nearest_on(poly, p):
    best, bd = None, 1e9
    for i in range(len(poly) - 1):
        a, b = poly[i], poly[i + 1]; vx, vy = b[0] - a[0], b[1] - a[1]
        L2 = vx * vx + vy * vy
        t = 0 if L2 == 0 else max(0, min(1, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L2))
        q = (a[0] + vx * t, a[1] + vy * t); dd = math.dist(p, q)
        if dd < bd: best, bd = q, dd
    return best, bd


def _dehook(pts):
    for _ in range(2):
        if len(pts) > 4 and _len(pts[-3:]) < 1.0 and _turn(pts[-5], pts[-3], pts[-1]) > 60: pts = pts[:-2]
        if len(pts) > 4 and _len(pts[:3]) < 1.0 and _turn(pts[0], pts[2], pts[4]) > 60: pts = pts[2:]
    return pts


def _snap_ends(subs):
    """Концы открытых линий, почти касающиеся другой линии, ставим точно на неё."""
    for k, sp in enumerate(subs):
        if _len(sp) < 0.5 or math.dist(sp[0], sp[-1]) < CLOSE_GAP: continue
        for end in (0, -1):
            best, bd = None, SNAP
            for j, other in enumerate(subs):
                if j == k or _len(other) < 0.5: continue
                q, dd = _nearest_on(other, sp[end])
                if dd < bd: best, bd = q, dd
            if best is not None: sp[end] = best
    return subs


def refit(d):
    result = []
    for raw in _snap_ends([_dehook(sp) for sp in subpaths(d)]):
        pts = [raw[0]]
        for p in raw[1:]:
            if math.dist(p, pts[-1]) > 0.05: pts.append(p)
        L = _len(pts)
        if len(pts) < 2 or L < 0.5:      # точка (i, !, .) — как есть
            result.append((raw[0], [(None, None, raw[-1])], False)); continue
        closed = L > 12 and math.dist(pts[0], pts[-1]) < CLOSE_GAP
        if closed:
            pts = pts[:-1] if math.dist(pts[0], pts[-1]) < 0.3 else pts
        dense = _resample(pts + ([pts[0]] if closed else []), STEP)
        if closed: dense = dense[:-1]
        corners = _rdp_corners(dense, closed)
        dense = _smooth(dense, 3, closed, corners)      # углы не двигаем: иначе прямые уходят с места
        n = len(dense)
        if closed:
            if corners:
                start = corners[0]
            else:
                start = min(range(n), key=lambda i: dense[i][1])      # верхняя точка — без шва
            dense = dense[start:] + dense[:start] + [dense[start]]
            corners = sorted(((c - start) % n) for c in corners) + [n]
            if corners[0] != 0: corners = [0] + corners
        else:
            corners = [0] + corners + [n - 1]
        segs = []
        for a, b in zip(corners, corners[1:]):
            run = dense[a:b + 1]
            if len(run) < 2: continue
            chord = math.dist(run[0], run[-1])
            dev = max(abs((run[-1][0] - run[0][0]) * (run[0][1] - p[1]) - (run[0][0] - p[0]) * (run[-1][1] - run[0][1])) / chord for p in run) if chord > 1e-6 else 99
            if dev < STRAIGHT_TOL:
                segs.append((None, None, run[-1]))
            else:
                segs += _run(run, _features(run))
        start_pt = dense[0]
        result.append((start_pt, segs, closed))
    return _snap_ends_to_axes(_snap_axes(result))


def _snap_ends_to_axes(paths):
    """Конец открытой линии рядом с прямой по оси (ножка, перекладина) — ставим точно на неё:
    иначе круглый конец торчит из ножки бугорком (перекладины Б, В, в)."""
    lines = []
    for k, (start, segs, closed) in enumerate(paths):
        nodes = [start] + [sg[2] for sg in segs]
        for i, sg in enumerate(segs):
            if sg[0] is None:
                a, b = nodes[i], nodes[i + 1]
                if abs(a[0] - b[0]) < 1e-6: lines.append((k, i, 'v', a[0], min(a[1], b[1]), max(a[1], b[1])))
                elif abs(a[1] - b[1]) < 1e-6: lines.append((k, i, 'h', a[1], min(a[0], b[0]), max(a[0], b[0])))
    out = []
    for k, (start, segs, closed) in enumerate(paths):
        if closed or not segs:
            out.append((start, segs, closed)); continue
        segs = list(segs)
        def fix(pt, own_seg):
            for (kk, ii, kind, c, lo, hi) in lines:
                if kk == k and ii == own_seg: continue
                if kind == 'v' and lo - 0.3 <= pt[1] <= hi + 0.3 and 0 < abs(pt[0] - c) < SNAP: return (c, pt[1])
                if kind == 'h' and lo - 0.3 <= pt[0] <= hi + 0.3 and 0 < abs(pt[1] - c) < SNAP: return (pt[0], c)
            # иначе — на ближайшую кривую (середина В и B: чаша не доходила до перекладины)
            best, bd = pt, SNAP_CURVE
            for kk, (st2, sg2, _) in enumerate(paths):
                nodes2 = [st2] + [x[2] for x in sg2]
                for ii, sg in enumerate(sg2):
                    if kk == k and abs(ii - own_seg) <= 1: continue
                    a, b = nodes2[ii], nodes2[ii + 1]
                    for t in [j / 40 for j in range(41)]:
                        q = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t) if sg[0] is None else _bez(a, sg[0], sg[1], b, t)
                        dd = math.dist(pt, q)
                        if 0.02 < dd < bd: best, bd = q, dd
            return best
        new_start = fix(start, 0)
        if new_start != start and segs[0][0] is not None:
            c1 = segs[0][0]; segs[0] = ((c1[0] + new_start[0] - start[0], c1[1] + new_start[1] - start[1]), segs[0][1], segs[0][2])
        last = segs[-1]; new_end = fix(last[2], len(segs) - 1)
        if new_end != last[2]:
            c2 = last[1]
            segs[-1] = (last[0], None if c2 is None else (c2[0] + new_end[0] - last[2][0], c2[1] + new_end[1] - last[2][1]), new_end)
        out.append((new_start, segs, closed))
    return out


def _snap_axes(paths):
    """Почти горизонтальные и вертикальные прямые — строго по оси (двигаем общий узел)."""
    out = []
    for start, segs, closed in paths:
        nodes = [start] + [s[2] for s in segs]
        for i, s in enumerate(segs):
            if s[0] is not None: continue
            a, b = nodes[i], nodes[i + 1]
            ang = abs(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))) % 180
            if min(ang, 180 - ang) < AXIS_DEG:
                y = (a[1] + b[1]) / 2; nodes[i] = (a[0], y); nodes[i + 1] = (b[0], y)
            elif abs(ang - 90) < AXIS_DEG:
                x = (a[0] + b[0]) / 2; nodes[i] = (x, a[1]); nodes[i + 1] = (x, b[1])
        if closed: nodes[-1] = nodes[0]
        new = []
        for i, s in enumerate(segs):
            c1, c2 = s[0], s[1]
            if c1 is not None:   # сдвиг ручек вместе с узлами
                d0 = (nodes[i][0] - ([start] + [x[2] for x in segs])[i][0], nodes[i][1] - ([start] + [x[2] for x in segs])[i][1])
                d1 = (nodes[i + 1][0] - s[2][0], nodes[i + 1][1] - s[2][1])
                c1 = (c1[0] + d0[0], c1[1] + d0[1]); c2 = (c2[0] + d1[0], c2[1] + d1[1])
            new.append((c1, c2, nodes[i + 1]))
        out.append((nodes[0], new, closed))
    return out


def node_count(paths):
    return sum(len(segs) for _, segs, _ in paths)
