"""Build a closed synthetic ELF bundle inside the disposable fixture image."""
from hashlib import sha256
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from qt_evaluator_bundle import read_elf, verify_bundle

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--fixture-dir', type=Path, default=Path('/fixture'))
parser.add_argument('--output', type=Path, default=Path('/bundle'))
args = parser.parse_args()
root = args.output
(root / 'bin').mkdir(parents=True)
(root / 'lib').mkdir()
files = {'qt_evaluator': args.fixture_dir / 'qt_evaluator',
         'libtrade_ngin.so': args.fixture_dir / 'libtrade_ngin.so'}
listing = subprocess.run(['ldd', str(files['qt_evaluator'])], check=True, text=True, capture_output=True).stdout
for line in listing.splitlines():
    pieces = line.split()
    for piece in pieces:
        if piece.startswith('/'):
            path = Path(piece)
            files[path.name] = path
roles = {'qt_evaluator': 'executable', 'libtrade_ngin.so': 'engine', 'ld-linux-x86-64.so.2': 'loader'}
rows = []
for name, source in sorted(files.items()):
    role = roles.get(name, 'dependency')
    path = ('bin/' if role == 'executable' else 'lib/') + name
    shutil.copyfile(source, root / path)
    (root / path).chmod(0o555)
    data = (root / path).read_bytes()
    rows.append(dict(name=name, role=role, path=path, size=len(data), sha256=sha256(data).hexdigest(), elf=read_elf(data)))
manifest = dict(schema='qt-evaluator-bundle/v1', wire_schema='qt-eval/v1',
                evaluator_build='synthetic-container-smoke', compiler={'id':'GNU','version':'synthetic'},
                abi={'platform':'linux','machine':'x86_64','elf_class':'ELF64','cxx_standard':'20'}, artifacts=rows)
canonical = lambda obj: json.dumps(obj, sort_keys=True, separators=(',', ':')).encode('ascii')
manifest['bundle_sha256'] = sha256(canonical(manifest)).hexdigest()
(root / 'qt_evaluator_manifest.json').write_bytes(canonical(manifest))
verify_bundle(root, manifest['bundle_sha256'])
