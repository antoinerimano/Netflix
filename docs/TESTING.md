# Tests

**90 automated tests** protect the app: 39 backend, 29 frontend, 22 end-to-end. GitHub runs
all of them on every pull request and again on `main` after a merge (`.github/workflows/ci-cd.yml`).
`main` is protected: nothing is merged, and nothing is deployed, unless the three test jobs pass.

| Suite | Count | Where | What it runs on |
|---|---|---|---|
| Backend (Django) | 39 | `backend/users/tests.py`, `backend/users/test_i18n.py`, `backend/reco/tests.py` | the real API, a real MySQL 8 database built from the migrations |
| Frontend (Jest) | 29 | `frontend/src/**/*.test.js` | app modules and components in a simulated browser (jsdom) |
| End-to-end (Playwright) | 22 | `e2e/tests/*.spec.js` | the whole app (production build + Django + MySQL) in a real Chromium, driven with the keyboard like a TV remote |

Unit tests check one piece in isolation; integration tests go through the API and the database;
end-to-end tests check what a user does, from the first page to the last click.

---

## Running them

| What | Command | Needs |
|---|---|---|
| Backend | `cd backend && python manage.py test` | MySQL running (the test database `test_<DB_NAME>` is created and deleted) |
| Frontend | `cd frontend && npm test -- --watchAll=false` | `npm ci` once |
| Translations | `cd frontend && npm run i18n:check` | |
| Production build | `cd frontend && npm run build` (the CI sets `CI=true`: a warning fails it) | |
| End-to-end | `cd e2e && npm test` (watch it: `npm run test:headed`, report: `npm run report`) | MySQL running, `npm ci && npx playwright install chromium` once |

The end-to-end suite starts its own servers on ports 8101 / 3101 and its own database,
`taurus_e2e`, emptied and refilled at every run by `manage.py e2e_prepare` (it refuses any
database whose name doesn't contain `e2e`, so it can't touch the dev or production data).

---

## What runs on GitHub, and when

| Job | Steps | Time |
|---|---|---|
| **Backend** | Django system checks · no model change without its migration (`makemigrations --check`) · translation files compile (`msgfmt --check`) · 39 tests | ~1 min 30 |
| **Frontend** | translations check · 29 tests · production build, warnings fail it | ~1 min 10 |
| **End-to-end** | starts MySQL, the backend and the production frontend · 22 tests in Chromium · on failure: screenshots, videos and traces kept 14 days (Actions → the run → Artifacts) | ~4 min |
| **Deploy** | only on `main`, only when the three jobs passed and `DEPLOY_ENABLED` is set | |

A failing end-to-end test is retried once on GitHub. A test that fails twice is a real failure;
one that passes on its retry shows as "flaky" and deserves a look.

---

## Backend tests (39)

### Security and permissions: `backend/users/tests.py`, `PermissionTests` (13)

| Test | Verifies |
|---|---|
| `test_register_cannot_grant_admin` | signing up with `is_staff` / `is_superuser` in the request doesn't make an admin; the password is stored hashed and never returned |
| `test_login_still_works` | a correct email and password sign in; the answer never contains the password |
| `test_user_list_scoped_to_self` | a user only sees their own account in the user list, and gets 404 on someone else's |
| `test_admin_sees_all_users` | an admin sees every account |
| `test_user_cannot_edit_own_privileges` | a user can't make themselves staff by editing their account |
| `test_nested_routes_require_auth` | profiles, subscriptions and payment history need to be signed in (401) |
| `test_nested_routes_blocked_for_other_users` | someone else's profiles / subscriptions / payments can't be read, and their profile can't be deleted (403) |
| `test_owner_can_use_nested_routes` | the account owner can create profiles and subscriptions, and read their payments; a profile always belongs to the account in the URL, whatever the request says |
| `test_payment_history_is_read_only` | payment history can't be written through the API |
| `test_subscribe_other_user_blocked` | nobody can subscribe another account |
| `test_subscribe_ignores_client_billing_fields` | price, currency and transaction id come from the server, never from the request |
| `test_logout_without_access_token` | signing out with a bad token gets a clear 400, not a crash |
| `test_titles_public_read` | the catalog can be read |

