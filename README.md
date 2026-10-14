# Checkers Arena

A browser-based English draughts (American checkers) game with real-time matchmaking, accounts, persistent player records, and ELO ratings. The server enforces all game rules and validates every move.

## Run locally

Requires Python 3.10 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload
```

Open <http://127.0.0.1:8000> in two browser windows and create two accounts to play against each other. Accounts, ratings, and completed matches are stored in `checkers.db`. Set `CHECKERS_DB` to use a different SQLite database file.

## Put it online

### Deploy a free test version to Render

`render.yaml` configures a free Render web service that serves the app over HTTPS/WSS and supports live WebSocket games. To deploy it:

1. Push this project to a GitHub repository.
2. Sign in to [Render](https://dashboard.render.com), select **New** → **Blueprint**, and connect that GitHub repository.
3. Review the `checkers-arena` service and deploy it on the **Free** plan. Do not add a paid disk or change the service plan for this test deployment.
4. Open the public `onrender.com` URL Render gives you and share it with friends. Each player creates an account; use the same link to join the matchmaking queue.

**Free-service limitations:** Render spins down free web services after 15 minutes without traffic, and waking them can take about a minute. The free filesystem is temporary, so accounts and ratings may be lost when the service sleeps, restarts, or redeploys. This is suitable for trying the game, not for keeping player progress. For persistent accounts and ratings, move the SQLite database to durable storage on a paid host plan before promoting the game.

Matchmaking is held in memory, so run a single application worker. Local development uses `checkers.db`; the Render Blueprint sets `CHECKERS_DB=/tmp/checkers.db` to keep test data out of the deployed source directory.

## Rules and progression

- 8×8 American checkers, with red moving first.
- Captures are mandatory; a capturing piece must continue jumping while another capture is available.
- Men move and capture forward; kings move and capture in either direction.
- A game ends when a player has no legal moves, resigns, or disconnects. A draw is declared after 80 consecutive non-capturing moves.
- Players start at 1000 ELO. Ratings and win/loss/draw records are saved after each completed game.

Run the rules tests with `python -m unittest discover -s tests`.
