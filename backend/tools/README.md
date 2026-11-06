# backend/tools

One-off scripts, run by hand from `backend/` (the regular jobs are `manage.py` commands, see
`commands.txt` at the repository root). Their input / output lists live in `backend/data/`.

| Script | What it does |
| --- | --- |
| `seed_titles.py` | Fill / sync movies or shows from a list of TMDB / IMDb ids: `python tools/seed_titles.py --mode movies --ids-file data/movie_tmdb_ids.txt --skip-existing-tmdb` |
| `get_20000_top_movies.py` | Build `data/tmdb_top_plus_blockbusters40y_20000.txt` (top rated + blockbusters of 40 years) |
| `get_100tv.py` | Build `data/b.txt`: popular shows not already in `data/a.txt` |
| `fetch_vidsrc_tmdb_ids.py` | List the TMDB ids a provider has |
| `add_trailer_to_cdn.py` | Cut 20 s trailer clips and upload them to the CDN (`scripts/run_add_trailer_to_cdn.sh` on the server) |

Keys come from the environment, never from the code: `TMDB_API_KEY`, `BUNNY_API_KEY`
(e.g. `docker compose exec backend python tools/add_trailer_to_cdn.py`: the container has backend/.env).