### Sign-in hardening: `AuthHardeningTests` (6)

| Test | Verifies |
|---|---|
| `test_login_same_error_for_unknown_email_and_wrong_password` | the same answer for an unknown email and a wrong password: sign-in can't be used to find out who has an account |
| `test_inactive_user_cannot_login` | a deactivated account can't sign in |
| `test_password_reset_same_answer_for_unknown_email` | password reset answers the same for any email, and only sends an email to real accounts |
| `test_password_reset_rejects_weak_password` | a reset link refuses a weak password and accepts a strong one |
| `test_login_is_rate_limited` | the 11th sign-in attempt in a minute is refused (429): no password guessing |
| `test_password_reset_is_rate_limited` | the 6th reset request in an hour is refused (429): no email flooding |

### Performance guards: `QueryCountTests` (2)

| Test | Verifies |
|---|---|
| `test_title_list_constant_queries` | the catalog list takes exactly 2 database queries, however many titles (no "N+1" slowdown) |
| `test_title_detail_constant_queries` | a show's page (seasons, episodes, cast) takes exactly 5 queries, however big the show |

### Recommendations: `backend/reco/tests.py` (5)

| Test | Verifies |
|---|---|
| `test_impressions_only_logged_for_own_profiles` | viewing statistics are only recorded for the user's own profiles |
| `test_impressions_batch_size_is_capped` | more than 500 events at once are refused (no flooding) |
| `test_action_on_other_users_profile_rejected` | likes / list actions can't be recorded on someone else's profile |
| `test_action_on_own_profile_logged` | they are recorded on your own |
| `test_public_endpoints` | catalog, genres, search and actors all answer (catches a broken import or URL) |

### Languages: `backend/users/test_i18n.py` (13)

| Test | Verifies |
|---|---|
| `LanguageCodeTests.test_codes` | language codes are understood whatever their form (`fr-CA` → French, `jp` → Japanese, `pt-BR` → Portuguese, `zh-Hans` → Chinese), unsupported ones (`ko`) are ignored |
| `EveryLanguageTests.test_every_app_language_has_its_messages` | every app language has its translated server messages: a language added without them fails here |
| `CatalogTextsTests.test_four_byte_characters_are_stored` | emoji and rare characters from TMDB are stored (regression: the translation sync crashed on them) |
| `CatalogTextsTests.test_payload_walker` | titles, synopses, episode names and notification show names are swapped for their translation; untranslated texts stay in English |
| `CatalogTextsTests.test_api_serves_the_request_language` | the API answers a show page in French when asked in French, in English otherwise, in English when no translation exists |
| `CatalogTextsTests.test_editing_tools_get_the_stored_texts` | the admin tools get the original English texts, so a translation can never be saved over them |
| `CatalogTextsTests.test_response_varies_on_language` | answers say which language they are in, so caches never mix languages |
| `MessagesTests.test_register_errors_are_translated_with_a_stable_code` | an error comes in the user's language, with a fixed code the app relies on (`email_taken`) |
| `MessagesTests.test_password_rules_in_the_request_language` | password rules are explained in the user's language |
| `MessagesTests.test_reset_email_in_the_request_language` | the password reset email (subject, text, HTML) is in the user's language |
| `MessagesTests.test_profile_language_is_normalized` | a profile language is saved in one standard form (`jp` → `ja`) |
| `SearchTests.test_translated_name_and_reason_shape` | search finds a title by its translated name ("Le Parrain" → The Godfather) and says why it matched |
| `SearchTests.test_typo_fallback_runs` | a misspelled search works (regression: the typo-tolerant pass crashed) |

