import struct
import zlib
import io


class PfsFile(object):
    __slots__ = ('crc', 'size', 'offset', 'data', 'name')

    def __init__(self, crc=0, size=0, offset=0, data=b'', name=''):
        self.crc = crc
        self.size = size
        self.offset = offset
        self.data = data
        self.name = name

    def get_name(self):
        return self.name

    def get_data(self):
        return self.data

    def get_size(self):
        return self.size


class PfsArchive(object):
    def __init__(self):
        self.files = []
        self.file_names = {}
        self.has_wld = False
        self.version = 0

    @staticmethod
    def from_bytes(data):
        archive = PfsArchive()
        archive._parse(data)
        return archive

    def get_file(self, name):
        lower_name = name.lower()
        for f in self.files:
            if f.name.lower() == lower_name:
                return f.data
        return None

    def get_file_names(self):
        return [f.name for f in self.files]

    def has_file_containing(self, substring):
        lower = substring.lower()
        for f in self.files:
            if lower in f.name.lower():
                return True
        return False

    def _parse(self, data):
        stream = io.BytesIO(data)
        stream_len = len(data)

        directory_offset = struct.unpack('<i', stream.read(4))[0]
        _magic = stream.read(4)  # "PFS "
        pfs_version = struct.unpack('<i', stream.read(4))[0]
        self.version = pfs_version

        stream.seek(directory_offset)
        file_count = struct.unpack('<i', stream.read(4))[0]

        file_names = []

        for i in range(file_count):
            crc = struct.unpack('<I', stream.read(4))[0]
            offset = struct.unpack('<I', stream.read(4))[0]
            size = struct.unpack('<I', stream.read(4))[0]

            if offset > stream_len:
                continue

            cached_pos = stream.tell()

            stream.seek(offset)
            inflated_size = 0
            file_bytes = bytearray()

            while inflated_size < size:
                deflated_length = struct.unpack('<I', stream.read(4))[0]
                inflated_length = struct.unpack('<I', stream.read(4))[0]

                if deflated_length >= stream_len:
                    break

                compressed_bytes = stream.read(deflated_length)
                try:
                    inflated_bytes = zlib.decompress(compressed_bytes)
                except zlib.error:
                    break

                file_bytes.extend(inflated_bytes)
                inflated_size += inflated_length

            file_data = bytes(file_bytes[:size])

            if crc == 0x61580AC9 or (crc == 0xFFFFFFFF and len(file_names) == 0):
                dict_stream = io.BytesIO(file_data)
                filename_count = struct.unpack('<I', dict_stream.read(4))[0]
                for j in range(filename_count):
                    name_len = struct.unpack('<I', dict_stream.read(4))[0]
                    name_bytes = dict_stream.read(name_len)
                    name = name_bytes.rstrip(b'\x00').decode('latin-1', errors='replace')
                    file_names.append(name)
                stream.seek(cached_pos)
                continue

            self.files.append(PfsFile(crc=crc, size=size, offset=offset, data=file_data))
            stream.seek(cached_pos)

        self.files.sort(key=lambda f: f.offset)

        for i, f in enumerate(self.files):
            if pfs_version == 0x10000:
                f.name = '%08X.bin' % f.crc
            elif pfs_version == 0x20000:
                if i < len(file_names):
                    f.name = file_names[i]
                    self.file_names[file_names[i].lower()] = f
                    if file_names[i].lower().endswith('.wld'):
                        self.has_wld = True
