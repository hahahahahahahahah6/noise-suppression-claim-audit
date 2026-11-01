import unittest

EXPECTED_NOISE = ('noise suppression', 'noise reduction', 'suppresses noise', 'suppress noise', 'reduces noise', 'reduce noise', 'removes noise', 'remove noise', 'removes background noise', 'reduces background noise', 'suppresses background noise', 'background noise suppression', 'background noise reduction', 'background noise removal', 'removes ambient noise', 'suppresses ambient noise', 'noise cancellation', 'noise cancelling', 'noise canceling', 'active noise cancellation', 'denoises audio', 'denoise audio', 'audio denoising', 'audio noise reduction', 'noise free audio', 'noise free speech', 'cleans up noisy audio', 'removes noise from audio', 'suppresses noise in audio', 'reduces noise in audio', 'noise suppressed', 'noise reduced', 'denoising audio', 'denoising speech', 'speech denoising', 'removes noisy background', 'filters out background noise', 'filters background noise', 'eliminates background noise', 'eliminate background noise', 'removes hiss', 'noise removal')
EXPECTED_NONOISE = ('no noise suppression', 'does not suppress noise', 'without noise suppression', 'no noise reduction', 'does not reduce noise', 'without noise reduction', 'no noise cancellation', 'does not cancel noise', 'without noise cancellation', 'noise suppression not supported', 'does not support noise suppression', 'no denoising', 'without denoising', 'does not denoise audio', 'cannot suppress noise', 'never suppresses noise', 'no background noise removal', 'without background noise removal', 'does not remove background noise', 'cannot remove noise', 'no noise removal', 'does not remove noise', 'without noise removal', 'no audio denoising', 'does not denoise', 'cannot denoise audio')

