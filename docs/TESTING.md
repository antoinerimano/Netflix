# Tests

**207 automated tests** protect the app: 104 backend, 63 frontend, 40 end-to-end. GitHub runs
all of them on every pull request and again on `main` after a merge (`.github/workflows/ci-cd.yml`).
`main` is protected: nothing is merged, and nothing is deployed, unless the three test jobs pass.

| Suite | Count | Where | What it runs on |
|---|---|---|---|
| Backend (Django) | 104 | `backend/users/tests.py`, `backend/users/test_i18n.py`, `backend/users/test_seo.py`, `backend/reco/tests.py`, `backend/reco/test_imports.py`, `backend/reco/test_calendar.py`, `backend/reco/test_history.py`, `backend/reco/test_stats.py`, `backend/reco/test_collections.py`, `backend/reco/test_lists.py` | the real API, a real MySQL 8 database built from the migrations |
| Frontend (Vitest) | 63 | `frontend/src/**/*.test.{js,jsx}` | app modules and components in a simulated browser (jsdom) |
| End-to-end (Playwright) | 40 | `e2e/tests/*.spec.js` | the whole app (production build + Django + MySQL) in a real Chromium, driven with the keyboard like a TV remote |

Unit tests check one piece in isolation; integration tests go through the API and the database;
end-to-end tests check what a user does, from the first page to the last click.

---

## Running them

| What | Command | Needs |
|---|---|---|
| Backend | `cd backend && python manage.py test` | MySQL running (the test database `test_<DB_NAME>` is created and deleted) |
| Frontend | `cd frontend && npm test` (re-runs on save: `npm run test:watch`) | `npm ci` once |
| Lint | `cd frontend && npm run lint` (a warning fails it) | |
| Translations | `cd frontend && npm run i18n:check` | |
| Production build | `cd frontend && npm run build` (Vite, then `scripts/obfuscate.js`) | |
| End-to-end | `cd e2e && npm test` (watch it: `npm run test:headed`, report: `npm run report`) | MySQL running, `npm ci && npx playwright install chromium` once |

The end-to-end suite starts its own servers on ports 8101 / 3101 and its own database,
`taurus_e2e`, emptied and refilled at every run by `manage.py e2e_prepare` (it refuses any
database whose name doesn't contain `e2e`, so it can't touch the dev or production data).

---

## What runs on GitHub, and when

| Job | Steps | Time |
|---|---|---|
| **Backend** | Django system checks · no model change without its migration (`makemigrations --check`) · translation files compile (`msgfmt --check`) · 104 tests | ~1 min 30 |
| **Frontend** | translations check · lint (warnings fail it) · 63 tests · production build | ~1 min 10 |
| **End-to-end** | starts MySQL, the backend and the production frontend · 40 tests in Chromium · on failure: screenshots, videos and traces kept 14 days (Actions → the run → Artifacts) | ~4 min |
| **Deploy** | only on `main`, only when the three jobs passed and `DEPLOY_ENABLED` is set | |

A failing end-to-end test is retried once on GitHub. A test that fails twice is a real failure;
one that passes on its retry shows as "flaky" and deserves a look.

---

## Backend tests (104)

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

### Recommendations: `backend/reco/tests.py` (12)

| Test | Verifies |
|---|---|
| `test_impressions_only_logged_for_own_profiles` | viewing statistics are only recorded for the user's own profiles |
| `test_impressions_batch_size_is_capped` | more than 500 events at once are refused (no flooding) |
| `test_action_on_other_users_profile_rejected` | likes / list actions can't be recorded on someone else's profile |
| `test_action_on_own_profile_logged` | they are recorded on your own |
| `test_public_endpoints` | catalog, genres, search and actors all answer (catches a broken import or URL) |
| `test_choices_are_known_titles_spread_over_genres` | "What do you like to watch?" offers well-known titles with a poster, a different genre for each of the first ones, some in the profile's language |
| `test_kids_profile_only_gets_titles_for_its_age` | a kids profile is only offered titles for its age |
| `test_other_users_profile_is_refused` | nobody can see or save the picks of someone else's profile |
| `test_picks_become_likes_and_the_home_is_rebuilt` | picks are saved as likes (unknown ids ignored), the home page is rebuilt at once, picked titles aren't offered again |
| `test_bad_bodies_are_refused` | missing, empty, non-numeric or more than 50 picks are refused |
| `test_an_empty_rebuild_never_replaces_the_home_page` | a rebuilt home page with nothing in it (everything already seen) keeps the page the profile had |
| `test_home_says_when_the_profile_has_no_taste_yet` | the home page tells the app to offer the picker until the profile likes something |