---

## Frontend tests (29)

### TV remote navigation: `frontend/src/tv/spatialNavigation.test.js` (7)

| Test | Verifies |
|---|---|
| arrows move to the nearest element in that direction | Up / Down / Left / Right reach the right element |
| the first arrow starts on the page main action that is on screen | the remote starts on what the user sees (Play), not on something scrolled away |
| up from the page reaches the banner before the fixed navbar | the navbar is reached from the top of the page, not from the middle of a row |
| up / down ignore an element on the same line | Up doesn't jump sideways to a button that is a few pixels higher |
| a closed select never changes its value with the arrows | arrows on a dropdown (the language picker) don't change it by accident |
| the focus continues next to an element that went away | when the focused button disappears, the remote continues from the nearest element instead of getting lost |
| an open dialog keeps the remote inside it | in a dialog, the arrows can't reach the page behind it |

### Player remote control: `frontend/src/components/watch/playerRemote.test.js` (4)

| Test | Verifies |
|---|---|
| only players with a documented API are driven by the remote | CineSrc is recognized; the other players aren't sent commands they don't understand |
| in full screen OK toggles play / pause and arrows seek / change the volume | the exact messages sent to CineSrc for OK, ◀ ▶ and ▲ ▼ |
| outside full screen the arrows still move around the page | the remote keeps navigating the page when the player isn't full screen |
| players without an API get no commands | nothing is sent to the other players |

### Languages and formatting: `frontend/src/i18n/i18n.test.js` (16)

| Test | Verifies |
|---|---|
| `normalizeLanguage` (8 cases) | browser and profile language codes map to app languages (`fr-CA`, `jp`, `zh-TW`, `pt-BR`…); unknown ones give nothing |
| every supported code normalizes to itself | the list of languages is consistent |
| switching language loads its texts and updates `<html lang>` | a language's texts load when chosen, the page declares its language, plurals follow the language ("1 saison", "3 saisons") |
| every supported language has its own texts | each of the 11 languages really has its texts: a language added to the list without them fails here |
| unsupported languages are ignored | an unknown language leaves the app in English |
| formatting follows the language | durations, decimal numbers (`7,3` in French), language names and "Yesterday" are written the local way |
| row titles | home row titles are written in the app's language from the server's data |
| card reasons fall back to the English sentence only in English | "Similar to Heat"-type reasons are translated; an old English one never shows in another language |
| search reasons | "With Bryan Cranston" / "Crime · 1990s · Series" are written from the server's data |

### Sign-in page: `frontend/src/components/Login.test.js` (2)

| Test | Verifies |
|---|---|
| links to sign up | the "Create an account" link is there and goes to `/register` (regression: it rendered empty) |
| is translated | the page and the link appear in French |

---

## End-to-end tests (22)

The whole app in Chromium. Outside services are replaced: the video players by a stand-in that
speaks CineSrc's API, images and fonts are blocked. The tests never depend on another website.
Test data: 8 movies, 1 show with 2 seasons, French translations, one account with three
profiles (Alex in English, Camille in French, Kids), see `backend/users/management/commands/e2e_prepare.py`.

### Signing in: `e2e/tests/auth.spec.js` (5)

| Test | Verifies |
|---|---|
| sign in, choose a profile, land on the home page | the full way in: email + password → "Who's watching?" → home with its banner and rows |
| a wrong password says so and stays on the page | the error is shown, nobody gets in |
| the sign-in page links to sign up | the link works and opens the sign-up page |
| signed out pages can change language | the language picker switches the page to French, Hindi and Russian (three alphabets) |
| pages need a signed-in user | the home page sends a signed-out visitor to sign in |

### TV remote: `e2e/tests/tv-remote.spec.js` (6, at 1280 × 720, a common TV size)