import ast
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
from noise_suppression_claim_audit import phrases
from noise_suppression_claim_audit.audit import audit, claims, evidence, main, normalize


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = main([str(self.root), *args])
        return code, out.getvalue()

    def test_phrase_oracle(self):
        tree = ast.parse(Path(phrases.__file__).read_text())
        values = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)}
        self.assertEqual(tuple(map(normalize, values['NOISE'])), EXPECTED_NOISE)
        self.assertEqual(tuple(map(normalize, values['NONOISE'])), EXPECTED_NONOISE)
        self.assertEqual(len(EXPECTED_NOISE), 42)
        self.assertEqual(len(EXPECTED_NONOISE), 26)

    def test_good(self):
        self.put('README.md', 'noise suppression')
        self.put('app.py', 'x.reduce_noise(a)')
        self.assertEqual(self.cli(), (0, 'PASS\n'))

    def test_bad(self):
        self.put('README.md', 'noise suppression')
        self.put('app.py', 'pass')
        code, output = self.cli('--json')
        result = json.loads(output)
        self.assertEqual(code, 2)
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertEqual(result['findings'][0]['rule'], 'documented-noise-suppression-claim-false')
        self.assertEqual(result['findings'][0]['severity'], 'HIGH')
        self.assertTrue(result['findings'][0]['message'])

    def test_test_only(self):
        self.put('README.md', 'noise suppression')
        self.put('tests/check.py', 'x.remove_noise(a)')
        self.assertEqual(self.cli()[0], 0)
        self.assertIn('MEDIUM', self.cli()[1])
        self.assertEqual(self.cli('--fail-on', 'MEDIUM')[0], 2)

    def test_denial(self):
        self.put('README.md', 'does not suppress noise')
        self.put('app.py', 'x.suppress_noise(a)')
        result = audit(self.root)
        self.assertEqual(self.cli()[0], 2)
        self.assertEqual(result['findings'][0]['rule'], 'documented-no-noise-suppression-claim-false')
        self.assertEqual(result['findings'][0]['severity'], 'HIGH')
        self.assertEqual(len(result['findings']), 1)

    def test_no_claim(self):
        self.put('app.py', 'x.remove_noise(a)')
        self.assertEqual(audit(self.root)['verdict'], 'PASS')

    def test_no_source_positive(self):
        self.put('README.md', 'noise reduction')
        self.assertEqual(self.cli()[0], 2)

    def test_no_source_negative(self):
        self.put('README.md', 'no noise reduction')
        self.assertEqual(self.cli()[0], 0)

    def test_module_scope(self):
        self.put('README.md', 'noise suppression')
        self.put('a.py', 'from df.enhance import init_df')
        self.put('b.py', 'x.enhance(a)')
        self.assertEqual(self.cli()[0], 2)

    def test_symlink(self):
        self.put('README.md', 'noise suppression')
        with tempfile.TemporaryDirectory() as target:
            path = Path(target) / 'app.py'
            path.write_text('x.remove_noise(a)')
            (self.root / 'link.py').symlink_to(path)
            (self.root / 'linked').symlink_to(target, target_is_directory=True)
            self.assertEqual(self.cli()[0], 2)

    def test_docs_paths(self):
        self.put('nested/docs/guide.md', 'noise suppression')
        self.assertEqual(self.cli()[0], 2)
        self.assertEqual(self.cli('--ignore', 'nested')[0], 0)

    def test_other_markdown(self):
        self.put('other.md', 'noise suppression')
        self.assertEqual(self.cli()[0], 0)

    def test_ignore_prefix(self):
        self.put('README.md', 'noise suppression')
        self.put('vendor/app.py', 'x.remove_noise(a)')
        self.assertEqual(self.cli('--ignore', 'vendor')[0], 2)
        self.assertEqual(self.cli('--ignore', 'vend')[0], 0)

    def test_usage(self):
        for args in ([], ['--unknown'], [str(self.root), '--fail-on', 'WRONG']):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
                main(args)
            self.assertEqual(ctx.exception.code, 1)

    def test_bad_path(self):
        self.assertEqual(main([str(self.root / 'missing')]), 1)

    def test_io_error(self):
        with patch('os.walk', side_effect=PermissionError('denied')):
            self.assertEqual(self.cli()[0], 1)

    def test_unreadable(self):
        self.root.chmod(0)
        try:
            self.assertEqual(self.cli()[0], 1)
        finally:
            self.root.chmod(0o700)

    def test_version_module(self):
        proc = subprocess.run([sys.executable, '-m', 'noise_suppression_claim_audit', '--version'], capture_output=True, text=True)
        self.assertEqual((proc.returncode, proc.stdout.strip()), (0, '0.1.0'))

    def test_console_configuration(self):
        config = Path(__file__).resolve().parents[1] / 'pyproject.toml'
        self.assertIn('noise-suppression-claim-audit = "noise_suppression_claim_audit.audit:main"', config.read_text())

    def test_verbose(self):
        self.put('README.md', 'noise suppression')
        self.assertIn('README.md', self.cli('--verbose')[1])


def add_case(name, fn):
    setattr(AuditTests, 'test_' + name, fn)


