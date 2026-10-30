# Checkers Arena

A cross-platform browser game and Windows desktop app for English draughts (American checkers), with real-time matchmaking, accounts, persistent player records, ELO ratings, a leaderboard, and live match chat. The server enforces all game rules and validates every move.

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

Run the test suite with `python -m unittest discover -s tests`.

## Windows desktop app

The desktop app can either host a game server on the player's PC or connect directly to another player's host. There is no required paid host or central matchmaking service in this mode. The host's PC must remain on with the app running while players are connected. The first desktop release uses one direct host per game; automatic peer-to-peer host handoff is a later step.

```powershell
python -m venv .venv-desktop
.\.venv-desktop\Scripts\Activate.ps1
python -m pip install -r requirements-desktop.txt
python desktop.py
```

On first launch, choose **Yes** to host on this PC or **No** to enter a host's invite address. To host directly from the command line, run `python desktop.py --host-game`; to join a host, run `python desktop.py --server-url https://your-host.example.com`. The `CHECKERS_SERVER_URL` environment variable is also supported. Each host keeps its own accounts and ratings in `%APPDATA%\Checkers Arena\checkers.db`.

### Invite players on the same Wi-Fi

1. Start the desktop app and choose **Yes** to host.
2. Allow Checkers Arena through Windows Firewall on your private network if Windows asks.
3. Give friends one of the local network addresses shown by the app. They choose **No** on startup and enter that address.

### Invite players over the internet

This requires more setup because home routers block unsolicited incoming connections by default:

1. Give the host PC a reserved LAN address in the router and forward TCP port `8000` to that PC.
2. Allow the app through Windows Firewall for the network profile you use.
3. Use a domain name pointing to your internet connection and obtain a valid TLS certificate for it. Start the host with `python desktop.py --host-game --ssl-certfile fullchain.pem --ssl-keyfile privkey.pem`.
4. Share the HTTPS address, such as `https://games.example.com`, with players. They join using `python desktop.py --server-url https://games.example.com`.

Do not expose a public HTTP host: account passwords and session tokens must be protected by HTTPS. Dynamic public IP addresses may require a dynamic-DNS domain. Port-forwarding and certificate setup depend on the router and network provider; some networks do not allow inbound connections.

To package a Windows executable from Windows:

```powershell
pyinstaller --noconfirm --windowed --onefile --name CheckersArena --add-data "static;static" desktop.py
```

The executable is written to `dist\CheckersArena.exe`. It can host locally with `CheckersArena.exe --host-game` or connect to an invited host with `CheckersArena.exe --server-url https://your-host.example.com`.
