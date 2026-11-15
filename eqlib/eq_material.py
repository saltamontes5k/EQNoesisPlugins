import struct


def get_texture_variants(archive, base_name):
    variants = []
    base_no_ext = base_name.rsplit('.', 1)[0] if '.' in base_name else base_name
    for fn in archive.get_file_names():
        lower = fn.lower()
        if lower.startswith(base_no_ext.lower()):
            variants.append(fn)
    if not variants and base_name:
        for fn in archive.get_file_names():
            if base_name.lower() in fn.lower():
                variants.append(fn)
    return variants


# ---------------------------------------------------------------------------
# BMP (.bmp, classic .s3d textures): 8-bit palettised or 24/32-bit, uncompressed.
# Rows are kept in file order (a normal BMP stores the bottom row first): that
# is how the client maps WLD UVs onto them. "masked" makes palette index 0
# transparent, which is how the WLD cut-out method works.
# Source: Everquest_Model_Viewer readBMP (verified against the client).
def _decode_bmp(data, masked=False):
    if len(data) < 54 or data[0] != 0x42 or data[1] != 0x4D:
        return None
    data_offset = struct.unpack_from('<I', data, 10)[0]
    hdr_size = struct.unpack_from('<I', data, 14)[0]
    w = struct.unpack_from('<i', data, 18)[0]
    h_raw = struct.unpack_from('<i', data, 22)[0]
    bpp = struct.unpack_from('<H', data, 28)[0]
    comp = struct.unpack_from('<I', data, 30)[0]
    h = abs(h_raw)
    if w <= 0 or h <= 0:
        return None
    if comp != 0 and comp != 3:
        return None  # compressed BMPs unsupported
    if bpp not in (8, 24, 32):
        return None

    stride = ((w * bpp + 31) >> 5) << 2
    out = bytearray(w * h * 4)

    if bpp == 8:
        pal_off = 14 + hdr_size
        # 256-entry RGBA table; index 0 becomes transparent when masked.
        pal = bytearray(256 * 4)
        for i in range(256):
            q = pal_off + i * 4
            if q + 3 > len(data):
                break
            pal[i * 4 + 0] = data[q + 2]
            pal[i * 4 + 1] = data[q + 1]
            pal[i * 4 + 2] = data[q]
            pal[i * 4 + 3] = 0 if (masked and i == 0) else 255
        pal_rows = [bytes(pal[i * 4:(i + 1) * 4]) for i in range(256)]
        for y in range(h):
            row = data_offset + y * stride
            if row + w > len(data):
                break
            rgba_row = b''.join([pal_rows[b] for b in data[row:row + w]])
            out[y * w * 4:(y + 1) * w * 4] = rgba_row
    else:
        step = bpp // 8
        row_bytes = w * 4
        white = b'\xff' * w
        for y in range(h):
            row = data_offset + y * stride
            if row + w * step > len(data):
                break
            base = y * row_bytes
            rowb = data[row:row + w * step]
            # file order is BGR(A): slice channels out at C speed. The extended
            # slice must cover exactly this one row - using the whole-image
            # length here raised "attempt to assign bytes of size N to extended
            # slice of size M" for anything taller than one pixel row.
            out[base + 0:base + row_bytes:4] = rowb[2::step]
            out[base + 1:base + row_bytes:4] = rowb[1::step]
            out[base + 2:base + row_bytes:4] = rowb[0::step]
            if bpp == 32:
                out[base + 3:base + row_bytes:4] = rowb[3::4]
            else:
                out[base + 3:base + row_bytes:4] = white
    return w, h, bytes(out)


