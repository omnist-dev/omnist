# Stability and versioning

## Status: beta

Omnist is in beta. The model is settled and the API has stopped churning, so it's safe to build real things on. But it isn't frozen. Pin your version, and read the [changelog](../CHANGELOG.md) before you upgrade.

The beta bargain, plainly: breaking changes are still possible, but they're no longer casual. They never happen in a patch release, they're always called out in the changelog, and where a clean migration path exists, the old behaviour is deprecated first rather than removed outright.

## What counts as public API

The stability rules below apply to:

- Everything exported from the top-level `omnist` package (its `__all__`).
- The `omnist` command-line interface: documented commands, their flags, exit codes, and `--json` output shape.
- The **OSD** and **OML** text formats, as described in the [schema](schema.md) and [format](formats/oml.md) docs.
- The format-plugin interface -- `Format` and `register_format`.

## What is *not* public

These can change at any time, without notice:

- Anything named with a leading underscore.
- Internal submodules such as `omnist.ops.*`. Import from the top-level `omnist` package only.
- The `tools/` directory (test oracle and the like).
- The exact wording of error messages. The *structured* error data -- each error's `path` and `code` -- is public and stable; the human-readable message text is not.

## Versioning during beta (0.x)

- **Patch** (`0.5.1 -> 0.5.2`): additive features and fixes only. A patch never breaks a working program or a previously valid file.
- **Minor** (`0.5.x -> 0.6.0`): may contain a breaking change. When it does, the change is listed under a **Breaking** heading in the changelog, and -- when a migration path is practical -- the previous minor release will have emitted a `DeprecationWarning` for the old behaviour first.

Every version published to PyPI is meant to work; there are no pre-release or nightly tags to avoid.

## Deprecations

When something is on its way out, it emits a `DeprecationWarning`, gets a changelog note explaining the replacement, and stays for at least one more minor release before removal. During beta, if a deprecation path genuinely isn't practical, the change may land directly -- but always announced in the changelog, never silently.

## On-disk formats (OSD and OML)

The `.osd` and `.oml` files you write are data, and breaking them is more serious than breaking code. During beta, readers stay backward-compatible with previously valid files wherever feasible, and grammar changes are additive by default. A breaking grammar change is treated as a breaking change under the rules above.

## Supported Python

Omnist supports actively-maintained CPython releases (currently 3.11 through 3.14). Dropping a version is a breaking change, announced in the changelog.

## The road to 1.0

1.0 is where beta's "may break in a minor release" hardens into the usual promise: no breaking changes without a major version bump. It's a stabilization-and-usage milestone, not a design one -- the model is already decided. We'll cut 1.0 once the public API has gone a stretch of releases without needing to break, real-world use hasn't surfaced a reason to reshape it, and no deprecations are pending. Until then: beta.
