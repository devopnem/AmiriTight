#!/usr/bin/env python3
"""
Amiri Tight Builder — OCR-friendly, Lightweight Arabic & Print-optimized variant of Amiri (SIL OFL)

Usage:
    python3 scripts/build_amiri_tight.py --src /path/to/amiri/fonts --out fonts
    python3 scripts/build_amiri_tight.py --src /path/to/amiri/fonts --out fonts --full  # keep all languages
"""

import argparse
import os
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import otTables
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.subset import Subsetter, Options

WEIGHTS = [
    ("Regular", "Regular", "Amiri Tight", "Amiri Tight Regular", "AmiriTight-Regular"),
    ("Bold", "Bold", "Amiri Tight", "Amiri Tight Bold", "AmiriTight-Bold"),
    ("Italic", "Italic", "Amiri Tight", "Amiri Tight Italic", "AmiriTight-Italic"),
    ("BoldItalic", "Bold Italic", "Amiri Tight", "Amiri Tight Bold Italic", "AmiriTight-BoldItalic"),
]

# Arabic-focused Unicode ranges (drops Urdu, Persian, Sindhi, Rohingya, Jawi, Arabic Math)
ARABIC_SUBSET_UNICODES = (
    list(range(0x0020, 0x0100)) +  # Basic Latin + Latin-1 Supplement (English, French, «», 0-9)
    list(range(0x2000, 0x2070)) +  # General Punctuation (ZWNJ, ZWJ, Word Joiner U+2060, dashes, quotes)
    list(range(0x0600, 0x0672)) +  # Core Arabic letters, tashkil, tatweel, Arabic digits, Alef Wasla, Dagger Alef
    [0x0674] +                     # High Hamza
    list(range(0x06D6, 0x06EE)) +  # Classical & Quranic annotation marks (waqf, ayah, rub el hizb, sajda)
    [0x08F0, 0x08F1, 0x08F2] +     # Open tanween (Quranic/Warsh)
    [0x25CC] +                     # Dotted circle
    [0xFD3E, 0xFD3F] +             # Ornate parentheses ﴿ ﴾
    [0xFDF2, 0xFDFA, 0xFDFB]       # Allah, Sallallahu Alayhi Wasallam ﷺ, Jalla Jalaluhu ﷻ
)

# Glyph-name patterns for vertical stacked ligatures that hide/stack letters and hurt OCR
# (Preserves Lam-Alef `لا`, Allah `لله`, Finjani Ayn, and normal cursive shaping)
STACK_PATTERNS = (
    "MemHaa", "LamMem", "BaaMem", "SenMem", "SadHaa", "BaaHaa",
    "AboveHaa", "MemMem", "HaaHaa", "AynHaa", "FaaHaa", "HehHaa",
    "SenHaa", "LamHaa", "KafLamMem",
    "LamHeh", "BaaHeh", "MemHeh", "KafHeh",
    "KafMem", "AynMem", "FaaMem", "HaaMem", "HehMem", "SadMem",
    "KafAlf", "KafLam", "KafKaf", "LamDal", "KafDal", "KafRaa", "KafBaa", "KafYaa",
    "LamYaa", "HaaYaa", "MemYaa", "AynYaa", "FaaYaa", "HehYaa",
)


