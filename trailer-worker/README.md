# trailer-worker

Makes the short trailer previews the site plays on the home banner and the rows, on a Linux
machine at home (a mini PC is plenty), **not** on the site's server:

- downloading and encoding videos is heavy; the server only answers two quick commands
- YouTube blocks server / cloud addresses far more than a home connection

```
server: manage.py export_trailer_jobs  ──jobs.json──▶  mini PC: make_previews.py  ──▶  Bunny Storage
server: manage.py import_trailer_results  ◀──results.json──┘
```

For each title it reads the YouTube video's details, **checks the video is the title's trailer**
(its name is the title's or one of its other names on TMDB, not a sequel, not another year's film,
20 s to 10 min), downloads only the ~17 s it keeps at 540p (the whole video when cutting while
downloading fails), encodes a 15 s clip (~2 MB, starts playing while it downloads) and uploads it
to `previews/{movie|tv}/{tmdb_id}-{youtube id}.mp4`.

Which video: the trailer the server chose when TMDB was synced (`backend/users/trailers.py`)
first. When it can't be used (removed, private, blocked in this country, not the title's), the
title's other TMDB trailers and teasers in the server's order, then a YouTube search. Titles TMDB
has no trailer for at all (with 20+ votes: `export_trailer_jobs --search-min-votes`) go straight
to those two. The import saves a clip made from another video with `trailer_clip_for`, and the
title page then plays that video instead of TMDB's broken one. Titles where nothing fitted are
tried again after `RECHECK_DAYS` (60): TMDB and YouTube get new videos.

TMDB's other trailers and the title's other names need `TMDB_API_KEY` in `.env` (the same key as
`backend/.env`); without it, only the search is tried.

## Setup (Debian / Ubuntu)

```bash
sudo apt update && sudo apt install -y git python3 python3-venv ffmpeg
git clone <this repository> ~/taurus && cd ~/taurus/trailer-worker
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env        # Bunny zone + key, the server's SSH address
```

An SSH key so `run.sh` can reach the server without a password:

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519   # if you don't have one
ssh-copy-id user@your-server
ssh user@your-server 'cd /opt/taurus && docker compose exec -T backend python manage.py export_trailer_jobs --limit 1'
```

## Try it

```bash
ssh user@your-server 'cd /opt/taurus && docker compose exec -T backend python manage.py export_trailer_jobs --limit 5' > jobs.json
.venv/bin/python make_previews.py jobs.json --dry-run    # makes the clips, uploads nothing
.venv/bin/python make_previews.py jobs.json              # uploads, writes results.json
ssh user@your-server 'cd /opt/taurus && docker compose exec -T backend python manage.py import_trailer_results - --dry-run' < results.json
```

## Every night

`run.sh` does all three steps (export, make, import), stops after `MAX_MINUTES` (8 h by
default; a machine that does nothing else can run ~21 h, `MAX_MINUTES=1260`) and carries on the
next night. When YouTube refuses, it gives the site what is done so far, waits
`BLOCKED_PAUSE_MINUTES` (30) and tries again, rather than stopping for the night.
Every `PROGRESS_MINUTES` (60) it also gives the site the clips made so far, and the admin
dashboard's "Trailer clips (mini PC)" row shows the run as *Running* with one line of progress
(`manage.py record_job trailer_worker --start / --progress`, then the end, ok or failed): a run
that is still going isn't mistaken for one that didn't work.
If YouTube keeps refusing, give yt-dlp a YouTube account's cookies (`YTDLP_COOKIES_FILE`, a
secondary account: exported from a browser where it is signed in). `crontab -e`:

```
0 1 * * * cd /home/you/taurus && (git pull -q --ff-only; trailer-worker/run.sh) >> /home/you/taurus/trailer-worker/run.log 2>&1
```

`git pull` first: a fix merged on `main` reaches the mini PC the next night, nobody has to log in.
Unattended reboots after security updates (`/etc/apt/apt.conf.d/52taurus-autoreboot`:
`Unattended-Upgrade::Automatic-Reboot "true"` and `Automatic-Reboot-Time "12:30"`, after the night
jobs) are safe: cron, ssh and Tailscale start at boot, nobody has to log in.

The first time the whole catalogue is done again (old clips could belong to the wrong title):
popular titles first, about 3 to 5 nights for 20,000 titles. Then a few minutes a night.

Before the new clips, `run.sh` re-checks up to `RECHECK_AUDIO` (100) clips already made: clips
made before the worker asked for the original audio could carry one of YouTube's AI dubs (a
Russian *The Walking Dead*). A video with other audio tracks gets its clip made again under a
new name (`...-a.mp4`: the CDN and browsers keep a file 30 days, the same name would go on
serving the old clip); `results.json` notes each clip's `audio` (`single`, `redone`, `gone`)
and `rev`, and the import saves the new address on the title. Once all are
checked, this step takes a few seconds.

## When something goes wrong

| In the log | Meaning / what to do |
|---|---|
| `YouTube refused (... not a bot)` | Too fast, or YouTube is wary of this address for a while. The run stops by itself and carries on the next night. If it keeps happening: raise `DELAY_MIN` / `DELAY_MAX`, or export your YouTube cookies (browser extension "Get cookies.txt LOCALLY") to a file and set `YTDLP_COOKIES_FILE`. |
| `rejected: the video is called '...'` | TMDB's trailer is another video (fan upload, wrong film). Not uploaded. `import_trailer_results --clear-rejected` also removes the title's old clip, most likely wrong too. |
| `unavailable` | Private / removed video. Tried again once TMDB lists another trailer. |
| `error` | Anything else; tried again on the next runs (3 times). |
| `Another run is going` | The previous night's run hasn't finished: fine. |

`results.json` remembers every title (by its trailer): delete a line's entry to make it again.
