# 7. Settings (project and admin)

Project settings: `/p/{project}/settings` · project admins and platform admins.
Admin settings: `/admin` · platform admins. Personal settings (profile, notification
preferences, API keys): `/me`. SPEC 5, screen 7. Plain forms, sensible defaults, no
sprawl: each page is one short form with one Save.

## Project settings: Rubric (1440 px)

```
+------------------------+-------------------------------------------------------------------+
| (sidebar)              | Customer Innovation / Settings                                    |
|                        |                                                                   |
|                        | General | Members | [Rubric] | Statuses | Public form | Branding  |
|                        |-------------------------------------------------------------------|
|                        | Rubric                                                            |
|                        | 3 to 6 criteria. Weights are relative. Inverted: lower is better. |
|                        |                                                                   |
|                        | ::  Value          [How much does it help customers or us?]       |
|                        |                    Weight [ 3 ]  [ ] Inverted  [Guidance v]  [..] |
|                        | ::  Feasibility    [Can we build and run it?              ]       |
|                        |                    Weight [ 2 ]  [ ] Inverted  [Guidance v]  [..] |
|                        | ::  Effort         [How much work is it?                  ]       |
|                        |                    Weight [ 2 ]  [x] Inverted  [Guidance v]  [..] |
|                        | ::  Strategic fit  [Does it fit where we're going?        ]       |
|                        |                    Weight [ 2 ]  [ ] Inverted  [Guidance v]  [..] |
|                        | ::  Risk           [What could go wrong?                  ]       |
|                        |                    Weight [ 1 ]  [x] Inverted  [Guidance v]  [..] |
|                        | [+ Add criterion]                                                 |
|                        |                                                                   |
|                        | Changing the rubric recalculates scores for all ideas.            |
|                        |                                [ Discard ]  [## Save rubric ##]   |
+------------------------+-------------------------------------------------------------------+
```

## Project settings: Members

```
+------------------------------------------------------------------------------------------+
| Members          [ Add people or groups...        ] [Member v]  [## Add ##]              |
|------------------------------------------------------------------------------------------|
| (A) Alice Anders   alice@example.com         [Admin v]                 [Remove]          |
| (B) Bob Brown      bob@example.com           [Member v]                [Remove]          |
| [G] /innovation/members (group, 14 people)   [Member v]                [Remove]          |
| (C) Carol Chen     via /innovation/members   Member (edit the group, not her)            |
+------------------------------------------------------------------------------------------+
```

## Admin settings: Email (1440 px)

```
+------------------------+-------------------------------------------------------------------+
| Admin                  | Email (SMTP)                                   Status: Working    |
|   Users                |                                                                   |
|   Groups               | These values come from the Helm release; change them there.       |
|   Sign-in (SSO)        |   Host       smtp.example.com       Port      587                 |
| > Email                |   Security   STARTTLS               Timeout   10 s                |
|   Branding             |   From       Soundings <ideas@example.com>                        |
|   API keys             |   Reply-to   --                     Username  soundings           |
|   Agents               |   Password   ********  (Secret soundings-smtp)                    |
|   Audit log            |   CA bundle  custom (1 certificate)                               |
|                        |                                                                   |
|                        | Send a test email to [ alice@example.com    ] [## Send test ##]   |
|                        |                                                                   |
|                        | Failed sends  2                                                   |
|                        |  bob@example.com   "You've been asked to evaluate..."             |
|                        |      8 attempts - 535 authentication failed - 2 h    [ Retry ]    |
+------------------------+-------------------------------------------------------------------+
```

## Mobile (390 px)

```
+--------------------------------------+
| <  Settings                          |
| [ Rubric                         v ] |
|--------------------------------------|
| Value                           [..] |
| [How much does it help us?       ]   |
| Weight [3]   [ ] Inverted            |
|--------------------------------------|
| Feasibility                     [..] |
| ...                                  |
+--------------------------------------+
| [ Discard ]    [### Save rubric ###] |
+--------------------------------------+
```

## Pages and what's on them

- **Project:** General (name, description, visibility private/internal, volunteer
  owners on/off, evaluation window in days, archive); Members (people and groups with
  a role; group-derived members are read-only here); Rubric; Statuses (rename the five
  labels, with a live preview of the board header); Public form (on/off, moderation,
  email verification, intro text, link to copy); Branding (optional override of the
  global branding, live preview).
- **Admin:** Users (pre-create, external IDs, deactivate, sign-out everywhere);
  Groups (IdP mappings, managed/additive, "Test mapping" box); Sign-in (effective OIDC
  config, login matching, break-glass status); Email (effective SMTP config, test,
  failed sends); Branding (global, live preview); API keys (all keys, revoke);
  Agents (registered kagent agents, purpose, service account); Audit log.
- **Me:** profile, notification preferences per type (immediate / daily digest /
  off), personal API keys (name, scopes, expiry, project restriction; the key is shown
  once).

## Notes

- **Primary action:** Save on each form (disabled-looking only while nothing changed;
  it still explains "No changes" if pressed). "Send test" on Email; "Add" on Members.
- **Defaults:** every setting has a working default; a fresh project needs only a name.
  Settings that come from Helm (SMTP, OIDC) are shown read-only with where to change
  them.
- **Destructive-ish actions** (remove member, archive project, revoke key) apply at
  once with an Undo toast, except those that can't be undone (erase submitter data,
  delete a key's secret), which confirm in a dialog that names the thing.
- **Loading:** the form skeleton matches the final layout; no layout jump.
- **Empty:** no members besides you: "Add people or a group to start collaborating."
  No failed sends: "All emails delivered." No API keys: "Create a key to use the API
  or connect an MCP client."
- **Errors:** field errors inline; save failure keeps the form dirty with a banner.
  SMTP test failure shows the server's reply (e.g. "535 authentication failed") and
  what to check.
- **Keyboard:** tabs are a proper tablist (`←`/`→`); rubric rows reorder with the
  drag handle or `Alt+↑`/`Alt+↓`; `⌘S` saves the current form.
- **Mobile:** the tab row becomes a page picker; forms are single column; Save is a
  sticky footer.
