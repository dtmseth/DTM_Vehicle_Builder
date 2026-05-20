# Versioning

DTM Vehicle Builder follows [Semantic Versioning](https://semver.org/) using `MAJOR.MINOR.PATCH`.

## What To Bump

- `patch`: Backward-compatible bug fixes only.
- `minor`: Backward-compatible new functionality or substantial UI/workflow improvements.
- `major`: Backward-incompatible changes to project files, drafts, config schemas, command behavior, or any workflow users already rely on.

For this desktop app, the public surface is more than Python imports. Treat saved project/draft/config formats, CLI commands, installer behavior, and user workflows as part of the compatibility promise.

Adding the project management UI is a `minor` release: it adds substantial backward-compatible functionality, so `1.0.4` becomes `1.1.0`.

## Release Flow

Use the GitHub Actions `Build` workflow manually when you want to publish a release:

1. Open Actions -> Build -> Run workflow.
2. Choose `current`, `patch`, `minor`, or `major`.
3. Use `current` when `pyproject.toml` already has the release version you want.
4. Use `patch`, `minor`, or `major` when the workflow should bump `pyproject.toml` for you.
5. The workflow tags `vX.Y.Z`, builds Mac and Windows artifacts, and publishes the release.

Normal pushes to `main` build artifacts for validation, but they do not bump versions or publish releases.

If a release was renamed without changing the tag or app metadata, delete the incorrect release/tag in GitHub first, then run the workflow with `current`. The workflow refuses to publish when the target tag already points at a different commit.

## Local Checks

The app version lives in `pyproject.toml`. Packaging reads from that single source:

- The in-app footer uses the installed package version.
- The macOS app bundle writes `CFBundleShortVersionString` and `CFBundleVersion`.
- The Windows installer receives `AppVersion`.
- The Windows executable receives file/product version metadata.
