# Releasing

## Every release

1. Set the new version in `src/iran_bourse_mcp/__init__.py` and `CITATION.cff`, add a section to `CHANGELOG.md`.
2. Regenerate what is generated: `scripts/gen_tools_doc.py`, `scripts/gen_screener_doc.py`, `scripts/gen_site_data.py`, `scripts/gen_readme.py` (see [CONTRIBUTING.md](../CONTRIBUTING.md)). CI fails if the tool and screener guides drift.
3. Merge to `main` with CI green, then create the release: `gh release create vX.Y.Z --target main --notes-file notes.md`.
4. The tag starts two workflows: **Publish container image** (ghcr.io) and **Publish to PyPI** (skipped until the one-time setup below is done).

## One-time PyPI setup (needs the maintainer's PyPI account)

The package name `iran-bourse-mcp` is free on PyPI, the build is checked (`uv build`, `twine check` both pass) and the workflow `.github/workflows/publish.yml` uses trusted publishing, so no token is stored anywhere.

1. Create a PyPI account with two-factor authentication.
2. Open <https://pypi.org/manage/account/publishing/> and add a **pending publisher** with exactly:
   - PyPI project name: `iran-bourse-mcp`
   - Owner: `msmahdinejad`, repository: `iran-bourse-mcp`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
3. In the GitHub repository, *Settings → Environments*, create an environment named `pypi` (optionally require yourself as reviewer).
4. In *Settings → Secrets and variables → Actions → Variables*, add `PUBLISH_PYPI` with the value `true`.
5. Publish the current version: *Actions → Publish to PyPI → Run workflow* on `main` (or push the next tag). Then check `uvx iran-bourse-mcp doctor` from a clean machine.
6. Make PyPI the default in the install snippets: set the default of `IRAN_BOURSE_SOURCE` to `pypi` in `src/iran_bourse_mcp/clients.py`, run `scripts/gen_readme.py` and `scripts/gen_site_data.py`, and replace the `git+https://...` commands in the README.
7. Submit to the MCP registry and directories (Smithery, Glama, PulseMCP).

The README on PyPI is rewritten at build time (`hatch-fancy-pypi-readme`) so its images and relative links point to the website and the repository.