| Test | Verifies |
|---|---|
| home: banner, rows, back up to the banner, never lost | Down lands on Play, then the first card; Right moves along the row; Up from the right side of the row reaches the banner (not the navbar); the focus is never lost |
| OK opens a title, Back returns to the card it came from | OK opens the title page; Back comes back to the exact card |
| holding OK on a card opens its options, Back closes them | a long press opens the options without also pressing Play; Back closes them and returns to the card |
| the profile menu keeps the remote inside, Back closes it | the arrows stay in the menu; Back closes it and returns to its button |
| arrows never change the language picker by themselves | pressing Down on the language picker doesn't switch the app's language |
| browse page: grid, sticky filter bar, filters dialog | the poster grid, up to the filters and the search box, the Filters dialog keeps the remote inside, Back closes it |

### Watching: `e2e/tests/watch.spec.js` (6)

| Test | Verifies |
|---|---|
| movie: details, Watch, the player loads the first source | the title page shows its information; Watch opens the player with the right video link |
| show: seasons and episodes, an episode opens the player on it | seasons switch; an episode opens the player on that season and episode |
| switching source changes the player | choosing another source loads that player with the right link |
| OK on the player never traps the remote in it | after OK on the player (full screen or not), the remote always comes back to the app, never stuck inside the player |
| CineSrc: the remote drives the player, the focus stays in the app | Play / Pause reach the CineSrc player as commands; the focus never leaves the app |
| Back on the player returns to the title | Back leaves the player for the title's page |

### Languages, search and lists: `e2e/tests/i18n-search.spec.js` (5)

| Test | Verifies |
|---|---|
| a French profile gets the app and the catalog in French | interface, page title, French titles and synopses; searching "Parrain" finds "Le Parrain" |
| switching to an English profile switches the app back | the language follows the profile chosen |
| search: by title, typo tolerant, with a reason | a title search, a misspelled search ("interstelar"), and a search with no results |
| browse filters by genre | the Animation genre only shows animated titles |
| my list: add from the details, find it in My List | adding to My List works and stays added even when the server's answer arrives late (regression: the button turned back to "Add"), and the title is on the My List page |

---

## Other automatic checks

| Check | Fails when |
|---|---|
| `npm run i18n:check` | a language misses a text, a plural form its grammar needs, a `{{placeholder}}` or a `<tag>`; a key used in the code doesn't exist; a translation uses a tag name that can't hold text (`<link>`) |
| `makemigrations --check` | a model changed without its database migration |
| `msgfmt --check` | a backend translation file is broken |
| production build with `CI=true` | the frontend has a compile error or a code warning |
| Dependabot (monthly) | proposes dependency updates as pull requests; they run all of the above before they can be merged |

---

## Not covered

- **Real TVs.** The remote tests use a keyboard in Chromium. TV browsers (Tizen, webOS, Android TV) and their Back keys aren't tested; the full-screen exit inside an external player depends on them.
- **The real video players** (Videasy, VidFast, VidSrc...): they are replaced by a stand-in. Their availability is checked by `manage.py check_providers` on the server, not by the tests.
- **TMDB.** The catalog and translation syncs aren't tested against TMDB itself.
- **Admin pages, account settings, the avatar builder, notifications, the email change flow:** no end-to-end test yet.
- **Looks.** Tests check what is shown and where the focus goes, not colors or pixel layouts (except the row size caught through card positions).
- **Arabic / Urdu** (right to left): not supported yet.

## Adding a test

- **New feature:** an end-to-end test of what a user does with it, in the matching file of `e2e/tests/`.
- **Bug fixed:** a test that fails without the fix, then passes with it. Check it really fails by putting the bug back once.
- **Backend rule** (permission, validation, API answer): a Django test next to the others.
- **New language:** add it to `SUPPORTED_LANGUAGES` (frontend) and `APP_LANGUAGES` (backend), its files in `frontend/src/i18n/locales/<lang>` and `backend/locale/<lang>`; the "every language" tests and `i18n:check` tell what is missing.
