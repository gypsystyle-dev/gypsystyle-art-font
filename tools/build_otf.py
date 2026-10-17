"""gypsystyle.art — build the installable fonts from single-line centerlines.

Centerlines in sources/centerlines.json are expanded with a round pen
(skia-pathops), overlaps are merged, output is CFF OTF in five weights + WOFF2.
Run: python tools/build_otf.py  (needs fonttools, skia-pathops, brotli — see requirements.txt)
"""
import json, re, sys
from pathlib import Path
import pathops
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'sources/centerlines.json'
OUT = ROOT / 'fonts'
UPM, S = 1000, 35.0            # cap height 20 source units → 700
VERSION = '1.000'
WEIGHTS = [('Thin', 100, 25), ('Light', 300, 55), ('Medium', 500, 85), ('Bold', 700, 120), ('Black', 900, 160)]
FAMILY, PS = 'gypsystyle.art', 'GypsyStyleArt'
COPY = ('Copyright 2013 The Exo 2 Project Authors (https://github.com/googlefonts/Exo-2.0). '
        'Copyright 2026 Vsevolod Belikov (Gypsy Style), https://gypsystyle.art')
OFL_URL = 'https://openfontlicense.org'
TOK = re.compile(r'([MLQ])|(-?\d+(?:\.\d+)?)')


def src_path(d, dx):
    """SVG M/L/Q (y down) → pathops.Path in font units (y up), shifted by dx."""
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
    """Zero-length segments are not stroked by skia — draw a round dot by hand."""
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


def outline(d, dx, w):
    p = src_path(d, dx)
    p.stroke(w, pathops.LineCap.ROUND_CAP, pathops.LineJoin.ROUND_JOIN, 4)
    p.convertConicsToQuads()
    ops = [p, dots(d, dx, w)]
    res = pathops.Path()
    builder = pathops.OpBuilder(fix_winding=True, keep_starting_points=False)
    for q in ops: builder.add(q, pathops.PathOp.UNION)
    return builder.resolve()


def build(meta, glyphs, style, wclass, w):
    order, cmap, charstrings, metrics = ['.notdef'], {}, {}, {}
    # .notdef — hollow box
    pen = T2CharStringPen(500, None)
    for a, b, c, e in [(50, 0, 450, 700)]:
        pen.moveTo((a, b)); pen.lineTo((c, b)); pen.lineTo((c, e)); pen.lineTo((a, e)); pen.closePath()
        pen.moveTo((a + w, b + w)); pen.lineTo((a + w, e - w)); pen.lineTo((c - w, e - w)); pen.lineTo((c - w, b + w)); pen.closePath()
    charstrings['.notdef'] = pen.getCharString(); metrics['.notdef'] = (500, 50)
    ymax, ymin = 0, 0
    for ch, (left, right, d) in sorted(glyphs.items(), key=lambda kv: ord(kv[0])):
        name = 'space' if ch == ' ' else 'uni%04X' % ord(ch)
        adv = round((right - left) * S + w)
        rec = RecordingPen()
        if d:
            outline(d, -left * S + w / 2, w).draw(rec)
        bp = BoundsPen(None); rec.replay(bp)
        pen = T2CharStringPen(adv, None); rec.replay(pen)
        charstrings[name] = pen.getCharString()
        lsb = round(bp.bounds[0]) if bp.bounds else 0
        if bp.bounds: ymax, ymin = max(ymax, bp.bounds[3]), min(ymin, bp.bounds[1])
        metrics[name] = (adv, lsb); order.append(name); cmap[ord(ch)] = name
    if 0xA0 not in cmap:   # no-break space maps to space
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
    asc, desc = 800, 250
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
    (OUT / 'otf').mkdir(parents=True, exist_ok=True); (OUT / 'woff2').mkdir(parents=True, exist_ok=True)
    for style, wclass, w in WEIGHTS:
        f = build(data['meta'], data['glyphs'], style, wclass, w)
        otf = OUT / 'otf' / f'{PS}-{style}.otf'
        f.save(otf)
        f2 = TTFont(otf); f2.flavor = 'woff2'; f2.save(OUT / 'woff2' / f'{PS}-{style}.woff2')
        print(style, otf.stat().st_size, 'bytes,', len(f2.getGlyphOrder()), 'glyphs')


if __name__ == '__main__':
    main()
