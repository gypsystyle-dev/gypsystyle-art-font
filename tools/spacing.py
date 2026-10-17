"""Оптический спейсинг по площади белого (17.10.2026).

Метод Уолтера Трейси («Letters of Credit») в автоматическом виде, как HT Letterspacer
(Huerta Tipográfica): у каждой стороны знака в зоне строчных (0 … высота x) или прописных
(0 … высота прописной) меряется белое между краем знака и его профилем до глубины DEPTH;
отступ подбирается так, чтобы белое плюс отступ давали одну и ту же площадь. Ровная ножка
получает полный отступ, круглая сторона — меньше, диагональ — ещё меньше.
Площадь калибруется по «n» (строчные) и «H» (прописные, цифры) — общая плотность прежняя.
"""
from fontTools.pens.basePen import BasePen

DEPTH = 0.15      # глубина замера, доля высоты зоны (по умолчанию HT Letterspacer — 15 %)
STEP = 8          # шаг строк замера, ед.
MIN_SB = -15      # диагонали (v, w, A, V) не уходят в сильный минус


class _Flat(BasePen):
    def __init__(self):
        super().__init__(None); self.edges = []; self.cur = None; self.start = None
    def _moveTo(self, p): self.cur = self.start = p
    def _lineTo(self, p): self.edges.append((self.cur, p)); self.cur = p
    def _curveToOne(self, a, b, c):
        p0 = self.cur
        for i in range(1, 13):
            t = i / 12; u = 1 - t
            p = (u**3*p0[0]+3*u*u*t*a[0]+3*u*t*t*b[0]+t**3*c[0], u**3*p0[1]+3*u*u*t*a[1]+3*u*t*t*b[1]+t**3*c[1])
            self.edges.append((self.cur, p)); self.cur = p
    def _qCurveToOne(self, a, b):
        p0 = self.cur
        for i in range(1, 9):
            t = i / 8; u = 1 - t
            p = (u*u*p0[0]+2*u*t*a[0]+t*t*b[0], u*u*p0[1]+2*u*t*a[1]+t*t*b[1])
            self.edges.append((self.cur, p)); self.cur = p
    def _closePath(self):
        if self.cur != self.start: self.edges.append((self.cur, self.start))
    def _endPath(self): self._closePath()


def profile(rec, y0, y1):
    """Для каждой строки y в [y0, y1] — (левый край, правый край) чернил или None."""
    pen = _Flat(); rec.replay(pen)
    rows = []
    y = y0
    while y <= y1:
        xs = []
        for (a, b) in pen.edges:
            if (a[1] <= y < b[1]) or (b[1] <= y < a[1]):
                xs.append(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]))
        rows.append((min(xs), max(xs)) if xs else None)
        y += STEP
    return rows


def white(rows, side, depth):
    """Белое у стороны до глубины depth от крайней точки, и крайняя точка."""
    pts = [r for r in rows if r]
    if not pts: return 0, None
    if side == 'L':
        edge = min(r[0] for r in pts)
        area = sum(min(r[0] - edge, depth) if r else depth for r in rows)
    else:
        edge = max(r[1] for r in pts)
        area = sum(min(edge - r[1], depth) if r else depth for r in rows)
    return area * STEP, edge
