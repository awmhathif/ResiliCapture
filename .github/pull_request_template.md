## What changed?

Describe the user-visible or reliability change.

## Recording-safety checklist

- [ ] I did not make finalization failure delete recoverable source chunks.
- [ ] I did not report success before the final output is verified.
- [ ] I considered crash/interruption behavior for changed session state.
- [ ] I added/updated tests for the changed behavior.
- [ ] `python -m unittest discover -s tests -v` passes locally (or I explained why it cannot be run).

## Testing

List Windows/Python/encoder combinations tested and any relevant logs/diagnostics.
