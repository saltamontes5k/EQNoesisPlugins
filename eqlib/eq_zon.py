"""EQG zone definition (.zon).

Two formats ship with the client:

* `EQGZ` (binary, Luclin and later): the zone's model list, every object
  instance with its placement, "area" volumes and point lights. This is what
  places the `.mod` props that a modern zone archive contains but the WLD
  does not describe.
* `EQTZ` (text, classic): only terrain parameters (name, extents,
  units-per-vert, cover/light map sizes). Nothing a viewer can draw.

Layout verified byte-exact against `D:/EverQuest/arena.zon` (56 models,
129 instances, 4 areas, 10 lights, 0 bytes left over). Descriptions come from
quail (github.com/dariusuknuis/quail, `raw/zon_read.go` and
`wce/def/eqgzondef.yaml`), the Go reader the Blender add-on uses.

Instance rotations are stored in "legacy RZ, RY, RX" order, i.e. the three
floats are yaw, pitch, roll - not (rx, ry, rz).

Note: `model` is an index into the model list, `instance` is a name offset
into the string block. Per-vertex "lit" colours (RGBA per vertex, version 2+)
follow each instance and are the instance's baked lighting.
"""
import struct


class EqgZonModel(object):
    __slots__ = ('name',)

    def __init__(self, name=''):
        self.name = name

    def __repr__(self):
        return 'EqgZonModel(%r)' % self.name


class EqgZonInstance(object):
    __slots__ = ('model', 'name', 'translation', 'rotation', 'scale', 'lits')

    def __init__(self):
        self.model = ''
        self.name = ''
        self.translation = (0.0, 0.0, 0.0)
        self.rotation = (0.0, 0.0, 0.0)   # yaw, pitch, roll
        self.scale = 1.0
        self.lits = []                    # [(r, g, b, a), ...] per vertex

    def __repr__(self):
        return 'EqgZonInstance(%r -> %r at %s)' % (self.name, self.model, (self.translation,))


class EqgZonArea(object):
    __slots__ = ('name', 'center', 'orientation', 'extents')

    def __init__(self):
        self.name = ''
        self.center = (0.0, 0.0, 0.0)
        self.orientation = (0.0, 0.0, 0.0)
        self.extents = (0.0, 0.0, 0.0)


class EqgZonLight(object):
    __slots__ = ('name', 'position', 'color', 'radius')

    def __init__(self):
        self.name = ''
        self.position = (0.0, 0.0, 0.0)
        self.color = (0.0, 0.0, 0.0)
        self.radius = 0.0


class EqgZonFile(object):
    def __init__(self, data):
        self.is_binary = False
        self.version = 0
        self.models = []
        self.instances = []
        self.areas = []
        self.lights = []
        self.trailing_bytes = 0
        self.text = {}
        self._parse(data)

    # -- helpers ---------------------------------------------------
    def instances_for(self, model_name):
        want = model_name.lower()
        return [i for i in self.instances if i.model.lower() == want]

    def model_names(self):
        return [m.name for m in self.models]

    # -- parsing ---------------------------------------------------
    def _parse(self, data):
        if len(data) < 8:
            return
        head = data[:4]
        if head == b'EQTZ':
            self._parse_text(data)
            return
        if head != b'EQGZ':
            return
        self.is_binary = True
        stream_len = len(data)
        (version, name_len, model_count, instance_count,
         area_count, light_count) = struct.unpack_from('<6I', data, 4)
        self.version = version
        off = 28
        name_data = data[off:off + name_len]
        off += name_len

        def name_at(idx):
            if idx < 0 or idx >= len(name_data):
                return ''
            end = name_data.find(b'\x00', idx)
            if end < 0:
                end = len(name_data)
            return name_data[idx:end].decode('latin-1', errors='replace')

        for _ in range(model_count):
            if off + 4 > stream_len:
                return
            idx = struct.unpack_from('<i', data, off)[0]
            off += 4
            self.models.append(EqgZonModel(name_at(idx)))
        names = [m.name for m in self.models]

        for _ in range(instance_count):
            if off + 36 > stream_len:
                self.trailing_bytes = stream_len - off
                return
            model_id, name_off = struct.unpack_from('<2i', data, off)
            off += 8
            tx, ty, tz, rx, ry, rz, scale = struct.unpack_from('<7f', data, off)
            off += 28
            inst = EqgZonInstance()
            if 0 <= model_id < len(names):
                inst.model = names[model_id]
            inst.name = name_at(name_off)
            inst.translation = (tx, ty, tz)
            inst.rotation = (rx, ry, rz)
            inst.scale = scale
            if version > 1:
                if off + 4 > stream_len:
                    return
                lit_count = struct.unpack_from('<I', data, off)[0]
                off += 4
                # 4 bytes per entry; guard against a corrupt count
                if lit_count * 4 > stream_len - off:
                    lit_count = (stream_len - off) // 4
                lits = []
                for k in range(lit_count):
                    base = off + k * 4
                    lits.append((data[base], data[base + 1], data[base + 2], data[base + 3]))
                off += lit_count * 4
                inst.lits = lits
            self.instances.append(inst)

        for _ in range(area_count):
            if off + 40 > stream_len:
                return
            name_off = struct.unpack_from('<i', data, off)[0]
            off += 4
            vals = struct.unpack_from('<9f', data, off)
            off += 36
            area = EqgZonArea()
            area.name = name_at(name_off)
            area.center = vals[0:3]
            area.orientation = vals[3:6]
            area.extents = vals[6:9]
            self.areas.append(area)

        for _ in range(light_count):
            if off + 32 > stream_len:
                return
            name_off = struct.unpack_from('<i', data, off)[0]
            off += 4
            vals = struct.unpack_from('<7f', data, off)
            off += 28
            light = EqgZonLight()
            light.name = name_at(name_off)
            light.position = vals[0:3]
            light.color = vals[3:6]
            light.radius = vals[6]
            self.lights.append(light)

        self.trailing_bytes = stream_len - off

    def _parse_text(self, data):
        text = data.decode('latin-1', errors='replace')
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith('*'):
                continue
            parts = line[1:].split(None, 1)
            if not parts:
                continue
            self.text[parts[0].upper()] = parts[1].strip() if len(parts) > 1 else ''