def sample_glyph_points(glyph_set, glyph_name):
    rec = DecomposingRecordingPen(glyph_set)
    glyph_set[glyph_name].draw(rec)
    pts = []
    cur = None
    start = None
    for op, args in rec.value:
        if op == "moveTo":
            cur = args[0]
            start = cur
            pts.append(cur)
        elif op == "lineTo":
            p1 = args[0]
            if cur is not None:
                for t in (0.25, 0.5, 0.75, 1.0):
                    pts.append((cur[0] + t * (p1[0] - cur[0]), cur[1] + t * (p1[1] - cur[1])))
            else:
                pts.append(p1)
            cur = p1
        elif op == "qCurveTo":
            if cur is None:
                continue
            off_and_end = list(args)
            if off_and_end[-1] is None:
                off_pts = off_and_end[:-1]
                n = len(off_pts)
                for i in range(n):
                    p0 = ((off_pts[i - 1][0] + off_pts[i][0]) / 2, (off_pts[i - 1][1] + off_pts[i][1]) / 2)
                    p1 = off_pts[i]
                    p2 = ((off_pts[i][0] + off_pts[(i + 1) % n][0]) / 2, (off_pts[i][1] + off_pts[(i + 1) % n][1]) / 2)
                    for t in (0.25, 0.5, 0.75, 1.0):
                        mt = 1 - t
                        x = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0]
                        y = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]
                        pts.append((x, y))
                cur = p2
            else:
                p0 = cur
                for i in range(len(off_and_end) - 1):
                    p1 = off_and_end[i]
                    if i == len(off_and_end) - 2:
                        p2 = off_and_end[i + 1]
                    else:
                        nxt = off_and_end[i + 1]
                        p2 = ((p1[0] + nxt[0]) / 2, (p1[1] + nxt[1]) / 2)
                    for t in (0.25, 0.5, 0.75, 1.0):
                        mt = 1 - t
                        x = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0]
                        y = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]
                        pts.append((x, y))
                    p0 = p2
                cur = off_and_end[-1]
        elif op == "curveTo":
            if cur is None:
                continue
            p0 = cur
            p1, p2, p3 = args
            for t in (0.25, 0.5, 0.75, 1.0):
                mt = 1 - t
                x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
                y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
                pts.append((x, y))
            cur = p3
        elif op == "closePath":
            if cur is not None and start is not None:
                pts.append(((cur[0] + start[0]) / 2, (cur[1] + start[1]) / 2))
            cur = start
    return pts


def local_extents(pts, x_center, half_width=220):
    local = [y for (x, y) in pts if abs(x - x_center) <= half_width]
    if not local:
        local = [y for (_, y) in pts]
    if not local:
        return None, None
    return min(local), max(local)


def unstack_ocr_ligatures(font):
    """
    Directly remove SingleSubst (LookupType 1) target mappings that substitute
    standard horizontal glyphs into vertically stacked ligature variants
    (e.g. مخـ in مختصر, لمـ in المنطق, ـلم in علم, بحـ, صحـ, محمـ, بمـ, سمـ),
    guaranteeing complete unstacking regardless of Context/ChainContext format,
    while preserving Lam-Alef (`لا`) and Allah (`لله`).
    """
    gsub = font["GSUB"].table
    gset = set(font.getGlyphOrder())
    cleared = 0
    for lk in gsub.LookupList.Lookup:
        if lk.LookupType == 1:
            for st in lk.SubTable:
                for k in list(st.mapping.keys()):
                    v = st.mapping[k]
                    if "BaaYaa" in v:
                        if k.endswith(".init") and (k + ".Wide") in gset:
                            st.mapping[k] = k + ".Wide"
                        else:
                            del st.mapping[k]
                        cleared += 1
                    elif any(p in v for p in STACK_PATTERNS):
                        del st.mapping[k]
                        cleared += 1
    return cleared


def tighten_diacritics(font, above_margin=65, above_floor=500, below_margin=95, below_ceil=-125):
    glyph_set = font.getGlyphSet()
    gpos = font["GPOS"].table
    cmap = font.getBestCmap()

    fatha = cmap.get(0x064E)
    kasra = cmap.get(0x0650)

    pts_cache = {}
    def get_pts(gn):
        if gn not in pts_cache:
            pts_cache[gn] = sample_glyph_points(glyph_set, gn)
        return pts_cache[gn]

    above_changed = 0
    below_changed = 0

    for lk in gpos.LookupList.Lookup:
        if lk.LookupType != 4:
            continue
        for st in lk.SubTable:
            marks = set(st.MarkCoverage.glyphs)
            is_above = fatha in marks
            is_below = kasra in marks
            if not (is_above or is_below):
                continue
            for bi, bg in enumerate(st.BaseCoverage.glyphs):
                br = st.BaseArray.BaseRecord[bi]
                pts = get_pts(bg)
                if not pts:
                    continue
                for a in br.BaseAnchor:
                    if a is None:
                        continue
                    local_ymin, local_ymax = local_extents(pts, a.XCoordinate, half_width=220)
                    if is_above and local_ymax is not None:
                        target_y = max(int(round(local_ymax + above_margin)), above_floor)
                        if a.YCoordinate > target_y and a.YCoordinate >= 500:
                            a.YCoordinate = target_y
                            above_changed += 1
                    elif is_below and local_ymin is not None:
                        target_y = min(int(round(local_ymin - below_margin)), below_ceil)
                        if a.YCoordinate < target_y and a.YCoordinate <= -150:
                            a.YCoordinate = target_y
                            below_changed += 1
    # Center above-mark X over final Raa/Zain (original X=98 drifts left over the next letter)
    for lk in gpos.LookupList.Lookup:
        if lk.LookupType != 4:
            continue
        for st in lk.SubTable:
            if fatha not in set(st.MarkCoverage.glyphs):
                continue
            for bg_name in ("reh-ar.fina", "zain-ar.fina"):
                if bg_name in st.BaseCoverage.glyphs:
                    bi = st.BaseCoverage.glyphs.index(bg_name)
                    for a in st.BaseArray.BaseRecord[bi].BaseAnchor:
                        if a is not None and a.XCoordinate < 160:
                            a.XCoordinate += 85
    return above_changed, below_changed


