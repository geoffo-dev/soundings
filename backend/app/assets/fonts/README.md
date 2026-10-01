# Bundled fonts for PDF exports

The proposal PDF (app/proposals, ADR 0011) uses only these files, which the renderer's
URL fetcher serves by name (`soundings-font:<name>`, see `app/proposals/fonts.py`);
nothing is downloaded and no system font name can stand in for them.

| Family | Files | Source | Licence |
|---|---|---|---|
| Inter | `inter-*` | npm `@fontsource/inter` 5.3.0 | SIL OFL 1.1 (`inter-LICENSE.txt`) |
| IBM Plex Sans | `ibm-plex-sans-*` | npm `@fontsource/ibm-plex-sans` 5.3.0 | SIL OFL 1.1 (`ibm-plex-sans-LICENSE.txt`) |
| Source Serif 4 | `source-serif-4-*` | npm `@fontsource/source-serif-4` 5.3.0 | SIL OFL 1.1 (`source-serif-4-LICENSE.txt`) |
| Atkinson Hyperlegible | `atkinson-hyperlegible-*` | npm `@fontsource/atkinson-hyperlegible` 5.3.0 | SIL OFL 1.1 (`atkinson-hyperlegible-LICENSE.txt`) |
| IBM Plex Mono (code) | `ibm-plex-mono-*` | npm `@fontsource/ibm-plex-mono` 5.3.0 | SIL OFL 1.1 (`ibm-plex-mono-LICENSE.txt`) |

Each branding font has the `latin` and `latin-ext` subsets (`woff2`) at 400, 600 and
700 (Atkinson Hyperlegible has no 600) plus 400 italic; IBM Plex Mono has 400. Glyphs
outside them (Greek, Cyrillic, symbols) fall back to DejaVu, which the image installs
(`fonts-dejavu-core`). To refresh: `npm pack @fontsource/<family>@<version>` and copy
`package/files/<family>-<subset>-<weight>-<style>.woff2` and `package/LICENSE`.
