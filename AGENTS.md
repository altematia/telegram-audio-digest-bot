# Project rules

## Required iteration finish

At the end of every implementation iteration in this repository:

1. Run the full automated test suite with `.venv/bin/python -m pytest`.
2. Inspect `git status` and make sure no secret, `.env`, database, audio, or deploy private key is staged.
3. Commit all intended changes with a descriptive commit message. Do not create an empty commit when nothing changed.
4. Push the commit to `origin/main`.
5. Deploy that exact pushed revision to `root@109.172.6.81` by running `scripts/deploy.sh` (the server must update through `git pull --ff-only`).
6. Verify `telegram-audio-digest-bot.service` is active and inspect its latest logs for startup or polling errors.

An iteration is not complete until tests, commit, push, deploy, restart, and service verification have all succeeded. Never commit or print credentials. Ask the user only after safe, in-scope recovery options are exhausted.

## Architecture

- Keep the application small and single-process unless measured load requires more.
- Use long polling, SQLite, and systemd; do not add queues, Redis, a web server, or containers without a concrete need.
- Runtime secrets belong only in `.env` locally and `/etc/telegram-audio-digest-bot.env` on the server.
- Raw audio is temporary and must be deleted after each request. Persist only transcripts and cached summaries.
