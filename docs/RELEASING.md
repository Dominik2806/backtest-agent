# Releasing

A release is a version bump and a CHANGELOG cut in one pull request, followed by a Git tag and a GitHub release.
Versions follow [Semantic Versioning](https://semver.org/): breaking change = major, new feature = minor, fix = patch.

## Where the version lives

Keep this list current; every place must show the same number after a release.

- `{{version-file}}` (`{{version-key}}`), the source of truth
- {{other places: package `__init__`, lock file, docs that name the current version}}
- Git tag `vX.Y.Z` (created after the merge)

## Steps

1. **Branch:** `git switch main; git pull; git switch -c chore/release-vX.Y.Z`
2. **Bump the version** in every place listed above. {{Regenerate the lock file if it contains the version.}}
3. **Cut the CHANGELOG.** In `CHANGELOG.md`:
   - rename the content of `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` and leave a new, empty `## [Unreleased]`
     above it;
   - merge duplicate `### Added`, `### Changed` and `### Fixed` headings into one each;
   - update the compare links at the bottom:

     ```markdown
     [Unreleased]: https://github.com/{{owner}}/{{repo}}/compare/vX.Y.Z...HEAD
     [X.Y.Z]: https://github.com/{{owner}}/{{repo}}/compare/vPREVIOUS...vX.Y.Z
     ```

     For the first release the link is `https://github.com/{{owner}}/{{repo}}/releases/tag/vX.Y.Z`.
4. **Reword stale text:** search README and `docs/` for sentences that call this version "upcoming" or "unreleased".
5. **Verify:** {{test-command}}, {{lint-command}}.
6. **Open the PR** titled `chore: release vX.Y.Z`. Squash-merge when CI is green and delete the branch.
7. **Tag and publish** from the merged `main`:

   ```bash
   git switch main && git pull
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   gh release create vX.Y.Z --title "vX.Y.Z" --notes-file release-notes.md
   ```

   Add `--prerelease` for versions below 1.0.0 if you want them marked. Do not commit `release-notes.md`.
8. **Check:** `gh release view vX.Y.Z` and open the compare link from the notes.

## Release notes template

Write the notes for readers, not as a copy of the CHANGELOG: lead with what matters, link the rest.

```markdown
## Highlights

{{vX.Y.Z is a feature / fix / maintenance release: one or two sentences on what it brings.}}

### Added

- **{{Feature}}**: {{what it does for the user}} (#{{pr}}).

### Changed

- {{Behaviour that changed, and what users must do about it.}}

### Fixed

- {{What was wrong and is fixed now}} (#{{pr}}).

### Breaking changes

{{Only for a major version: what breaks and how to migrate. Delete the section otherwise.}}

---

Changelog: https://github.com/{{owner}}/{{repo}}/blob/vX.Y.Z/CHANGELOG.md

**Full diff:** https://github.com/{{owner}}/{{repo}}/compare/vPREVIOUS...vX.Y.Z
```

## If something goes wrong

- **Wrong tag pushed:** `git push origin :refs/tags/vX.Y.Z`, `git tag -d vX.Y.Z`, `gh release delete vX.Y.Z`, then
  redo step 7. Only do this if nobody has used the release yet.
- **Bug found after release:** do not move the tag; fix it and release a patch version.