def subset_arabic_only(font):
    """Strip non-Arabic scripts (Urdu/Persian/Sindhi/Rohingya/Math) while preserving all Arabic OpenType tables."""
    options = Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.name_languages = ["*"]
    options.hinting = True
    options.glyph_names = False
    options.notdef_glyph = True
    options.notdef_outline = True
    options.recommended_glyphs = True

    subsetter = Subsetter(options=options)
    subsetter.populate(unicodes=ARABIC_SUBSET_UNICODES)
    subsetter.subset(font)


def add_yeh_fina_below_mark_drop(font, y_drop=-155):
    """
    Contextually drop below-marks (kasra/kasratan) ONLY when immediately followed by
    final Yaa / Alef Maksura so the mark stays tight everywhere else (e.g. مِنَ)
    while never touching the rightward-sweeping belly of final Yaa (e.g. صَلِيَ، عَلِيٌّ).
    """
    gpos = font["GPOS"].table
    cmap = font.getBestCmap()
    kasra = cmap.get(0x0650)

    below_marks = set()
    for lk in gpos.LookupList.Lookup:
        if lk.LookupType == 4:
            for st in lk.SubTable:
                if kasra in st.MarkCoverage.glyphs:
                    below_marks.update(st.MarkCoverage.glyphs)
    for cp in (0x064D, 0x0650, 0x0656, 0x08F2):
        if cp in cmap:
            below_marks.add(cmap[cp])

    gorder = font.getGlyphOrder()
    gindex = {g: i for i, g in enumerate(gorder)}
    yeh_finas = sorted(
        [g for g in gorder if g.startswith(("yeh-ar.fina", "alefMaksura-ar.fina", "yehHamzaabove-ar.fina"))],
        key=lambda g: gindex[g],
    )
    below_marks_sorted = sorted([g for g in below_marks if g in gindex], key=lambda g: gindex[g])
    if not below_marks_sorted or not yeh_finas:
        return 0

    sp_st = otTables.SinglePos()
    sp_st.Format = 1
    sp_cov = otTables.Coverage()
    sp_cov.glyphs = below_marks_sorted
    sp_st.Coverage = sp_cov
    sp_st.ValueFormat = 0x0002  # YPlacement
    val = otTables.ValueRecord()
    val.YPlacement = y_drop
    sp_st.Value = val

    sp_lk = otTables.Lookup()
    sp_lk.LookupType = 1
    sp_lk.LookupFlag = 0
    sp_lk.SubTable = [sp_st]
    sp_lk.SubTableCount = 1

    sp_idx = len(gpos.LookupList.Lookup)
    gpos.LookupList.Lookup.append(sp_lk)

    all_marks = set(below_marks_sorted)
    for lk in gpos.LookupList.Lookup:
        if lk.LookupType == 4:
            for st in lk.SubTable:
                all_marks.update(st.MarkCoverage.glyphs)
    all_marks_sorted = sorted([g for g in all_marks if g in gindex], key=lambda g: gindex[g])

    def make_chain_st(lookahead_lists):
        st = otTables.ChainContextPos()
        st.Format = 3
        st.BacktrackGlyphCount = 0
        st.BacktrackCoverage = []
        in_cov = otTables.Coverage()
        in_cov.glyphs = below_marks_sorted
        st.InputGlyphCount = 1
        st.InputCoverage = [in_cov]
        st.LookAheadGlyphCount = len(lookahead_lists)
        st.LookAheadCoverage = []
        for la in lookahead_lists:
            c = otTables.Coverage()
            c.glyphs = la
            st.LookAheadCoverage.append(c)
        rec = otTables.PosLookupRecord()
        rec.SequenceIndex = 0
        rec.LookupListIndex = sp_idx
        st.PosCount = 1
        st.PosLookupRecord = [rec]
        return st

    cc_lk = otTables.Lookup()
    cc_lk.LookupType = 8
    cc_lk.LookupFlag = 0
    cc_lk.SubTable = [
        make_chain_st([yeh_finas]),
        make_chain_st([all_marks_sorted, yeh_finas]),
    ]
    cc_lk.SubTableCount = len(cc_lk.SubTable)

    cc_idx = len(gpos.LookupList.Lookup)
    gpos.LookupList.Lookup.append(cc_lk)
    gpos.LookupList.LookupCount = len(gpos.LookupList.Lookup)

    for fr in gpos.FeatureList.FeatureRecord:
        if fr.FeatureTag == "mark":
            fr.Feature.LookupListIndex.append(cc_idx)
            fr.Feature.LookupCount = len(fr.Feature.LookupListIndex)
    return len(below_marks_sorted)


