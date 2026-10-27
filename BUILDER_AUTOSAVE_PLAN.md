# Builder autosave and safe saving: implementation plan

Status: Phases 0, 1 and 2 committed (2b07237). The switch is off; Phase 3 (rollout) is next.
The builder UX stages 1-2 (below) are committed (56fe6c4).

## Builder UX, stages 1-2 (built on top of autosave)

These apply whether or not the autosave switch is on.

- **No blank rows** on `/builder/` (the formsets have no extra empty forms); empty sections show their empty state.
- **Videos are cards** (`templates/dashboard/builder/_project_row.html`): thumbnail, title, format, link host,
  arrows and a drag handle; the fields fold underneath ("Edit").
  - A video needs its link **or** a title (`ProjectForm.clean`). A blank title is filled from the link when
    saved (`services.link_title`), and a video with a new link and no image gets the link's thumbnail after
    the save commits (`services.attach_link_thumbnail`).
  - "Paste a video link" box at the top of the Work panel (`_paste_link.html`); the card looks the link up
    through `welcome_preview_link` and fills in the title, format and thumbnail.
  - "Display size: Long Video / Short/Reel" is now "Format: Full video / Short / reel" (Arabic labels come
    through `ProjectForm(arabic=True)`, so the "add" template is translated too).
  - Order saves on its own through `POST /builder/api/projects/order/` (`ids` repeated).
- **Skills are chips** (`_skills_panel_body.html`, `_skill_row.html`): the launch checklist's presets plus
  "Your own"; every picked skill is still a formset row.
- **Links name themselves** from the URL (`services.platform_from_url`, mirrored in `BXLinks`); "Shown as" is optional.
- **Readiness card** (`_readiness.html`, video editors): the three client-ready items, each a shortcut to its
  field; when all three are done it offers "Copy your link" (live) or "Publish your portfolio".
- **Section order** for video editors: Work, About you, Skills, Links, Reviews; Experience, Education,
  Collaborators and Section layout fold under "More sections" while empty.
- **Copy:** "Preview" until the portfolio is live; "Save portfolio" instead of "Launch portfolio"; the sidebar
  tip matches autosave; "Collaborators" in the sidebar; with autosave, the last sections end with "Done — view my portfolio".
- Tests: `builder/test_cards.py`, `builder/js_tests/builder_cards_check.js` (run by `builder.test_autosave`),
  and more checks in the opt-in `builder/test_autosave_browser.py` (15 in all).

## Calm visual design (after stages 1-2)

The builder felt busy (a full-width readiness card, dashed borders everywhere, nine two-line nav items,
a "SECTION n" kicker and tinted band on every panel). The calm pass:

- One top bar (`templates/dashboard/builder/_topbar.html`): title, save state, Preview and **one** primary
  action: Publish (or Copy link once live). Without autosave, Save is primary and Publish is secondary.
- Client-readiness moved to the top of the sidebar as a small block (`_readiness.html`) that folds into
  "Ready to send to clients." once all three items are done.
- Sidebar: an icon and a name per section (icons are CSS masks keyed by `data-nav-key`), no numbers,
  descriptions or tip box; "More sections" is a text link.
- Panels: no kicker or tinted band, hairline borders, one spacing scale; dashed borders only on upload drop zones.
- Styles live in the "Calm builder" section at the end of `static/css/builder_v2.css` (it overrides older rules above it).

Phase 1 as built differs from the text below in two small ways:
- There is also a `builder_item_deleted` event (`kind`).
- On an update, a field the request didn't send that fails today's rules (saved under older ones) keeps its
  stored value instead of blocking the save. A field that was sent is always checked.

Phase 2 as built (`BXAutosave` in `static/js/builder_v2.js`, migration `core/0087`):
- A deleted row waits 6 s, not 5, to match how long the Undo toast stays up. Undo after the delete went out
  creates the row again.
- A value the server refused is held back until the user changes it, and the rest of the row is sent again
  without it, so it never blocks other fields.
- Editing a row that was deleted elsewhere (update returns 404) creates it again.
- Section layout changes save themselves without the "Layout saved" popup; the header pill reports them.
- The header shows "View live site" for every user when the switch is on (before, only on the update page).
- Tests: `builder/test_autosave.py` (switch + Node queue checks in `builder/js_tests/builder_autosave_check.js`)
  and the opt-in `builder/test_autosave_browser.py` (Playwright, 7 checks).

## Goal

Nobody loses work in the builder. Every change saves itself within about a second and the
user stays where they are. Saving never deletes something the user didn't delete.

Done means:

- Typing in any builder field persists after a reload, with no Save button pressed.
- A bad value in one field (e.g. a booking link) never blocks saving anything else.
- A chosen image is uploaded right away and is never lost to a failed save.
- A video, skill, link, etc. added from the launch pages, the AI agent or another tab survives a builder save.
- English and Arabic builders both get this (they share `static/js/builder_v2.js`).

## What happens today (the problems this fixes)

