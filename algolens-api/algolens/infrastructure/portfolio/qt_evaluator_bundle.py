"""Admission for a byte-pinned, closed native evaluator bundle.

No native code is loaded here. The bounded process owns request/response pipes;
this module yields an explicit isolated launch from verified private bytes.
ELF/manifest rules intentionally match the standalone engine staging tool so
both deployment boundaries validate the same data without importing a checkout.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import struct
import tempfile

_NAME = re.compile(r'[A-Za-z0-9_.+-]{1,160}\Z')
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_MAX_FILE = 512 * 1024 * 1024
_MAX_TOTAL = 1024 * 1024 * 1024
_MANIFEST = 'qt_evaluator_manifest.json'
_ABI = {'platform': 'linux', 'machine': 'x86_64', 'elf_class': 'ELF64', 'cxx_standard': '20'}


def _pairs(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('duplicate_json_key')
        result[name] = value
    return result


def _json(path):
    return json.loads(_read(path, 1024 * 1024).decode('utf-8'), object_pairs_hook=_pairs)


def _read(path, limit=_MAX_FILE):
    with path.open('rb') as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError('bundle_file_too_large')
    return data


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(',', ':')).encode('ascii')


def _name(value):
    if not isinstance(value, str) or not _NAME.fullmatch(value) or value in {'.', '..'}:
        raise ValueError('unsafe_artifact_name')
    return value


def read_elf(data):
    """Only the reviewed Linux ELF64 little-endian x86_64 ABI is admitted."""
    if (len(data) < 64 or data[:7] != b'\x7fELF\x02\x01\x01' or
            data[7] not in {0, 3} or struct.unpack_from('<H', data, 18)[0] != 62):
        raise ValueError('unsupported_elf_abi')
    kind = struct.unpack_from('<H', data, 16)[0]
    offset = struct.unpack_from('<Q', data, 32)[0]
    entry_size, count = struct.unpack_from('<HH', data, 54)
    if kind not in {2, 3} or entry_size != 56 or not 0 < count <= 512:
        raise ValueError('invalid_elf_program_headers')
    if offset + count * entry_size > len(data):
        raise ValueError('invalid_elf_program_headers')
    segments = []
    interpreter = None
    dynamic = None
    for index in range(count):
        row = struct.unpack_from('<IIQQQQQQ', data, offset + index * entry_size)
        ptype, _, start, address, _, size, _, _ = row
        if start + size > len(data):
            raise ValueError('invalid_elf_segment')
        if ptype == 1:
            segments.append((start, address, size))
        if ptype == 2:
            if dynamic is not None or size % 16:
                raise ValueError('invalid_elf_dynamic')
            dynamic = (start, size)
        if ptype == 3:
            if interpreter is not None or not size or data[start + size - 1] != 0:
                raise ValueError('invalid_elf_interpreter')
            interpreter = data[start:start + size - 1].decode('ascii')
    if dynamic is None:
        raise ValueError('missing_elf_dynamic')
    tags = []
    for index in range(dynamic[0], sum(dynamic), 16):
        tag, value = struct.unpack_from('<qQ', data, index)
        if tag == 0:
            break
        if tag in {0x7fffffff, 0x7ffffffd, 0x6ffffefb, 0x6ffffefc}:
            raise ValueError('elf_filter_not_supported')
        tags.append((tag, value))
    else:
        raise ValueError('unterminated_elf_dynamic')
    tables = [value for tag, value in tags if tag == 5]
    sizes = [value for tag, value in tags if tag == 10]
    if len(tables) != 1 or len(sizes) != 1:
        raise ValueError('invalid_elf_string_table')
    tables = [(start + tables[0] - address, sizes[0]) for start, address, size in segments
              if address <= tables[0] and tables[0] + sizes[0] <= address + size]
    if len(tables) != 1:
        raise ValueError('invalid_elf_string_table')
    start, size = tables[0]
    strings = data[start:start + size]

    def string_at(index):
        if index >= size or (end := strings.find(b'\0', index)) < 0:
            raise ValueError('invalid_elf_string')
        return strings[index:end].decode('ascii')

    needed = [_name(string_at(value)) for tag, value in tags if tag == 1]
    sonames = [_name(string_at(value)) for tag, value in tags if tag == 14]
    if len(needed) != len(set(needed)) or len(sonames) > 1:
        raise ValueError('ambiguous_elf_names')
    return {'needed': sorted(needed), 'soname': sonames[0] if sonames else None,
            'interpreter': interpreter,
            'runpath': [string_at(value) for tag, value in tags if tag in {15, 29}]}


def _metadata(metadata):
    if (not isinstance(metadata, dict) or set(metadata) != {'evaluator_build', 'compiler', 'abi'}
            or metadata['abi'] != _ABI or not isinstance(metadata['compiler'], dict)
            or set(metadata['compiler']) != {'id', 'version'}):
        raise ValueError('invalid_bundle_metadata')
    for value in [metadata['evaluator_build'], *metadata['compiler'].values()]:
        if not isinstance(value, str) or not value.strip() or len(value) > 256:
            raise ValueError('invalid_bundle_metadata')


def _closure(rows):
    names = {row['name']: row for row in rows}
    if len(names) != len(rows) or not 4 <= len(rows) <= 256:
        raise ValueError('ambiguous_bundle_artifacts')
    required = {'executable': 'qt_evaluator', 'engine': 'libtrade_ngin.so',
                'loader': 'ld-linux-x86-64.so.2'}
    for role, name in required.items():
        if [row['name'] for row in rows if row['role'] == role] != [name]:
            raise ValueError('missing_bundle_role')
    if 'libcrypto.so.3' not in names:
        raise ValueError('missing_bundle_crypto')
    for row in rows:
        _name(row['name'])
        if row['role'] not in {'executable', 'engine', 'loader', 'dependency'}:
            raise ValueError('invalid_bundle_role')
        path = ('bin/' if row['role'] == 'executable' else 'lib/') + row['name']
        if row['path'] != path:
            raise ValueError('unsafe_bundle_path')
        if row['role'] != 'executable' and row['elf']['soname'] != row['name']:
            raise ValueError('bundle_soname_mismatch')
        if row['role'] == 'executable':
            interpreter = row['elf']['interpreter']
            if (not isinstance(interpreter, str) or not interpreter.startswith('/') or
                    Path(interpreter).name != required['loader']):
                raise ValueError('bundle_interpreter_mismatch')
        elif row['elf']['interpreter'] is not None and row['name'] != 'libc.so.6':
            raise ValueError('unexpected_bundle_interpreter')
        if any(name not in names for name in row['elf']['needed']):
            raise ValueError('unresolved_bundle_dependency')
    visited = set()
    pending = [required['executable'], required['loader']]
    while pending:
        name = pending.pop()
        if name not in visited:
            visited.add(name)
            pending.extend(names[name]['elf']['needed'])
    if visited != set(names):
        raise ValueError('disconnected_bundle_artifact')


def verify_bundle(directory, expected_bundle_sha256):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir() or directory.resolve() != directory.absolute():
        raise ValueError('invalid_bundle_directory')
    path = directory / _MANIFEST
    if path.is_symlink() or not path.is_file():
        raise ValueError('invalid_bundle_manifest')
    manifest = _json(path)
    if (not isinstance(manifest, dict) or set(manifest) !=
            {'schema', 'wire_schema', 'evaluator_build', 'compiler', 'abi', 'artifacts', 'bundle_sha256'}
            or manifest['schema'] != 'qt-evaluator-bundle/v1' or manifest['wire_schema'] != 'qt-eval/v1'
            or not isinstance(expected_bundle_sha256, str) or not _DIGEST.fullmatch(expected_bundle_sha256)):
        raise ValueError('invalid_bundle_manifest')
    unsigned = {key: value for key, value in manifest.items() if key != 'bundle_sha256'}
    if manifest['bundle_sha256'] != expected_bundle_sha256 or sha256(_canonical(unsigned)).hexdigest() != expected_bundle_sha256:
        raise ValueError('bundle_digest_mismatch')
    _metadata({key: manifest[key] for key in ['evaluator_build', 'compiler', 'abi']})
    rows = manifest['artifacts']
    if not isinstance(rows, list):
        raise ValueError('invalid_bundle_artifacts')
    total = 0
    expected_files = {_MANIFEST}
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'name', 'role', 'path', 'size', 'sha256', 'elf'}
                or type(row['size']) is not int or not 0 < row['size'] <= _MAX_FILE
                or not isinstance(row['sha256'], str) or not _DIGEST.fullmatch(row['sha256'])):
            raise ValueError('invalid_bundle_artifact')
        _name(row['name'])
        expected_path = ('bin/' if row['role'] == 'executable' else 'lib/') + row['name']
        if row['path'] != expected_path:
            raise ValueError('unsafe_bundle_path')
        path = directory / row['path']
        if path.parent.is_symlink() or path.is_symlink() or not path.is_file():
            raise ValueError('invalid_bundle_file')
        total += row['size']
        if total > _MAX_TOTAL or path.stat().st_size != row['size']:
            raise ValueError('bundle_artifact_size')
        data = _read(path)
        if sha256(data).hexdigest() != row['sha256'] or read_elf(data) != row['elf']:
            raise ValueError('bundle_artifact_changed')
        expected_files.add(row['path'])
    _closure(rows)
    actual_files = set()
    for path in directory.rglob('*'):
        if path.is_symlink():
            raise ValueError('bundle_symlink')
        if path.is_file():
            actual_files.add(path.relative_to(directory).as_posix())
        elif path.relative_to(directory).as_posix() not in {'bin', 'lib'}:
            raise ValueError('unexpected_bundle_directory')
    if actual_files != expected_files:
        raise ValueError('unexpected_bundle_file')
    return manifest


class QtEvaluatorBundleUnavailable(Exception):
    """Fixed admission reason; no deployment path or request data is exposed."""


@dataclass(frozen=True)
class QtBundleLaunch:
    argv: tuple[str, ...]
    pass_fds: tuple[int, ...]


@dataclass(frozen=True)
class QtBundleSnapshot:
    directory: Path
    manifest: dict

    def command(self, descriptors: dict[str, int]) -> tuple[str, ...]:
        names = {row['name'] for row in self.manifest['artifacts']}
        if (type(descriptors) is not dict or set(descriptors) != names or
                any(type(fd) is not int or fd < 3 for fd in descriptors.values()) or
                len(set(descriptors.values())) != len(descriptors)):
            raise ValueError('invalid_bundle_descriptors')
        by_role = {row['role']: row['name'] for row in self.manifest['artifacts']
                   if row['role'] in {'executable', 'engine', 'loader'}}
        path = lambda name: f'/proc/self/fd/{descriptors[name]}'
        executable = path(by_role['executable'])
        loader = path(by_role['loader'])
        # Every admitted DT_NEEDED SONAME is loaded from its verified sealed
        # descriptor, including crypto and transitive dependencies. No private
        # file is reopened by the native loader after the admission boundary.
        preload = ':'.join(path(row['name']) for row in self.manifest['artifacts']
                           if row['role'] not in {'executable', 'loader'})
        inhibit = ['', *sorted(names), *(path(name) for name in sorted(names))]
        return ('/usr/bin/unshare', '-Urn', '--', loader,
                '--inhibit-cache', '--inhibit-rpath', ':'.join(inhibit),
                '--library-path', '', '--preload', preload, executable)



@dataclass(frozen=True)
class QtEvaluatorBundle:
    directory: Path
    expected_bundle_sha256: str
    expected_executable_sha256: str
    expected_build: str

    def __post_init__(self):
        if (not isinstance(self.directory, Path) or not self.directory.is_absolute()
                or any(not isinstance(value, str) or not _DIGEST.fullmatch(value)
                       for value in [self.expected_bundle_sha256, self.expected_executable_sha256])
                or not isinstance(self.expected_build, str) or not self.expected_build.strip()
                or len(self.expected_build) > 256):
            raise ValueError('invalid_evaluator_bundle_configuration')

    @contextmanager
    def snapshot(self):
        """Hash the copied bytes, never reopen a verified deployment file at spawn."""
        try:
            manifest = verify_bundle(self.directory, self.expected_bundle_sha256)
            executable = next(row for row in manifest['artifacts'] if row['role'] == 'executable')
            if (manifest['evaluator_build'] != self.expected_build or
                    executable['sha256'] != self.expected_executable_sha256):
                raise ValueError('bundle_identity_mismatch')
            with tempfile.TemporaryDirectory(prefix='qt-evaluator-bundle-') as temporary:
                directory = Path(temporary)
                directory.chmod(0o700)
                for row in manifest['artifacts']:
                    source = self.directory / row['path']
                    # Check link status again; content hashing below protects a
                    # replaced inode or in-place overwrite during this copy.
                    if source.is_symlink() or source.parent.is_symlink():
                        raise ValueError('bundle_symlink')
                    with source.open('rb') as stream:
                        data = stream.read(_MAX_FILE + 1)
                    if (len(data) != row['size'] or sha256(data).hexdigest() != row['sha256']
                            or read_elf(data) != row['elf']):
                        raise ValueError('bundle_artifact_changed')
                    path = directory / row['path']
                    path.parent.mkdir(mode=0o700, exist_ok=True)
                    path.write_bytes(data)
                    path.chmod(0o500 if row['role'] in {'executable', 'loader'} else 0o400)
                (directory / _MANIFEST).write_bytes(_canonical(manifest) + b'\n')
                # Complete closure and copied metadata are checked before the
                # snapshot is exposed to a launcher or any child is created.
                verify_bundle(directory, self.expected_bundle_sha256)
                yield QtBundleSnapshot(directory, manifest)
        except (OSError, ValueError, TypeError, KeyError, UnicodeError, struct.error, RecursionError):
            raise QtEvaluatorBundleUnavailable('evaluator_bundle_unavailable') from None

    @contextmanager
    def launch(self):
        """Yield the complete sealed native closure for the bounded transport."""
        if os.name != 'posix' or not hasattr(os, 'memfd_create'):
            raise QtEvaluatorBundleUnavailable('evaluator_bundle_isolation_unavailable')
        import fcntl

        descriptors = {}
        try:
            with self.snapshot() as snapshot:
                for row in snapshot.manifest['artifacts']:
                    descriptor = os.memfd_create('qt-evaluator-' + row['name'],
                                                os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC)
                    descriptors[row['name']] = descriptor
                    digest = sha256()
                    copied = 0
                    with (snapshot.directory / row['path']).open('rb') as source:
                        while chunk := source.read(65536):
                            copied += len(chunk)
                            if copied > row['size']:
                                raise ValueError('bundle_snapshot_changed')
                            digest.update(chunk)
                            remaining = memoryview(chunk)
                            while remaining:
                                count = os.write(descriptor, remaining)
                                if count <= 0:
                                    raise OSError('bundle_seal_write')
                                remaining = remaining[count:]
                    if copied != row['size'] or digest.hexdigest() != row['sha256']:
                        raise ValueError('bundle_snapshot_changed')
                    os.fchmod(descriptor, 0o500)
                    fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS,
                                fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW |
                                fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
                yield QtBundleLaunch(snapshot.command(descriptors), tuple(descriptors.values()))
        except QtEvaluatorBundleUnavailable:
            raise
        except (OSError, ValueError):
            raise QtEvaluatorBundleUnavailable('evaluator_bundle_isolation_unavailable') from None
        finally:
            for descriptor in descriptors.values():
                os.close(descriptor)