### Lists and sharing them: `backend/reco/test_lists.py` (8)

| Test | Verifies |
|---|---|
| `test_create_list_add_remove_and_read` | a list made with its first title (name tidied, private, a 10-letter share id), adding twice adds once, titles in the order added, covers, removing |
| `test_lists_say_which_contain_a_title` | the lists say which ones hold a given title (the "Add to a list" checks) |
| `test_rename_describe_delete_and_bad_names` | rename, description cut at 300, an empty name refused, delete |
| `test_limits` | 50 lists per profile, 500 titles per list |
| `test_private_until_shared_then_anyone_can_read_it` | a private list's public address is a 404; shared, anyone signed out sees its name, author and titles |
| `test_save_a_copy` | another account saves a private copy, titles in the same order |
| `test_other_accounts_and_kids` | another account can't read or change a list; a kids profile's view of its list follows its age |
| `test_shared_list_page_for_search_engines_and_previews` | `/l/<id>`: 404 while private; shared: its title, "author: titles" description, first poster, `ItemList` data |

### Franchises in watch order: `backend/reco/test_collections.py` (6)

| Test | Verifies |
|---|---|
| `test_collection_id_follows_the_json` | `Title.collection_id` is set from `belongs_to_collection` on save, also with `update_fields` |
| `test_parts_in_release_order_with_what_was_watched_and_whats_next` | parts in release order (announced ones last, "upcoming"), numbered, watched from the history, the next one to watch, name and artwork |
| `test_played_or_imported_counts_as_watched` | Play pressed, Continue watching and imported "watched" count; nothing next when only an announced part is left |
| `test_unknown_collection_age_limit_and_other_accounts` | unknown collection, a kids profile that may see none of it, another account: 404 |
| `test_home_row_offers_the_next_part_of_started_franchises` | "Next in your collections": the next part of each started franchise, the latest watched first, "Part 3 of ..." under it |
| `test_no_row_when_nothing_started_or_everything_seen` | no row when no franchise was started, or all of it was seen |

### Your year: `backend/reco/test_stats.py` (7)