# ---------------------------------------------------------------------------
# TGA (some effect sprites): uncompressed or RLE, 24/32-bit, either origin.
# Source: Everquest_Model_Viewer readTGA.
def _decode_tga(data):
    if len(data) < 18:
        return None
    id_len = data[0]
    color_map = data[1]
    img_type = data[2]
    w = struct.unpack_from('<H', data, 12)[0]
    h = struct.unpack_from('<H', data, 14)[0]
    bpp = data[16]
    desc = data[17]
    if img_type not in (2, 10) or bpp not in (24, 32):
        return None
    if w <= 0 or h <= 0:
        return None

    step = bpp // 8
    n = w * h
    p = 18 + id_len
    if color_map:
        p += struct.unpack_from('<H', data, 5)[0] * ((data[7] + 7) // 8)

    raw = bytearray(n * step)
    if img_type == 2:
        need = n * step
        if p + need > len(data):
            need = max(0, len(data) - p)
        raw[:need] = data[p:p + need]
    else:
        i = 0
        while i < n and p < len(data):
            c = data[p]
            p += 1
            k = (c & 127) + 1
            if c & 128:
                if p + step > len(data):
                    break
                packet = data[p:p + step]
                p += step
                for _ in range(k):
                    if i >= n:
                        break
                    raw[i * step:(i + 1) * step] = packet
                    i += 1
            else:
                k = min(k, n - i, (len(data) - p) // step)
                raw[i * step:(i + k) * step] = data[p:p + k * step]
                i += k
                p += k * step

    # file order is BGR(A)
    px = bytearray(n * 4)
    px[0::4] = raw[2::step]
    px[1::4] = raw[1::step]
    px[2::4] = raw[0::step]
    if bpp == 32:
        px[3::4] = raw[3::4]
    else:
        px[3::4] = b'\xff' * n
    # TGA stores bottom-up unless bit 5 of the descriptor is set
    out = bytearray(n * 4)
    top = (desc & 0x20) != 0
    for y in range(h):
        src = y if top else h - 1 - y
        out[y * w * 4:(y + 1) * w * 4] = px[src * w * 4:(src + 1) * w * 4]
    return w, h, bytes(out)


# ---------------------------------------------------------------------------
# Uncompressed DDS (16/24/32-bit via channel masks). Compressed DXT formats
# are handed straight to Noesis by the caller.
# Source: Everquest_Model_Viewer readDDS/decodeLevel.
def _decode_dds_uncompressed(data):
    if len(data) < 128 or data[:4] != b'DDS ':
        return None
    h = struct.unpack_from('<I', data, 12)[0]
    w = struct.unpack_from('<I', data, 16)[0]
    pf_flags = struct.unpack_from('<I', data, 80)[0]
    if w <= 0 or h <= 0 or (pf_flags & 0x4):
        return None
    bpp = struct.unpack_from('<I', data, 88)[0]
    if bpp not in (16, 24, 32):
        return None
    masks = [struct.unpack_from('<I', data, 92 + k * 4)[0] for k in range(4)]
    has_alpha = (pf_flags & 0x1) != 0 and masks[3] != 0
    step = bpp // 8
    n = w * h
    if 128 + n * step > len(data):
        return None
    body = data[128:128 + n * step]

    def chan(val, m):
        if not m:
            return 0
        s = 0
        while not ((m >> s) & 1):
            s += 1
        mx = m >> s
        return ((val & m) >> s) * 255 // mx

    out = bytearray(n * 4)
    for i in range(n):
        o = i * step
        if step == 4:
            val = struct.unpack_from('<I', body, o)[0]
        elif step == 3:
            val = body[o] | (body[o + 1] << 8) | (body[o + 2] << 16)
        else:
            val = struct.unpack_from('<H', body, o)[0]
        q = i * 4
        out[q] = chan(val, masks[0])
        out[q + 1] = chan(val, masks[1])
        out[q + 2] = chan(val, masks[2])
        out[q + 3] = chan(val, masks[3]) if has_alpha else 255
    return w, h, bytes(out)


def _decode_dds_dxt(data):
    """DXT1/3/5 passthrough for Noesis. Returns (name, w, h, data, type) or None."""
    if len(data) < 128 or data[:4] != b'DDS ':
        return None
    w = struct.unpack_from('<I', data, 16)[0]
    h = struct.unpack_from('<I', data, 12)[0]
    pf_flags = struct.unpack_from('<I', data, 80)[0]
    fourcc = struct.unpack_from('<I', data, 84)[0]
    if w <= 0 or h <= 0 or not (pf_flags & 0x4):
        return None
    if fourcc == 0x31545844:
        ttype = noesis_type_dxt1()
    elif fourcc == 0x33545844:
        ttype = noesis_type_dxt3()
    elif fourcc == 0x35545844:
        ttype = noesis_type_dxt5()
    else:
        return None
    return w, h, data[128:], ttype


def noesis_type_dxt1():
    import noesis
    return noesis.NOESISTEX_DXT1


def noesis_type_dxt3():
    import noesis
    return noesis.NOESISTEX_DXT3


def noesis_type_dxt5():
    import noesis
    return noesis.NOESISTEX_DXT5


def _make_texture(name, w, h, rgba):
    from inc_noesis import NoeTexture
    import noesis
    return NoeTexture(name, w, h, rgba, noesis.NOESISTEX_RGBA32)


def load_texture_from_archive(archive, texture_name, masked=False):
    """Load a texture by name, trying common extension variants.

    BMP rows are kept in file order (matching how the client maps WLD UVs),
    so WLD V coordinates need no extra row flip on top of the loader's own
    convention.
    """
    try:
        if not texture_name:
            return None
        candidates = [texture_name]
        stem = texture_name.rsplit('.', 1)[0]
        for ext in ('.dds', '.bmp', '.tga'):
            alt = stem + ext
            if alt.lower() != texture_name.lower():
                candidates.append(alt)

        data = None
        used_name = texture_name
        for cand in candidates:
            data = archive.get_file(cand)
            if data is not None:
                used_name = cand
                break
        if data is None or len(data) < 4:
            return None

        magic = data[:4]
        if magic == b'DDS ' and len(data) >= 128:
            dxt = _decode_dds_dxt(data)
            if dxt is not None:
                from inc_noesis import NoeTexture
                w, h, pix, ttype = dxt
                return NoeTexture(used_name, w, h, pix, ttype)
            dec = _decode_dds_uncompressed(data)
            if dec is not None:
                return _make_texture(used_name, dec[0], dec[1], dec[2])
            return None
        if magic[:2] == b'BM':
            dec = _decode_bmp(data, masked=masked)
            if dec is not None:
                return _make_texture(used_name, dec[0], dec[1], dec[2])
            return None
        # TGA has no magic; try it when the name asks for one
        if used_name.lower().endswith('.tga'):
            dec = _decode_tga(data)
            if dec is not None:
                return _make_texture(used_name, dec[0], dec[1], dec[2])
        return None
    except Exception:
        return None


def load_layered_texture(archive, base_name, layer_name):
    """Composite an overlay page over a base texture by alpha.

    Luclin bodies list a skin page plus an armor page drawn over it
    ("<armor>.dds_layer" in the WLD bitmap list); the overlay's alpha says
    where it covers and 0 lets the skin show through.
    Source: Everquest_Model_Viewer layered().
    """
    try:
        base = load_texture_from_archive(archive, base_name)
        layer = load_texture_from_archive(archive, layer_name)
        if base is None:
            return None
        import noesis
        if layer is None or base.pixelType != noesis.NOESISTEX_RGBA32:
            return base
        if layer.pixelType != noesis.NOESISTEX_RGBA32:
            return base

        bw, bh = base.width, base.height
        lw, lh = layer.width, layer.height
        out = bytearray(base.pixelData)
        lp = layer.pixelData
        for y in range(bh):
            ly = min(lh - 1, y * lh // bh)
            for x in range(bw):
                lx = min(lw - 1, x * lw // bw)
                q = (y * bw + x) * 4
                lo = (ly * lw + lx) * 4
                a = lp[lo + 3]
                if a == 0:
                    continue
                if a == 255:
                    out[q] = lp[lo]
                    out[q + 1] = lp[lo + 1]
                    out[q + 2] = lp[lo + 2]
                else:
                    ia = 255 - a
                    out[q] = (out[q] * ia + lp[lo] * a) // 255
                    out[q + 1] = (out[q + 1] * ia + lp[lo + 1] * a) // 255
                    out[q + 2] = (out[q + 2] * ia + lp[lo + 2] * a) // 255
                out[q + 3] = 255
        return _make_texture('%s+%s' % (base_name, layer_name), bw, bh, bytes(out))
    except Exception:
        return None