POSITIVE = {
    'nr_attribute': 'noisereduce.reduce_noise(a)',
    'any_attribute': 'obj.reduce_noise(a)',
    'nr_import_name': 'import noisereduce as reduce_noise\nreduce_noise(a)',
    'nr_from': 'from noisereduce import reduce_noise\nreduce_noise(a)',
    'nr_alias': 'import noisereduce as nr\nnr.reduce_noise(a)',
    'nr_from_alias': 'from noisereduce import reduce_noise as clean\nclean(a)',
    'df_name': 'from df.enhance import enhance\nenhance(a)',
    'df_alias': 'from df.enhance import enhance as clean\nclean(a)',
    'df_attribute': 'import df.enhance\ndf.enhance.enhance(a)',
    'df_module_alias': 'import df.enhance as de\nde.enhance(a)',
    'df_any_import': 'from df.enhance import init_df\nx.enhance(a)',
    'suppress': 'x.suppress_noise(a)',
    'remove': 'x.remove_noise(a)',
}
NEGATIVE = {
    'bare_import': 'import noisereduce\nimport df.enhance\nimport rnnoise',
    'df_init': 'from df.enhance import init_df, load_audio, save_audio\ninit_df()\nload_audio(a)\nsave_audio(a)',
    'transcription': 'whisper.transcribe(a)\nr.recognize_google(a)\npipeline("automatic-speech-recognition")',
    'vad': 'vad.is_speech(a)\nget_speech_timestamps(a)',
    'diarization': 'pipeline("pyannote")\nx.diarize(a)',
    'verification': 'x.verify(a)\nx.identify(a)',
    'capture': 'microphone.open()\nstream.read(a)',
    'playback': 'audio.play(a)',
    'silence': 'pydub.detect_silence(a)\npydub.detect_nonsilent(a)\nlibrosa.effects.trim(a)',
    'separation': 'demucs.separate(a)\nspleeter.separate(a)',
    'filter': 'scipy.signal.wiener(a)\nx.highpass(a)\nx.lowpass(a)\nx.equalize(a)\nx.spectral_subtraction(a)',
    'volume': 'x.normalize(a)',
    'language': 'x.detect_language(a)',
    'generation': 'x.synthesize(a)\nx.generate(a)',
    'strings': 's = "noisereduce.reduce_noise(a)"',
    'subprocess': 'subprocess.run(["rnnoise", "audio.wav"])',
    'reference': 'import noisereduce\nnoisereduce.reduce_noise',
    'invalid': 'x.reduce_noise(a',
    'unresolved_name': 'reduce_noise(a)\nsuppress_noise(a)\nremove_noise(a)\nenhance(a)',
    'df_without_import': 'x.enhance(a)',
}
for key, source in POSITIVE.items():
    def check(self, source=source):
        self.assertTrue(evidence(source))
    add_case('evidence_' + key, check)
for key, source in NEGATIVE.items():
    def check(self, source=source):
        self.assertFalse(evidence(source))
    add_case('not_evidence_' + key, check)
for operation in ('reduce_noise', 'enhance', 'suppress_noise', 'remove_noise'):
    for kind in ('function', 'method', 'async'):
        def check(self, operation=operation, kind=kind):
            definition = 'def ' + operation + '(): pass'
            if kind == 'method':
                definition = 'class X:\n    ' + definition
            elif kind == 'async':
                definition = 'async ' + definition
            self.assertFalse(evidence('import df.enhance\n' + definition + '\nx.' + operation + '(a)'))
        add_case('shadow_' + operation + '_' + kind, check)
for location in ('tests/app.py', 'test_app.py', 'app_test.py', 'nested/tests/app.py', 'fixtures/app.py', 'docs/app.py', 'examples/app.py'):
    def check(self, location=location):
        self.put('README.md', 'noise suppression')
        self.put(location, 'x.remove_noise(a)')
        result = audit(self.root)
        self.assertEqual(result['findings'][0]['severity'], 'MEDIUM' if 'test' in location else 'HIGH')
    add_case('exclude_' + location.replace('/', '_').replace('.', '_'), check)
for index, (text, expected) in enumerate([
    ('```\nnoise suppression\n```', (False, False)),
    ('   ~~~~\nnoise suppression\n   ~~~~', (False, False)),
    ('`noise suppression`', (True, False)),
    ('does not suppress noise', (False, True)),
    ("doesn't suppress noise", (False, True)),
    ('NOISE-FREE   AUDIO', (True, False)),
    ('noise\nsuppression', (True, False)),
    ('noise\n\nsuppression', (False, False)),
    ('xnoise suppressionx', (False, False)),
    ('no noise suppression\n\nreduces noise', (True, True)),
    ('```\nnoise suppression', (False, False)),
    ('~~~\n```\nnoise suppression\n~~~', (False, False)),
]):
    def check(self, text=text, expected=expected):
        self.assertEqual(claims(text), expected)
    add_case('normalization_' + str(index), check)
