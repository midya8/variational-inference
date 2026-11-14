"""Compare an installed wheel's API and both CLI paths outside the checkout.

This checks packaging and entry points. It is not an independent math oracle;
the unit suite contains the enumeration and analytic references.
"""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import varilab

MODEL = {'version': 1, 'fields': [.2, -.3],
         'edges': [{'i': 0, 'j': 1, 'weight': .7}]}
CASES = [
    ('exact', 'exact', {}, []),
    ('fit', 'mean_field', {'initial': [.1, -.2], 'order': [1, 0],
                          'sweeps': 3, 'tolerance': 0},
     ['--initial', '[0.1,-0.2]', '--order', '[1,0]', '--sweeps', '3',
      '--tolerance', '0']),
    ('compare', 'compare', {'initial': [.1, -.2]},
     ['--initial', '[0.1,-0.2]']),
    ('curvature', 'curvature', {'means': [.1, -.2]},
     ['--means', '[0.1,-0.2]']),
    ('forest', 'forest', {'evidence': [{'i': 0, 'spin': 1}]},
     ['--evidence', '[{"i":0,"spin":1}]']),
    ('map', 'forest_map', {'evidence': [{'i': 0, 'spin': 1}]},
     ['--evidence', '[{"i":0,"spin":1}]']),
    ('plan', 'elimination_plan', {'query': [1]}, ['--query', '[1]']),
    ('eliminate', 'eliminate', {'query': [1]}, ['--query', '[1]']),
    ('cyclic-map', 'cyclic_map', {'query': [1]}, ['--query', '[1]']),
]
DEMOS = [('demo', 'varilab.demo', 'demo'),
         ('curvature-demo', 'varilab.curvature', 'curvature_demo'),
         ('forest-demo', 'varilab.forest', 'forest_demo'),
         ('map-demo', 'varilab.decoding', 'map_demo'),
         ('elimination-demo', 'varilab.elimination', 'elimination_demo'),
         ('cyclic-map-demo', 'varilab.cyclic_map', 'cyclic_map_demo')]
MODULES = ['varilab'] + ['varilab.' + n for n in
    ['__main__', 'core', 'curvature', 'cyclic_map', 'decoding', 'demo',
     'elimination', 'forest']]


def normalized(value):
    return json.loads(json.dumps(value, allow_nan=False))


def checked(args, cwd, env):
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=env,
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f'{args!r}\n{result.stdout}\n{result.stderr}')
    return result.stdout


def main():
    expected = [normalized(getattr(varilab, api)(MODEL, **kw))
                for _, api, kw, _ in CASES]
    demos = [normalized(getattr(importlib.import_module(module), name)())
             for _, module, name in DEMOS]
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    env['PYTHONNOUSERSITE'] = '1'
    with tempfile.TemporaryDirectory(prefix='varilab-installed-') as temp:
        directory = Path(temp)
        wheels = directory / 'wheels'
        wheels.mkdir()
        checked([sys.executable, '-m', 'pip', 'wheel', '--no-deps',
                 '--no-build-isolation', ROOT, '-w', wheels], directory, env)
        wheel_files = list(wheels.glob('varilab-*.whl'))
        assert len(wheel_files) == 1, wheel_files
        environment = directory / 'venv'
        venv.EnvBuilder(with_pip=True).create(environment)
        binaries = environment / ('Scripts' if os.name == 'nt' else 'bin')
        python = binaries / ('python.exe' if os.name == 'nt' else 'python')
        entry = binaries / ('varilab.exe' if os.name == 'nt' else 'varilab')
        checked([python, '-m', 'pip', 'install', '--no-deps', wheel_files[0]],
                directory, env)
        origin_code = '''import importlib, importlib.metadata, json, sys
from pathlib import Path
names = json.loads(sys.argv[1])
base = Path(sys.prefix).resolve()
paths = [Path(importlib.import_module(n).__file__).resolve() for n in names]
assert all(base in p.parents for p in paths), paths
assert importlib.metadata.version('varilab') == '0.6.0'
print(json.dumps([str(p) for p in paths]))
'''
        origins = json.loads(checked([python, '-c', origin_code,
                                      json.dumps(MODULES)], directory, env))
        model_file = directory / 'model.json'
        model_file.write_text(json.dumps(MODEL), encoding='utf-8')
        api_code = '''import json,sys,varilab
model=json.load(open(sys.argv[1]))
print(json.dumps(getattr(varilab,sys.argv[2])(model,**json.loads(sys.argv[3])),allow_nan=False))
'''
        for (_, api, kw, _), reference in zip(CASES, expected):
            actual = json.loads(checked([python, '-c', api_code, model_file,
                                         api, json.dumps(kw)], directory, env))
            assert actual == reference, api
        invalid = ['{', '{"version":1,"version":1,"fields":[0],"edges":[]}',
                   '{"version":1,"fields":[NaN],"edges":[]}', ' ' * 262145]
        rejected = 0
        for command in [[entry], [python, '-m', 'varilab']]:
            for (name, _, _, flags), reference in zip(CASES, expected):
                actual = json.loads(checked(command + [name, model_file] + flags,
                                            directory, env))
                assert actual == reference, name
            for (name, _, _), reference in zip(DEMOS, demos):
                assert json.loads(checked(command + [name], directory, env)) == reference, name
            bad_file = directory / 'invalid.json'
            for body in invalid:
                bad_file.write_text(body, encoding='utf-8')
                result = subprocess.run([str(a) for a in command + ['exact', bad_file]],
                    cwd=directory, env=env, capture_output=True, text=True, timeout=120)
                assert result.returncode == 2 and result.stdout == '', result
                assert 'Traceback' not in result.stderr, result.stderr
                rejected += 1
        print(json.dumps({'wheel': wheel_files[0].name, 'module_origins': len(origins),
                          'installed_api_cases': len(CASES), 'cli_paths': 2,
                          'queries_per_cli_path': len(CASES),
                          'demos_per_cli_path': len(DEMOS),
                          'malformed_input_rejections': rejected}))


if __name__ == '__main__':
    main()