| Problem | Where |
|---|---|
| One POST validates 7 forms together. One bad field means nothing saves. | `builder/views.py:268-276`, `:442-450` |
| After a failed POST the page re-renders without the chosen files (browsers can't re-fill file inputs). | same branches, `templates/dashboard/builder.html` upload fields |
| Rows missing from the POST are deleted, so anything added elsewhere after the builder loaded is wiped. | `builder/views.py:761-763, 779-781, 802-804, 828-830, 844-846, 863-865` |
| Saving redirects away (preview or dashboard). | `builder/views.py:296`, `:469` |
| Section layout has its own AJAX save, which the submit has to flush first. | `static/js/builder_v2.js:456-477` |

## Decisions (recommended defaults, change before building if you disagree)

1. **Ship behind a switch.** `SiteSettings.builder_autosave_enabled`, default **off**, same pattern as
   `launch_checklist_enabled`. Off = today's form (with the Phase 0 fix). On = autosave.
2. **Save per item, per changed field.** The client sends only the fields that changed; the server merges
   them onto the stored row. Last write wins per field. No version numbers (the agent and the launch pages
   don't edit the same field at the same moment in practice).
3. **Deleting waits 5 seconds** behind the existing Undo toast, then is sent. A pending delete is flushed
   on `pagehide` with `fetch(..., {keepalive: true})`. Undo cancels the request; nothing is re-created.
4. **Keep the full-form POST as the no-JS fallback.** After Phase 0 it is safe, so it can stay.
5. **The Save buttons go away when autosave is on.** The header shows a save-status pill and
   "View portfolio". The "Launch portfolio" wording goes (it never published anything).

---

## Phase 0: stop the data loss (ship first, ~half a day, no switch)

This is safe on its own and fixes the worst bug even if nothing else ships.

**`builder/views.py` `save_portfolio_data`** (`:689`)
- Collect `deleted_ids` per formset: forms whose `cleaned_data` has `DELETE=True` and an `id`.
- Delete only those ids (still scoped with `user=request.user`).
- Rows that weren't submitted at all are left alone.
- Drop the `existing_map` sweep loops listed in the table above.
- Edge: a DELETE row with no id (a new row the user removed) is simply skipped, as today.

**Tests (`builder/tests.py`, `SavePortfolioDataTests`)**
- Change `test_removed_projects_are_deleted` to send the row with `DELETE=on`.
- Add: a project created after the builder loaded (not in the POST) survives the save. Repeat for skills,
  education, experience, links and creators (one loop test).
- Add: a DELETE row with another user's id deletes nothing.
- Run `manage.py test builder core.test_activation core.test_launch`.

---

## Phase 1: per-item save API (server, ~2 days)

### Endpoints (`builder/urls.py`, new `builder/api.py`)

All are `POST`, `@login_required`, multipart `FormData` (so files and CSRF work the same way as the
existing category AJAX). All look rows up with `get_object_or_404(Model, pk=pk, user=request.user)`.

| Route | Does |
|---|---|
| `builder/api/personal/` | Update personal info (any subset of fields) and/or `picture` |
| `builder/api/<kind>/` | Create one row |
| `builder/api/<kind>/<int:pk>/` | Update one row (subset of fields, optional image) |
| `builder/api/<kind>/<int:pk>/delete/` | Delete one row |

`kind` is one of `skills`, `education`, `experience`, `projects`, `links`, `creators`.

### One set of rules for both save paths (`builder/services.py`, new)

Pull the per-model logic out of `save_portfolio_data` so the legacy POST and the API share it:

- `KINDS = {kind: (Model, FormClass, initial_from_instance, fields_from_cleaned)}`.
- `initial_from_instance`: the per-row dicts that `_portfolio_initial_data` (`views.py:570`) builds today.
- `fields_from_cleaned`: the model-field mapping currently inline in `save_portfolio_data`
  (e.g. education `year` → `grade_year`, experience `start`/`end` parsing, project `category_id` lookup,
  "keep the old image if no new one").
- Partial update = `initial_from_instance(row)` overlaid with the posted fields, bound to the existing form
  class (`ProjectForm(user=...)` keeps its collection-ownership check), `is_valid()`, then save.
- `save_portfolio_data` becomes a loop over `KINDS` that calls the same helpers.

### Images

- Run uploads through `core.launch.clean_thumbnail` (Pillow-checked format, 5 MB cap, generated file name)
  for project thumbnails, creator images and the profile picture.
- A refused image returns a field error and changes nothing else on the row.

### Responses

- Success: `{"ok": true, "id": 12, "item": {...saved values...}}`. On the user's first project, also
  `"reveal_url"` (from `onboarding.reveal_url`), replacing the redirect in `_first_project_redirect`.
- Validation: HTTP 400 `{"ok": false, "errors": {"<form field name>": ["message"]}}`. Field names match the
  form's, so the client can find `[name$="-<field>"]`.
- Arabic: the client sends `lang=ar`; errors come back in Arabic (reuse `ProjectForm.INVALID_CATEGORY_ERROR_AR`
  and `launch.FIELD_ERRORS` where they fit; add Arabic text for the remaining form messages).

### Side effects to keep (one `_after_write(request, kind, created)` helper)

- Run saves inside `activation.source('builder')`.
- `_track_profile_fields_added` for personal-info changes.
- Make sure a `UserPayment` row exists (end of `save_portfolio_data` today).
- Set `is_public` if the latest payment is active (today's behaviour on every save).
- New activation events `builder_item_saved` (`kind`, `created`) and `builder_item_save_failed`
  (`kind`, `fields`, `reason`). Register them in `core/activation.py:20`.
- The launch checklist needs nothing: its progress is read from the portfolio itself, so a skill or video
  saved here still finishes it.

### Tests (`builder/test_api.py`, new; use `core.testing_helpers.make_editor` to keep them fast)

- Create, update and delete for each kind; the row has the right values afterwards.
- A partial update leaves the other fields unchanged.
- Another user's row returns 404 for update and delete.
- An invalid value returns 400 with the field name; nothing is saved.
- Image: a non-image or a file over 5 MB is refused; a valid one is stored under a generated name.
- First project returns `reveal_url`; the second doesn't.
- The events fire with the right properties.
- Arabic errors come back in Arabic.

---

## Phase 2: autosave in the builder page (client, ~3 days)

Everything lives in `static/js/builder_v2.js`, so one change covers `builder.html` and
`arabic_builder_v2.html`. The template only adds `data-autosave="1"` on `#builder-root` when the switch is on;
otherwise the JS keeps today's behaviour.

### A save queue per row (`BXAutosave`)

- Each `.bx-item` gets `data-kind`; its id is read from and written to its hidden `-id` input.
  The identity panel counts as one row of kind `personal`.
- Per row: the set of changed fields, a debounce timer, a promise chain so requests for one row never
  overlap, and a status (`saved`, `pending`, `saving`, `error`, `draft`).
- **Triggers:** text input saves 800 ms after typing stops. Blur, `<select>`, collection chips
  (`selectChip`, `:781`) and file choice save immediately.
- **New rows:** stay `draft` until their required fields pass `checkValidity()`, then one create request.
  Edits made while the create is in flight wait in the chain and go out as an update with the new id.
  This prevents duplicate rows.
- **Errors:**
  - 400: show the messages in the row's existing `.bx-field-error` elements (reuse `validateField`'s markup).
  - Network or 5xx: retry after 1 s, 3 s, 9 s, then show "Couldn't save · Retry".
  - 401/403 (signed out): keep everything on the page and show "You were signed out. Sign in again to save."

### Deleting

- `removeItem` (`:628`) keeps its hide-and-Undo toast and schedules the delete request for 5 s later.
- Undo cancels it. Leaving the page sends pending deletes with `keepalive`.

### Files

- If the row has an id, the image is uploaded the moment it is chosen, with a spinner on the preview.
- If it doesn't, the image goes with the create request.

### What the user sees

- Header: a status pill ("Saving…" / "All changes saved" / "1 change didn't save · Retry") and "View portfolio".
- Removed when autosave is on:
  - the header and panel-footer Save buttons
  - the unsaved-changes bar (`builder.html:898`)
  - the saving overlay
  - the layout flush in `handleSubmit` (`:456-477`)
- A `<noscript>` Save button stays for the no-JS fallback.
- `beforeunload` (`:246`) warns only while something is pending, saving, failed, or a draft row has content.
- Section layout: save changes automatically (debounced) through the existing `BXSectionOrder.save`, and
  report into the same status pill.
- On the first video, show a toast with a link to `reveal_url` instead of redirecting.
- New strings go into `BX_I18N` (`:1`) and the Arabic `window.BuilderI18n` in `arabic_builder_v2.html`.

### Tests

- **Queue logic in Node:** `builder/js_tests/` already holds a Node check run by a Django test
  (`builder_progress_check.js`). Add one for debounce, per-row serialisation, create-then-update and retry.
- **Opt-in browser test** (`builder/test_builder_browser.py`, `SKILLIFLY_BROWSER_TESTS=1`, Playwright with
  `channel='chromium'`). Each checks the result after a reload:
  - type a title, reload: it's still there
  - add a video
  - remove a skill and Undo: still there
  - remove a link and wait: gone
  - upload a thumbnail
  - a bad booking link shows its error while other fields still save
  - the Arabic builder saves a field

---

## Phase 3: rollout and measurement (~half a day)

1. Turn the switch on in dev, run the browser test, then turn it on in production.
2. Compare before and after:
   - `builder_save_failed` per builder session, against `builder_item_save_failed` per session
   - time from signup to first project
   - share of sessions that leave with unsaved work (now `beforeunload` warnings)
3. After about two weeks with no regressions, delete the old JS paths (savebar, overlay, submit flush).
   Keep the server POST as the no-JS fallback.

## Out of scope

- **Reordering projects inside the builder** (still on `customize_projects`). That's part of recommendation #3.
- **Order of new videos.** They still get `order=0`, so a new video shows at the top of the builder but
  after older `order=0` videos on the portfolio. Unchanged from today.
- **Version history / multi-step undo.** `agent/tools.py` snapshots could provide this later.
