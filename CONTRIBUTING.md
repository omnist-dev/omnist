# Contributing

Omnist is **beta**: the public API is covered by the
[stability policy](docs/stability.md), so stable surfaces change only through
a deprecation cycle. The workflow below is the real one this project uses —
not a placeholder.

## Setup

```bash
git clone https://github.com/omnist-dev/omnist.git
cd omnist
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]      # core + all formats + pytest + ruff
```

## Workflow

Changes go through a pull request, not a direct push to `master`:

1. Create a branch: `git checkout -b <type>/<short-description>`, e.g.
   `fix/registry-thread-safety` or `docs/plugins-guide`. Prefixes in use:
   `fix`, `feat`, `docs`, `test`, `chore`, `ci`.
2. Make the change. Keep a PR to one coherent change set — a batch of
   doc fixes, one bug fix, one feature — not an unrelated grab-bag.
3. Before pushing, run both gates locally (CI runs the same two):
   ```bash
   ruff check .
   pytest -q
   ```
4. Push the branch and open a PR (`gh pr create`) describing the *intent*
   of the change, not just a restatement of the diff.
5. Branch protection on `master` requires the `test (3.11)` / `test (3.12)` /
   `test (3.13)` checks to pass (and the branch to be up to date) before
   merging. Squash-merge once green.

## Code style

- `ruff` is the source of truth (`pyproject.toml`'s `[tool.ruff]`); fix
  whatever it flags rather than arguing with it locally.
- This codebase uses `;`-joined one-liners and one-line class/def bodies in a
  few places (notably `osd.py`) — that's intentional (see the `E701`/`E702`
  ignores in `pyproject.toml`), not something to "clean up" in an unrelated PR.
- Type hints are enforced: CI runs `mypy --strict omnist` on every push
  and PR, and `omnist/py.typed` ships so callers' type checkers trust the
  package's hints. Run it locally before pushing.

## Tests

- Every new function or fixed bug gets a test. Tests that assert *errors* are
  raised matter as much as tests for the happy path — see
  `tests/test_canonical.py`'s `TestOsdRobustness` and `TestValidation` classes
  for the pattern: verify the actual exception type and message against the
  real code before writing the assertion, don't guess at what it "should" say.
- `examples/*.py` are documentation with executable code, not throwaway
  demos. `tests/test_examples.py` runs every one of them and will fail CI if
  any of them breaks — if you change something an example depends on (a
  function signature, example data referenced elsewhere in the docs), run the
  examples yourself before opening the PR, don't rely on CI to find it first.
- If you touch a doc's code block, run it. A doc claiming output that the
  code doesn't actually produce is worse than no example at all.

## Releases

Tags follow `v<version>` matching `pyproject.toml`'s `version`. This project
is pre-1.0 beta (`0.x`), so a version bump still marks "a meaningful batch of
work landed" rather than declaring the model final — but the public API is no
longer free to change silently: the [stability policy](docs/stability.md)
governs what a bump may change, and any break of a stable surface goes
through the deprecation cycle it describes (deprecate in one minor, remove no
earlier than the next). Bump the version, update `CHANGELOG.md` — noting any
deprecation — tag, and push the tag. See the README's Status section for the
current release plan.

## Reporting issues

<https://github.com/omnist-dev/omnist/issues>
