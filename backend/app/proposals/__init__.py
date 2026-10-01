"""Proposals (SPEC sections 2 and 5, screen 5; docs/api/contract-phase4.md 3.1-3.4).

* :mod:`.service`: start a proposal over the fixed template, read it, save a section
  with optimistic concurrency, and the permission flags;
* :mod:`.comments`: margin comment threads anchored to a section;
* :mod:`.markdown`: proposal Markdown as the SPA renders it (raw HTML dropped, images
  as links, headings demoted through the parser, bounded tables);
* :mod:`.export`: the Markdown and PDF exports (shared content, limits, filenames);
* :mod:`.pdf`: the PDF renderer, WeasyPrint in a separate process with a hard time
  limit and a URL fetcher that answers only bundled fonts and ``data:`` URIs.

This package's ``__init__`` stays import-free: the PDF child process imports
:mod:`.pdf` and nothing else of the application.
"""
