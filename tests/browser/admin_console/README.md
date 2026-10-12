# Optional admin-console browser proof

This local proof runs the real admin-console factory, templates, CSS and shipped
scripts over loopback HTTP. Its upstream is a **test-only simulated service**.
It is optional and is not collected by pytest or installed as a new CI job.
The Python dependency/lock files are unchanged.

## Run

Requirements: the repository's locked Python environment (`uv sync --locked`),
Node.js, curl, an optional Playwright Node package and a compatible Chromium
executable. The reviewed run used Node.js 24.19.0, Playwright 1.62.1 and Chromium
141.0.7390.37 (Playwright Chromium build 1194, headless shell). Package/browser
installation belongs to a disposable directory, outside the repository.

If Playwright and its downloaded Chromium are already available:

```bash
ADMIN_BROWSER_PLAYWRIGHT_MODULE=/absolute/path/to/node_modules/playwright \
  bash tests/browser/admin_console/run.sh
```

To choose a separately installed Chromium:

```bash
ADMIN_BROWSER_PLAYWRIGHT_MODULE=/absolute/path/to/node_modules/playwright \
ADMIN_BROWSER_EXECUTABLE=/absolute/path/to/headless_shell \
  bash tests/browser/admin_console/run.sh
```

Without `ADMIN_BROWSER_PLAYWRIGHT_MODULE`, Node resolves `playwright` normally.
Without `ADMIN_BROWSER_EXECUTABLE`, Playwright resolves its installed Chromium.
For an optional transient installation, run:

```bash
npm install --prefix /your/temp/path playwright@1.62.1
/your/temp/path/node_modules/.bin/playwright install chromium
```
Missing tooling fails visibly; the proof never reports a skipped run as passed.

The launcher works from any directory, binds only to `127.0.0.1`, starts a fresh
private session directory, and removes it on exit. `ADMIN_BROWSER_PORT` selects
the loopback port (default `18422`). `ADMIN_BROWSER_ARTIFACTS` selects the output
directory (default `.ci/admin-visual`, ignored by Git). Screenshots, a sanitized
server log and `verification.json` remain there after the fixture stops.
Only synthetic fixture credentials/proofs are used; supply no real credentials.

## Protected behavior and falsifiers

- Desktop at 1440 × 1080 and mobile at 320 × 900 have no whole-page overflow.
- The mobile drawer traps keyboard focus, returns focus on Escape and makes the
  main content inert. With JavaScript disabled, navigation remains available.
- A mutating HTMX form cancels without a POST, confirms exactly one POST, supplies
  Origin and CSRF, and restores its submit button after completion.
- Personal security and owner enrollment render through the actual factory.
  Private submit buttons stay disabled without JavaScript.
- Enrollment uses fetch, clears the password/proof after an aborted network
  request, and retains the GET address. Reload does not repeat the POST.
- Recovery-code replacement has one confirmation mechanism: Cancel sends zero
  POSTs and Confirm sends one. Reload hides the one-time fixture code and does
  not issue another set.
- Browser JavaScript errors fail the proof.
- Nested visual controls add and remove rows, retain an explicit No value, and
  disable nested required controls when Clear value is selected. Each row edit
  changes the draft's idempotency intent. Requests contain the surviving row and
  explicit null mode, rather than a removed row or disabled child.
- Time values retain microseconds (`09:00:00.123456`) and an explicit offset
  (`09:00:00+03:00`) in text controls because native HTML time inputs silently
  clear those values. Milliseconds (`09:00:00.123`) use a native time control with
  no whole-second step restriction and pass actual browser validity checks. The submitted
  request retains all three values exactly.
- First-business creation uses the canonical platform schema and a named account
  picker. The picker starts blank, creation links the returned business and Party,
  and the continuation reaches the guided setup page. New editor and setup pages
  are captured at desktop/mobile widths and checked for whole-page overflow.
- Without JavaScript, nested controls explain that adding entries and enabling
  optional groups needs JavaScript; account choices remain usable and unselected.

These assertions remain executable proof requirements. The October 12 initial
download returned HTML instead of a browser archive; an alternative official
Playwright CDN subsequently supplied Chromium 141.0.7390.37. The launcher passed
with Playwright 1.62.1 at desktop 1440×1080 and mobile 320×900, with no JavaScript
errors or whole-page overflow. Ten screenshots and the result were produced in
the ignored `.ci/admin-visual` evidence directory.

That run crossed the test checkpoint from `c64678d5` to `f8c984cd`.
The complete production and browser-fixture Git trees were identical in both;
only three other test files received typing fixes. The recorded result therefore
proves those unchanged UI/fixture bytes, rather than falsely claiming the entire
run occurred on a single commit. Later revisions need their own execution proof.

Removing the drawer focus handling, private-form fetch interception, secret-input
clearing, default-disabled private buttons or cancellation guard makes the
corresponding assertion fail. Expected outcomes are observed in the browser and
its network requests, rather than computed by the production helper.

## Evidence boundary

This is bounded browser/component evidence with an explicitly excluded upstream.
The fixture imports application code to expose the real UI; it is **not** a
black-box system/E2E runner and does not belong to the reusable Docker suite
registry. It proves no database durability, authorization policy, live provider
acceptance, real WebAuthn ceremony, clean Docker installation or production
readiness. Existing HTTP, PostgreSQL and Docker lanes retain ownership of those
claims. The test-only synthetic OpenAPI operation exists to exercise generic UI
interactions and is never mounted by production entrypoints.
