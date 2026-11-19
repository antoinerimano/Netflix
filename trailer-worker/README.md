# trailer-worker

Makes the short trailer previews the site plays on the home banner and the rows, on a Linux
machine at home (a mini PC is plenty), **not** on the site's server:

- downloading and encoding videos is heavy; the server only answers two quick commands
- YouTube blocks server / cloud addresses far more than a home connection

```
server: manage.py export_trailer_jobs  ──jobs.json──▶  mini PC: make_previews.py  ──▶  Bunny Storage
server: manage.py import_trailer_results  ◀──results.json──┘
```

For each title it reads the YouTube video's details, **checks the video's name is the title's**
(otherwise: `rejected`, nothing uploaded), downloads only the ~17 s it keeps at 540p, encodes a
15 s clip (~2 MB, starts playing while it downloads) and uploads it to
`previews/{movie|tv}/{tmdb_id}-{youtube id}.mp4`. Which video is a title's trailer is chosen on
the server when TMDB is synced (`backend/users/trailers.py`).

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

`run.sh` does all three steps (export, make, import), stops after `MAX_MINUTES` (8 h) and
carries on the next night. `crontab -e`:

```
0 1 * * * /home/you/taurus/trailer-worker/run.sh >> /home/you/taurus/trailer-worker/run.log 2>&1
```

The first time the whole catalogue is done again (old clips could belong to the wrong title):
popular titles first, about 3 to 5 nights for 20,000 titles. Then a few minutes a night.

Before the new clips, `run.sh` re-checks up to `RECHECK_AUDIO` (100) clips already made: clips
made before the worker asked for the original audio could carry one of YouTube's AI dubs (a
Russian *The Walking Dead*). A video with other audio tracks gets its clip made again, same
path; `results.json` notes each clip's `audio` (`single`, `redone`, `gone`). Once all are
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
