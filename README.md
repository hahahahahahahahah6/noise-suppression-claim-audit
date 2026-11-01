# Documentation evidence auditor

An offline static audit tool for NS documentation claims and Python call evidence.
It reads root README.md and Markdown beneath docs directories, excluding fenced
blocks. Inline code counts. Python files are parsed without execution. Test
calls are tracked separately; fixtures, docs, examples and symbolic links are
excluded from evidence. Invalid Python provides no evidence.

## Install and run

```sh
pip install .
noise-suppression-claim-audit .
python3 -m noise_suppression_claim_audit . --json
python3 -m noise_suppression_claim_audit . --fail-on MEDIUM --verbose
python3 -m noise_suppression_claim_audit . --ignore vendor --ignore generated
```

Path prefixes are relative to the audited root. Findings have a rule, severity,
message and documentation locations. HIGH is the default failure threshold.
Exit codes are 0 for an audit below the threshold, 2 for a finding at or above
it, and 1 for usage or I/O errors. Version is 0.1.0. No network access or file
writes are performed by the auditor.

## Rules and examples

```text
documented-noise-suppression-claim-false: HIGH when a positive claim lacks production evidence
 documented-noise-suppression-claim-false: MEDIUM when evidence exists only in tests
documented-no-noise-suppression-claim-false: HIGH when a denial conflicts with production evidence

README.md: This tool provides noise suppression.
app.py: processor.suppress_noise(audio)
Result: PASS

README.md: This tool provides noise suppression.
app.py: print("hello")
Result: documented-noise-suppression-claim-false HIGH; exit 2
```

Matching uses normalized exact phrases and gives denial spans priority. Static
calls are evidence of implementation intent, not proof of runtime quality.
Imports and local definitions are resolved within each module; local functions
and methods shadow matching operation names throughout that module.

## Development

```sh
python3 -m unittest discover
python3 -m build
```

MIT licensed.
