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


def get_positional_forms(font):
    cmap = font.getBestCmap()
    gsub = font["GSUB"].table
    forms = {"init": {}, "medi": {}, "fina": {}}
    for fr in gsub.FeatureList.FeatureRecord:
        if fr.FeatureTag in forms:
            for li in fr.Feature.LookupListIndex:
                lk = gsub.LookupList.Lookup[li]
                for st in lk.SubTable:
                    if hasattr(st, "mapping"):
                        for k, v in st.mapping.items():
                            forms[fr.FeatureTag][k] = v[0] if isinstance(v, list) else v

    def get_g(cp, pos=None):
        base = cmap.get(cp)
        if not base:
            return None
        return forms[pos].get(base) if pos else base

    return {
        "lam_init": get_g(0x0644, "init"),
        "lam_medi": get_g(0x0644, "medi"),
        "meem_init": get_g(0x0645, "init"),
        "meem_medi": get_g(0x0645, "medi"),
        "meem_fina": get_g(0x0645, "fina"),
        "haa_medi": get_g(0x062D, "medi"),
        "haa_fina": get_g(0x062D, "fina"),
        "khaa_medi": get_g(0x062E, "medi"),
        "jeem_medi": get_g(0x062C, "medi"),
        "baa_init": get_g(0x0628, "init"),
        "baa_medi": get_g(0x0628, "medi"),
        "seen_init": get_g(0x0633, "init"),
        "sad_init": get_g(0x0635, "init"),
        "alef_fina": get_g(0x0627, "fina"),
        "heh_fina": get_g(0x0647, "fina"),
    }


def unstack_ocr_ligatures(font):
    gsub = font["GSUB"].table
    g = get_positional_forms(font)

    meem_targets = {x for x in (g["meem_medi"], g["meem_fina"]) if x}
    haa_targets = {x for x in (g["haa_medi"], g["haa_fina"], g["khaa_medi"], g["jeem_medi"]) if x}
    stack_prefixes = {x for x in (g["lam_init"], g["lam_medi"], g["baa_init"], g["baa_medi"], g["seen_init"], g["sad_init"], g["meem_init"]) if x}
    protected = {x for x in (g["alef_fina"], g["heh_fina"]) if x}

    rlig_indices = set()
    for fr in gsub.FeatureList.FeatureRecord:
        if fr.FeatureTag == "rlig":
            rlig_indices.update(fr.Feature.LookupListIndex)

    removed_subtables = 0
    for li in sorted(rlig_indices):
        lk = gsub.LookupList.Lookup[li]
        if lk.LookupType != 6:
            continue
        kept = []
        for st in lk.SubTable:
            if st.Format != 3:
                kept.append(st)
                continue
            in_covs = [set(c.glyphs) for c in st.InputCoverage]
            all_in = set().union(*in_covs) if in_covs else set()
            if all_in & protected:
                kept.append(st)
                continue
            has_prefix = len(in_covs) >= 2 and bool(in_covs[0] & stack_prefixes)
            has_meem = any(bool(cov & meem_targets) for cov in in_covs[1:])
            has_haa = any(bool(cov & haa_targets) for cov in in_covs[1:])
            if has_prefix and (has_meem or has_haa):
                removed_subtables += 1
            else:
                kept.append(st)
        lk.SubTable = kept
        lk.SubTableCount = len(kept)
    return removed_subtables


def tighten_diacritics(font, above_margin=65, above_floor=340, below_margin=95, below_ceil=-110):
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


def unify_line_metrics(font):
    """Ensure identical cross-platform line spacing (Linux/Windows/macOS) via USE_TYPO_METRICS."""
    os2 = font["OS/2"]
    hhea = font["hhea"]
    # Bit 7 = USE_TYPO_METRICS
    os2.fsSelection |= (1 << 7)
    # Sync hhea and sTypo cleanly
    os2.sTypoAscender = 1124
    os2.sTypoDescender = -634
    os2.sTypoLineGap = 0
    hhea.ascent = 1124
    hhea.descent = -634
    hhea.lineGap = 0
    # Tighten legacy Win clipping bounds slightly for tightened diacritics (prevents bloated spacing in old apps)
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
        removed = unstack_ocr_ligatures(font)
        above_n, below_n = tighten_diacritics(font)
        if not args.full:
            subset_arabic_only(font)
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
            f"{ps_name:24s} | glyphs: {orig_glyphs}->{new_glyphs} | unstacked={removed} "
            f"| TTF={ttf_kb:5.1f}KB | WOFF2={woff2_kb:5.1f}KB"
        )


if __name__ == "__main__":
    main()
