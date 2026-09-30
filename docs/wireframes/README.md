# Wireframes (low-fi, Phase 0)

ASCII wireframes of the seven screens in SPEC section 5, one file per screen, each with
notes on the primary action, loading / empty / error states, keyboard use and mobile.
Open **[index.html](index.html)** in a browser to see them all on one page (light and
dark, no external assets).

1. [My work](01-my-work.md)
2. [Project: Board and List](02-project-board-list.md)
3. [Idea page](03-idea-page.md)
4. [Evaluate sheet](04-evaluate-sheet.md)
5. [Proposal editor](05-proposal-editor.md)
6. [Submit idea (internal and public)](06-submit-idea.md)
7. [Settings (project and admin)](07-settings.md)

`index.html` is generated: edit the Markdown, then run
`python3 docs/wireframes/build_index.py` (standard library only; output is
deterministic). Keep each ASCII block's lines the same width so boxes line up.

These are for agreeing layout and behaviour, not visual design: the design system
(`/design` in the frontend) decides spacing, type and colour. Permissions shown here
follow [../role-matrix.md](../role-matrix.md).
