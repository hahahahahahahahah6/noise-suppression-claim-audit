"""Read-only documentation and AST evidence audit."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys

from . import __version__
from .phrases import NOISE, NONOISE


def normalize(text):
    return ' '.join(text.lower().replace("n't", ' not').replace('-', ' ').split())


def pattern(phrases):
    return re.compile(r'\b(?:' + '|'.join(re.escape(p) for p in sorted(phrases, key=lambda p: (-len(p), p))) + r')\b')


def claims(text):
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            lines.append('')
        elif match:
            fence = match[1]
            lines.append('')
        else:
            lines.append(line)
    positive = negative = False
    for paragraph in re.split(r'\n\s*\n', '\n'.join(lines)):
        text = normalize(paragraph)
        negative = negative or bool(pattern(NONOISE).search(text))
        text = pattern(NONOISE).sub(' ', text)
        positive = positive or bool(pattern(NOISE).search(text))
    return positive, negative


def evidence(source):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    aliases = {}
    df = False
    shadow = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            shadow.add(node.name)
        elif isinstance(node, ast.Import):
            for name in node.names:
                aliases[name.asname or name.name.split('.')[0]] = name.name if name.asname else name.name.split('.')[0]
                df = df or name.name == 'df.enhance' or name.name.startswith('df.enhance.')
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            df = df or module == 'df.enhance' or module.startswith('df.enhance.')
            for name in node.names:
                aliases[name.asname or name.name] = module + '.' + name.name
    def resolve(node):
        if isinstance(node, ast.Name):
            return '' if node.id in shadow else aliases.get(node.id, '')
        if isinstance(node, ast.Attribute):
            base = resolve(node.value)
            return base + '.' + node.attr if base else ''
        return ''
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''
        resolved = resolve(func)
        operation = resolved.rsplit('.', 1)[-1]
        if name in shadow or operation in shadow:
            continue
        if isinstance(func, ast.Attribute):
            if name in ('reduce_noise', 'suppress_noise', 'remove_noise') or (name == 'enhance' and df):
                return True
        if isinstance(func, ast.Name):
            if (name == 'reduce_noise' and (resolved == 'noisereduce' or resolved.startswith('noisereduce.'))) or (resolved.startswith('noisereduce.') and operation == 'reduce_noise') or (resolved.startswith('df.enhance.') and operation == 'enhance'):
                return True
    return False


def audit(root, ignore=()):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise OSError('root must be a readable directory')
    if root.stat().st_mode & 0o444 == 0 or root.stat().st_mode & 0o111 == 0:
        raise OSError('root is unreadable')
    ignored = [Path(p).as_posix().strip('/') for p in ignore]
    positive, negative = [], []
    production = test = False
    def excluded(rel):
        return any(rel == p or rel.startswith(p + '/') for p in ignored)
    def error(exc):
        raise exc
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=error):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink() and not excluded((Path(directory) / d).relative_to(root).as_posix()))
        for filename in sorted(files):
            path = Path(directory) / filename
            rel = path.relative_to(root)
            if path.is_symlink() or excluded(rel.as_posix()):
                continue
            is_doc = rel.as_posix() == 'README.md' or (path.suffix == '.md' and 'docs' in rel.parts[:-1])
            if is_doc:
                yes, no = claims(path.read_text(encoding='utf-8'))
                if yes:
                    positive.append(rel.as_posix())
                if no:
                    negative.append(rel.as_posix())
            if path.suffix != '.py' or set(rel.parts[:-1]) & {'fixtures', 'docs', 'examples'}:
                continue
            is_test = 'tests' in rel.parts[:-1] or filename.startswith('test_') or filename.endswith('_test.py')
            found = evidence(path.read_text(encoding='utf-8'))
            if is_test:
                test = test or found
            else:
                production = production or found
    findings = []
    if positive and not production:
        findings.append(dict(rule='documented-noise-suppression-claim-false', severity='MEDIUM' if test else 'HIGH', message='Documented claim lacks production call evidence.', paths=positive))
    if negative and production:
        findings.append(dict(rule='documented-no-noise-suppression-claim-false', severity='HIGH', message='Documented denial conflicts with production call evidence.', paths=negative))
    return dict(verdict='FAIL' if findings else 'PASS', findings=findings)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[])
    parser.add_argument('--fail-on', choices=['LOW', 'MEDIUM', 'HIGH'], default='HIGH')
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, args.ignore)
    except (OSError, UnicodeError) as exc:
        print('error: ' + str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result['verdict'])
        for finding in result['findings']:
            print('{rule} {severity}: {message}'.format(**finding))
            if args.verbose:
                print('  ' + ', '.join(finding['paths']))
    ranks = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}
    return 2 if any(ranks[f['severity']] >= ranks[args.fail_on] for f in result['findings']) else 0
