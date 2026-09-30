# 6. Submit idea (internal and public)

Internal: a dialog opened with `N`, "New idea" or the palette · `idea.create`.
Public: a branded page at `/{project}/submit` · `public.submit` (only when the project
enables it) · SPEC 5, screen 6, and SPEC 10.

## Internal (dialog over any page)

```
+------------------------------------------------------------+
| New idea                                               [x] |
|------------------------------------------------------------|
| Project      [ Customer Innovation                     v ] |
|                                                            |
| Title        [ Print-free returns with a QR code         ] |
|              A short name people will recognise.           |
|                                                            |
| Summary      [ One or two sentences: what and why        ] |
|                                                            |
| Description  [Write | Preview]                  optional   |
|              +-------------------------------------------+ |
|              | Markdown. Who is it for? What changes?    | |
|              +-------------------------------------------+ |
|                                                            |
| Tags         [ returns x ] [ logistics x ] [ + tag       ] |
|------------------------------------------------------------|
|                         [ Cancel ]   [## Submit idea ##]   |
+------------------------------------------------------------+
```

## Public (branded page, 1440 px)

```
+------------------------------------------------------------------------------+
|                          [Acme logo]  Acme Ideas                             |
|                                                                              |
|                  Share an idea with our Customer team                        |
|         We read every idea. You'll get a private link to follow it.          |
|                                                                              |
|   Title          [                                                    ]      |
|   Summary        [                                                    ]      |
|   Description    [                                                    ]      |
|                  [                                          optional  ]      |
|                                                                              |
|   Your name      [                    ]  optional                            |
|   Your email     [                    ]  optional, for updates               |
|                  [x] Email me when the status changes                        |
|                                                                              |
|   [v] Verified you're human (runs in your browser, no puzzle)                |
|                                                                              |
|                         [####### Send idea #######]                          |
|                                                                              |
|          Privacy: we store only what you enter here. Powered by Soundings    |
+------------------------------------------------------------------------------+
```

## Public confirmation

```
+------------------------------------------------------------------------------+
|                          [Acme logo]  Acme Ideas                             |
|                                                                              |
|                   Thanks! Your idea "Print-free returns" is in.              |
|                                                                              |
|   Keep this private link to see its status:                                  |
|   [ https://ideas.acme.example/t/5pX...Qe                    ] [## Copy ##]  |
|   We've also emailed it to you. (Check your inbox to confirm your address.)  |
+------------------------------------------------------------------------------+
```

## Mobile (390 px), public

```
+--------------------------------------+
|        [logo] Acme Ideas             |
| Share an idea                        |
| Title                                |
| [                                  ] |
| Summary                              |
| [                                  ] |
| Description (optional)               |
| [                                  ] |
| Email (optional)                     |
| [                                  ] |
| [v] Verified you're human            |
| [########## Send idea ###########]   |
+--------------------------------------+
```

## Notes

- **Primary action:** "Submit idea" (internal) / "Send idea" (public).
- **Fields:** only title and summary are required. Limits are shown as you approach
  them, not up front. The project picker is preselected from context and hidden when
  there's only one project you can submit to.
- **After internal submit:** the dialog closes, the new idea opens, and a toast says
  "CUST-22 created" with "Copy link". The draft is kept in the dialog if you close it
  by accident (per-browser, not synced).
- **Public anti-abuse:** a hidden honeypot field, a per-IP rate limit (proxy-aware),
  and the ALTCHA proof-of-work widget, which solves itself in the background and
  works offline. Optional email verification and moderation (the idea stays hidden
  until an admin approves it). Name and email are optional and erasable by admins.
- **Branding:** the public page uses the project's (or global) logo, colours and font;
  it shows nothing about the project beyond its name and intro, even for private
  projects.
- **Loading:** the internal dialog opens instantly; the tag picker loads lazily. The
  public page is small and server-light; the ALTCHA challenge loads with it.
- **Empty:** not applicable. Public submission disabled: 404 page "This form isn't
  available" (no hint whether the project exists).
- **Errors:** field errors inline, focus moves to the first; rate-limited: "You've
  sent several ideas in a short time. Try again in a few minutes."; verification
  failed: "We couldn't verify this browser. Retry".
- **Keyboard:** `N` opens the dialog anywhere; `⌘Enter` submits; `Esc` closes (asks
  only if there's unsaved text). Labels are visible, not placeholders.
- **Mobile:** single column, large fields, sticky submit on the internal dialog
  (which becomes a full-screen sheet).