| Test | Verifies |
|---|---|
| `test_the_year_in_numbers` | time from runtimes (movie, episode, else the show's usual length, else 100 / 45 min), titles / movies / shows / episodes / days, minutes per month, the longest streak with its dates, the first title; years with history |
| `test_genres_share_the_time_and_add_up` | a title's time is split between its genres; the shares add up to 100% |
| `test_top_titles_and_lead_actors` | most watched titles by time (with their episode count); actors among the five first-billed only, most titles first, with their photo |
| `test_default_year_is_the_latest_with_history` | without a year: the latest one with history |
| `test_streaks` | longest and current streaks (a gap breaks the current one) |
| `test_kids_age_and_other_accounts` | a kids profile's numbers follow its age limit; another account's are refused |
| `test_no_history` | no history: zeros, no streak, the current year |

### Watch history: `backend/reco/test_history.py` (8)

| Test | Verifies |
|---|---|
| `test_opening_the_player_writes_one_entry_per_episode_and_day` | the watch page writes one entry per movie / episode per day (again the same day: the same entry), newest first, episodes with their name |
| `test_pages_of_fifty` | 50 entries per page, then the next page |
| `test_removing_the_last_entry_of_a_title_forgets_it` | removing an entry keeps the title's signals while another entry is left; removing the last one also clears Continue watching, Play / open signals, its sources and its "Because you watched" row; likes stay |
| `test_clear_all` | Clear history empties it and Continue watching |
| `test_paused_history_saves_nothing_about_watching` | paused: no entry, no Continue watching, no Play / open signal, no impression, no source result (a like still counts); back on, it records again |
| `test_export_csv` | the CSV file: header, a movie line and an episode line with its name |
| `test_kids_profile_list_respects_its_age_and_others_are_refused` | a kids profile's list follows its age limit; nobody reads or removes another account's history |
| `test_backfill_from_what_was_recorded_before` | the migration builds the first history from Continue watching (with the episode) and Play presses (one per title and day) |

### Upcoming episodes: `backend/reco/test_calendar.py` (5)

| Test | Verifies |
|---|---|
| `test_your_shows_recent_and_upcoming` | followed, listed and watched shows count (follow wins as the reason); this week's episodes newest first, today and the next 30 days soonest first; specials, older and further episodes left out |
| `test_suggestions_are_popular_shows_coming_back_that_arent_tracked` | "Coming back soon": popular shows with an episode coming, not already tracked, with their next episode |
| `test_kids_profile_only_sees_its_age` | a kids profile doesn't see shows above its age, nor get them suggested |
| `test_someone_elses_profile_is_refused` | nobody can read another account's calendar |
| `test_the_sync_refreshes_tracked_shows_that_still_air` | the episode sync also refreshes the shows people track, not ended ones |

### History import: `backend/reco/test_imports.py` (8)

| Test | Verifies |
|---|---|
| `test_letterboxd_files_become_likes_dislikes_watched_and_my_list` | Letterboxd ratings / watchlist / hearts: 3.5 stars or more and hearts are likes, 2 or less dislikes, the rest watched, the watchlist goes to My List; matched by name + year (a same-name film from another year isn't), unknown titles reported; the home page is rebuilt |
| `test_dates_are_kept` | likes and watched titles keep their date from the export, not the import day |
| `test_letterboxd_zip_export` | the Letterboxd .zip works as is; its deleted/ folder and non-film files are ignored |
| `test_imdb_ratings_match_by_imdb_id_and_skip_episodes` | IMDb ratings match by IMDb id, shows included, single episodes skipped |
| `test_what_the_profile_did_here_wins` | an import never changes a thumb or My List entry made in the app |
| `test_importing_twice_adds_nothing_twice` | the same file twice adds nothing the second time (and doesn't rebuild the home page) |
| `test_unknown_or_missing_files_are_refused` | no file, or a file that isn't a Letterboxd / IMDb export, is refused with a reason |
| `test_other_users_profile_is_refused` | nobody can import into someone else's profile |

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

### Search engines and link previews: `backend/users/test_seo.py` (16)

What `users/seo.py` answers for the app's pages (nginx sends it every URL that isn't a file) and the sitemaps.

| Test | Verifies |
|---|---|
| `test_movie_page_has_its_own_tags` | a movie page has its own title, description, canonical link and preview image, the home page's ones are gone, the app's scripts are still there, the HTML is never cached |
| `test_hreflang_for_every_language` | links to the page in each of the 11 languages (`?lng=fr`...) + `x-default` |
| `test_translated_page` | `?lng=fr` gives the French title and synopsis, `<html lang="fr">`, `fr_FR` previews |
| `test_json_ld` | structured data (Movie: name, director, genres, rating) for search results |
| `test_show_page_and_canonical_follows_type` | a show opened as `/movies/<id>` points search engines at `/tv/<id>` |
| `test_text_is_escaped` | a title containing HTML can't inject anything into the page |
| `test_missing_title_is_404` | an unknown title answers 404 + `noindex` (the app still shows its "Page not found") |
| `test_actor_page` | an actor page has the actor's name, photo and a translated description; an unknown actor is a 404 |
| `test_translated_fallback_description` | a title without synopsis gets a description in the page's language |
| `test_app_routes_200_unknown_404` | every app route answers 200; made-up addresses (`/wp-login.php`) answer 404 instead of a page that looks real |
| `test_every_app_route_is_known` | every `<Route path>` of `frontend/src/App.jsx` answers 200 from Django (regression: `/taste`, `/import`, `/calendar`, `/history`, `/stats`, `/collection/…` were 404 + noindex on a reload or an opened link) |
| `test_api_404_stays_json` | unknown API addresses are not turned into app pages |
| `test_index_and_sections`, `test_unknown_parts_404`, `test_split_into_files` | `/sitemap.xml` lists the parts; each part lists its movies / shows / actors once; parts split at 40,000 addresses |
| `test_revalidates_and_survives_outage` | `index.html` is re-checked with the frontend on every page (a deploy shows at once) and the last copy is used if the frontend is briefly down |

---

## Frontend tests (63)

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

### Player events: `frontend/src/components/watch/playerEvents.test.js` (16)

What each video player's messages mean (`watch/playerEvents.js`): they drive the progress bar, "Continue watching" and smart playback.

| Test | Verifies |
|---|---|
| Videasy (6) | progress / duration / playing / paused / completed / episode, messages sent as text or as objects, empty numbers aren't read as 0 |
| CineSrc (3) | time updates, play / pause / ended / next episode; unknown events ignored |
| VidCore and others (2) | VidCore's text messages; anything else posted to the page (ads, extensions) is ignored |
| URLs (2) | a bare domain gets `https://`; `.mp4` / `.m3u8` files play in the page's own player |
| saved preferences and the address (3) | the saved source is per profile and title; old saved sources still work; `?season=` / `?episode=` / `?t=` only accept positive numbers |

### Tab title: `frontend/src/utils/pageTitle.test.jsx` (2)

| Test | Verifies |
|---|---|
| sets "<name> \| Tauruss" and restores the app title on leaving | a movie / show / actor page names the browser tab and history entry; leaving it gives back the app's title |
| nothing while the name is still loading | no empty "| Tauruss" title while the page loads |

### Sign-in page: `frontend/src/components/Login.test.jsx` (2)

| Test | Verifies |
|---|---|
| links to sign up | the "Create an account" link is there and goes to `/register` (regression: it rendered empty) |
| is translated | the page and the link appear in French |

### Taste picker: `frontend/src/components/profiles/TastePage.test.jsx` (2)

| Test | Verifies |
|---|---|
| Continue waits for enough picks, then saves them and opens the home page | Continue stays off until 3 titles are picked (picking again unpicks), then the picks are sent and the home page opens |
| Skip goes home without saving | Skip saves nothing |

### Add to a list: `frontend/src/components/lists/ListPicker.test.jsx` (2)

| Test | Verifies |
|---|---|
| toggles the title in a list, the focus starts on the first list | checks where the title is, OK adds it (count and toast), the focus lands on the first list once they arrive |
| a new list starts with the title; an empty name is refused | "Give the list a name.", then the new list, checked |

### Collection page: `frontend/src/components/collection/CollectionPage.test.jsx` (3)

| Test | Verifies |
|---|---|
| half watched: what comes next, checks, coming soon | the name, "Collection · 3 movies", the progress meter, "Watch next: ...", each part's number / title / year / state for screen readers |
| nothing watched: start with the first one; all seen: no button | "Start with ...", then "All watched" and no button |
| a collection that does not exist | "Collection not found" |

### Your year page: `frontend/src/components/stats/StatsPage.test.jsx` (2)

| Test | Verifies |
|---|---|
| the year in numbers, genres scaled to the top one, switching year | "About 10 hours", streak, top titles with episodes and time, actors with titles; genre bars scaled to the top one with the share as text; a value on the busiest month only; a year chip loads that year |
| nothing watched yet | the empty state, no share button |

### Watch history page: `frontend/src/components/history/HistoryPage.test.jsx` (2)

| Test | Verifies |
|---|---|
| entries by day, episodes with their name, download | Today / Yesterday / a date, "S1 · E2 · <name>" for episodes, a remove button per entry, Download asks for the CSV |
| paused and empty: says nothing is saved | a paused, empty history says so; the switch shows it; Clear is off |

### Upcoming page: `frontend/src/components/calendar/CalendarPage.test.jsx` (3)

| Test | Verifies |
|---|---|
| days, the week row, and where an episode leads | rows titled Today / Tomorrow / the date with "In N days", the week's episodes in their own row; an episode out today opens the player on it |
| an episode still to come opens the show | an upcoming episode opens the show's page |
| a calendar that could not load offers to try again | the error is shown with "Try again" |

### History import page: `frontend/src/components/import/ImportPage.test.jsx` (2)

| Test | Verifies |
|---|---|
| a file import: summary, focus on "Go to your home page", titles not found on demand | the summary appears with the focus on "Go to your home page"; the titles not found show on demand |
| Letterboxd first, IMDb a press away, an unreadable file is explained | Letterboxd is selected first, IMDb can be chosen; a file that isn't an export gets a clear message |

---

## End-to-end tests (40)

The whole app in Chromium. Outside services are replaced: the video players by a stand-in that
speaks CineSrc's API, images and fonts are blocked. The tests never depend on another website.
Test data: 8 movies, 1 show with 2 seasons, French translations, one account with four
profiles (Alex in English, Camille in French, Kids, and Sam: new, nothing liked yet), and a show
still on air ("Night Shift": an episode 12 days ago, then in 3 and 10 days, dated from the run),
a franchise (The Godfather + The Godfather Part II, collection 230), see `backend/users/management/commands/e2e_prepare.py`.

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

### Focus look never covers a neighbour: `e2e/tests/focus-overlap.spec.js` (10: 5 at 1280 × 720, the same 5 at 1920 × 1080)

Every control on screen is focused the way the remote does; its focus look (the box after any
lift / zoom, plus its ring) must keep at least 2px clear of every other control. Zoom clipped by
its own card doesn't count, nor does what scrolls under a pinned bar, nor rows that touch at rest
(menu lists). Each page is checked screen by screen, top to bottom.

| Test | Pages |
|---|---|
| browsing pages | home, Movies, TV Shows, My List, Upcoming, a collection, search (empty and with results) |
| title pages and the player | a movie in a franchise, a movie, a show, the player (Alex's history is cleared after) |
| signed out: sign in, sign up | sign in, sign up |
| menus, sheets and dialogs | browse filters, title options, profile menu, notifications, every tab of the avatar builder |
| profiles, account, picker, import | Who's watching?, Manage profiles, the profile editor, taste picker, import, watch history, your year, account, My List with your lists, a list, its shared page, the "Add to a list" dialog |

To see what overlaps, the test prints `OVERLAP <page> \| <focused> -> <neighbour> (<w>x<h>)`.

### Lists: `e2e/tests/lists.spec.js` (1, remote only, at 1280 × 720)

| Test | Verifies |
|---|---|
| make a list, share it, open it signed out, save a copy | "Add to a list" beside My List opens on the name field, a new list starts with the title, Back closes; from a card's options sheet the dialog starts on the list and OK adds; My List starts on "Your lists"; Share shows the address; someone signed out sees the list and opens a title; "Save a copy" opens the copy |

### Franchises: `e2e/tests/collection.spec.js` (1, remote only, at 1280 × 720)

| Test | Verifies |
|---|---|
| collection: movie page, collection page, what comes next | the movie page's numbered row starts on this movie, Right reaches part 2 then "Watch order"; the collection page starts on "Start with ...", Down + Right reach part 2, OK opens it, Back returns to it; after part 1: "Next movie" in the player, "1 of 2 watched", "Watch next: ..." and the home row "Next in your collections" |

### Your year: `e2e/tests/stats.spec.js` (1, remote only, at 1280 × 720)

| Test | Verifies |
|---|---|
| walk through the recap with the remote | Down goes through the streak, month chart, genres, most watched and reaches "Share my year" (regression: the button at the right edge was skipped for the footer); Right reaches the card beside the streak; a title opens and Back returns to it (regression: while the page loaded, the focus jumped to the footer) |

### Watch history: `e2e/tests/history.spec.js` (1, remote only, at 1280 × 720)

| Test | Verifies |
|---|---|
| remove an entry, pause, clear: all with the remote | Kids watches two titles; the remote reaches an entry, Right its remove button, OK removes it and the focus moves to the next one; the pause switch stops recording (a title opened meanwhile isn't added); Clear history opens a dialog on Cancel, Right + OK empties it |

### Upcoming: `e2e/tests/calendar.spec.js` (1, remote only, at 1280 × 720)

| Test | Verifies |
|---|---|
| follow a show coming back, then its episodes are in the calendar | an empty calendar offers "Night Shift"; Down lands on it, OK follows it (the focus stays) and its episodes appear by day; Up reaches them; OK on one to come opens the show; Back returns to that card |

### History import: `e2e/tests/import.spec.js` (1, remote only, at 1280 × 720)

| Test | Verifies |
|---|---|
| import with the remote: sources, upload, summary, then home | the remote starts on the selected source, Right / OK switch to IMDb and back, Down reaches "Choose files"; after a Letterboxd file (uploaded like a phone would) the summary counts liked / watched / not found, the remote lands on "Go to your home page", the titles not found can be shown, and home opens with its rows |

### Taste picker: `e2e/tests/taste.spec.js` (2, remote only, at 1280 × 720)

| Test | Verifies |
|---|---|
| home banner opens the picker, Back returns without saving | a new profile's home offers "Pick titles" right under Play (Down, not skipped); Right reaches "Not now"; the banner remembers its button; OK opens the picker; Back leaves it without saving |
| pick with OK, Continue with Down, then a personal home page | starts on the first poster; OK picks; Down never leaves the focus under the pinned bar and enters it on Continue (not Skip); Up returns to the poster; Continue opens the home page without the banner |

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
| `npm run lint` | the frontend has a code warning (unused variable, hook rules, missing effect dependency...) |
| production build | the frontend doesn't compile |
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