def unify_line_metrics(font):
    """Ensure identical cross-platform line spacing (Linux/Windows/macOS) via USE_TYPO_METRICS."""
    os2 = font["OS/2"]
    hhea = font["hhea"]
    os2.fsSelection |= (1 << 7)  # USE_TYPO_METRICS
    os2.sTypoAscender = 1124
    os2.sTypoDescender = -634
    os2.sTypoLineGap = 0
    hhea.ascent = 1124
    hhea.descent = -634
    hhea.lineGap = 0
    os2.usWinAscent = 1480
    os2.usWinDescent = 780


def update_name_table(font, style_name, family_name, full_name, ps_name):
    name_table = font["name"]
    replacements = {1: family_name, 2: style_name, 4: full_name, 6: ps_name, 16: family_name, 17: style_name}
    for rec in name_table.names:
        if rec.nameID in replacements:
            rec.string = replacements[rec.nameID].encode(rec.getEncoding())
        elif rec.nameID == 3:
            s = rec.toUnicode().replace("Amiri-", "AmiriTight-").replace("Amiri", "Amiri Tight")
            rec.string = s.encode(rec.getEncoding())
        elif rec.nameID == 5:
            s = rec.toUnicode()
            if "Tight" not in s:
                s = s + " (Amiri Tight OCR)"
            rec.string = s.encode(rec.getEncoding())


def main():
    parser = argparse.ArgumentParser(description="Build Amiri Tight font family from Amiri TTF fonts.")
    parser.add_argument("--src", required=True, help="Directory containing Amiri-{Regular,Bold,Italic,BoldItalic}.ttf")
    parser.add_argument("--out", default="fonts", help="Output directory (creates ttf/ and woff2/ subfolders)")
    parser.add_argument("--full", action="store_true", help="Keep all non-Arabic languages (skip Arabic-only subsetting)")
    args = parser.parse_args()

    ttf_dir = os.path.join(args.out, "ttf")
    woff2_dir = os.path.join(args.out, "woff2")
    os.makedirs(ttf_dir, exist_ok=True)
    os.makedirs(woff2_dir, exist_ok=True)

    for weight_file, style_name, family_name, full_name, ps_name in WEIGHTS:
        src_path = os.path.join(args.src, f"Amiri-{weight_file}.ttf")
        if not os.path.exists(src_path):
            print(f"Skipping missing {src_path}")
            continue
        font = TTFont(src_path)
        orig_glyphs = len(font.getGlyphOrder())
        cleared = unstack_ocr_ligatures(font)
        above_n, below_n = tighten_diacritics(font)
        if not args.full:
            subset_arabic_only(font)
        add_yeh_fina_below_mark_drop(font, y_drop=-155)
        unify_line_metrics(font)
        update_name_table(font, style_name, family_name, full_name, ps_name)
        new_glyphs = len(font.getGlyphOrder())

        ttf_out = os.path.join(ttf_dir, f"{ps_name}.ttf")
        woff2_out = os.path.join(woff2_dir, f"{ps_name}.woff2")
        font.save(ttf_out)
        font.flavor = "woff2"
        font.save(woff2_out)
        ttf_kb = os.path.getsize(ttf_out) / 1024
        woff2_kb = os.path.getsize(woff2_out) / 1024
        print(
            f"{ps_name:24s} | glyphs: {orig_glyphs}->{new_glyphs} | cleared_stacks={cleared} "
            f"| TTF={ttf_kb:5.1f}KB | WOFF2={woff2_kb:5.1f}KB"
        )


if __name__ == "__main__":
    main()
