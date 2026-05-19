# Omni-Localizer Release Checklist

## Prerequisites
- PyPI account (https://pypi.org/account/register/)
- PyPI API token (https://pypi.org/manage/account/#api-tokens)
- twine installed: `pip install twine`
- build installed: `pip install build`

## Pre-Release Steps

1. **Update version**
   - [ ] Bump version in pyproject.toml (line 3: `version = "X.Y.Z"`)
   - [ ] Bump version in src/ol_cli.py (line 16: `__version__ = "X.Y.Z"`)

2. **Update CHANGELOG.md**
   - [ ] Add new version section with date
   - [ ] Document all changes since last release
   - [ ] Remove "[Unreleased]" placeholder

3. **Verify dependencies**
   - [ ] Check hypomnema requires Python >=3.13
   - [ ] Ensure requires-python matches dependency constraints

4. **Run tests**
   - [ ] `pytest tests/` - all should pass
   - [ ] `ruff check src/` - no errors

5. **Clean build**
   - [ ] `rm -rf dist/`
   - [ ] `python -m build`
   - [ ] Verify wheel contents with `unzip -l dist/*.whl`

6. **Test installation from wheel**
   - [ ] `pip install dist/*.whl --force-reinstall`
   - [ ] `ol --version` - should show new version
   - [ ] `ol --help` - should work

## Release Steps

1. **Create git tag**
   ```bash
   git add -A
   git commit -m "Release vX.Y.Z"
   git tag vX.Y.Z
   git push origin main --tags
   ```

2. **Upload to PyPI**
   ```bash
   twine upload dist/*
   ```
   - Use PyPI API token when prompted
   - Or set `TWINE_PASSWORD` environment variable with token

3. **Verify on PyPI**
   - [ ] Visit https://pypi.org/project/omni-localizer/
   - [ ] Verify version number, description, license
   - [ ] Check download stats update

## Post-Release

- [ ] Monitor for installation issues
   ```bash
   pip install omni-localizer==X.Y.Z
   ol --version
   ```
- [ ] Announce release (if applicable)

## Rollback (if needed)

If something goes wrong:
```bash
# DO NOT delete releases from PyPI - you cannot reuse the same version
# Instead, bump to next patch version and re-upload
```

## Notes

- Python >=3.13 required (due to hypomnema dependency)
- Entry point: `ol = "ol_cli:main_entry"` (in pyproject.toml)
- Package name on PyPI: `omni-localizer` (hyphenated)
- CLI command: `ol` (from entry point)
