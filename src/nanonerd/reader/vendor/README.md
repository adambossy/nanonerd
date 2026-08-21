# Vendored browser bundles

## defuddle.js

- Package: [`defuddle`](https://www.npmjs.com/package/defuddle) 0.19.2
- Source file: `dist/index.full.js` from the npm tarball
  (`https://registry.npmjs.org/defuddle/-/defuddle-0.19.2.tgz`)
- Upstream: https://github.com/kepano/defuddle
- License: MIT (see `DEFUDDLE-LICENSE`)

The "full" bundle is a UMD build that assigns the `Defuddle` class to
`window.Defuddle`. It includes MathML/LaTeX conversion (temml +
mathml-to-latex), which the core bundle lacks. The server injects it into a
Playwright-rendered page and calls `new Defuddle(document, {url}).parse()`
(see `nanonerd/reader/defuddle.py`).

To upgrade: `npm pack defuddle@<version>`, copy `package/dist/index.full.js`
over `defuddle.js`, copy `package/LICENSE` over `DEFUDDLE-LICENSE`, and bump
the version above.
