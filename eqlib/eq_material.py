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


def load_texture_from_archive(archive, texture_name):
    try:
        from inc_noesis import NoeTexture

        data = archive.get_file(texture_name)
        if data is None:
            alt_name = texture_name.rsplit('.', 1)[0] + '.dds'
            data = archive.get_file(alt_name)
        if data is None:
            alt_name = texture_name.rsplit('.', 1)[0] + '.bmp'
            data = archive.get_file(alt_name)
        if data is None:
            return None

        if len(data) < 4:
            return None

        magic = data[:4]
        if magic == b'DDS ' and len(data) >= 128:
            w = struct.unpack_from('<I', data, 16)[0]
            h = struct.unpack_from('<I', data, 12)[0]
            pf_flags = struct.unpack_from('<I', data, 80)[0]
            pf_fourcc = struct.unpack_from('<I', data, 84)[0]
            if pf_flags & 0x4 and w > 0 and h > 0:
                if pf_fourcc == 0x31545844:
                    tex_type = 3
                elif pf_fourcc == 0x33545844:
                    tex_type = 4
                elif pf_fourcc == 0x35545844:
                    tex_type = 5
                else:
                    return None
                pix_data = data[128:]
                tex = NoeTexture(texture_name, w, h, pix_data, tex_type)
                return tex

        if magic[:2] == b'BM' and len(data) >= 54:
            return None

        return None
    except Exception:
        return None
