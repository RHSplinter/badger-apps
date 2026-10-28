# Contribution Graph

Contribution Graph shows a GitHub user's yearly contribution heatmap, starting with the username set on your badge.

It draws the last year of contributions as the familiar grid of green squares,
one column per week, and shows the current streak, longest streak and busiest
day underneath. The app opens on the username in `GITHUB_USERNAME` in the
badge's `secrets.py`; you can look up anyone else with an on-screen keyboard,
and that choice lasts until you leave the app.

## Setting your username

Set `GITHUB_USERNAME` in the badge's `secrets.py`. Use just the handle, with no
`@` and no `github.com/`:

```python
GITHUB_USERNAME = "your-handle"
```

1. Put the badge in USB Disk Mode: open the **Mass Storage** app, or quickly
   double-tap RESET.
2. Open `secrets.py` on the **BADGER** drive (in its top folder) in a text
   editor, change the `GITHUB_USERNAME` line and save the file.
3. Eject the drive. The badge restarts; open **Contribution Graph** again.

The Settings app also has a *GitHub Username* field. If it shows that field as
locked, change the value in `secrets.py` instead.

The app reads this one setting every time it starts, and spaces around the name
are ignored. It never reads `GITHUB_TOKEN` or any password.

### If the app asks you to set your username

When there is nothing usable in `GITHUB_USERNAME`, the app shows a page with the
line to put in `secrets.py`, and downloads nothing:

- **GitHub username not set**: the setting is empty, only spaces, or missing.
- **Invalid GitHub username**: the setting is not a GitHub username. The page
  shows what it found, in quotes (for example `"@octocat"`), so the mistake is
  easy to spot. Usernames may contain letters, numbers and hyphens, up to 39
  characters.

Fix `secrets.py` and open the app again. Until then **MENU** still opens the
keyboard, so you can look someone up in the meantime; those lookups are not
saved. If you set a username that looks right but does not exist on GitHub, the
usual "User not found" message appears with the hint "Check GITHUB_USERNAME in
secrets.py".

## Usage

Open **Contribution Graph** from the badge menu. The graph appears as soon as
it has been downloaded, and refreshes by itself every 30 minutes while the app
is open. The graph for the `GITHUB_USERNAME` user is saved on the badge, so it
shows immediately next time, even when Wi-Fi is not available. Graphs for other
users are not saved.

### Controls

| Button | On the graph | On the keyboard |
| --- | --- | --- |
| UP / DOWN | Previous / next day | Move the highlight up / down |
| LEFT / RIGHT | Previous / next week | Move the highlight left / right |
| SELECT | Refresh now | Type the highlighted key |
| BACK | Jump to the latest day | Delete a letter (cancel when empty) |
| MENU | Change user | Cancel |
| HOME | Return to the badge menu | Return to the badge menu |

Holding a direction button repeats it. The panel under the graph shows the
date and number of contributions for the highlighted day.

### Changing the user

1. Press **MENU**.
2. Move to a letter, number or `-` and press **SELECT** to type it. `Aa` makes
   the next letter a capital, `DEL` deletes, and `OK` accepts the name.
3. The graph for the new user loads. If GitHub has no such user, the keyboard
   comes back with "User not found" so you can fix the name. What was on screen
   before (the previous user, or the page asking for your username) stays as it
   was; press **MENU** to leave the keyboard.

The chosen user is not saved. Their graph stays up until you leave the app, and
the next time you open it, it starts on the `GITHUB_USERNAME` user again. Names
may contain letters, numbers and hyphens, up to 39 characters.

## Requirements

- A username in the badge's `secrets.py` (`GITHUB_USERNAME`, see above).
- Wi-Fi: the badge needs its Wi-Fi details set up (Settings app, stored in the
  badge's `secrets.py`). The app never reads or stores Wi-Fi credentials
  itself. Without them it shows the saved graph if there is one, and otherwise
  the standard "missing details" screen. If the username is not set either, the
  username page comes first, and its footer says Wi-Fi is not set up.
- Data comes from `https://github.com/<user>.contribs`, a public JSON feed with
  one entry per day. No token or sign-in is needed.
- Network problems never close the app: it keeps showing what it has and
  retries after 30 s, then 60 s, then every 2 minutes.

## Files

- `__init__.py`: screens, buttons and networking.
- `contrib_data.py`: parsing, dates, statistics and keyboard logic. It has no
  badge dependencies, so it also runs on a desktop for testing.
- `icon.png`: 48x48 menu icon.

Saved on the badge: `/state/contribution_graph_cache.json` (the last graph for
the `GITHUB_USERNAME` user, about 1.5 KB). It is only shown for that user, so if
you change `GITHUB_USERNAME` the old graph is ignored and replaced once the new
one has downloaded. The app does not record which user you looked up last. An
old `/state/contribution_graph.json` from earlier versions, which stored that
choice, is ignored and deleted when the app starts.

## Status

Not yet run on a physical badge, so timing, memory use, how the dark squares
look on the real screen, and reading the real `secrets.py` are still to be
confirmed.

Checked so far:

- The static validator, for both the badge and the simulator, with no warnings.
- Desktop tests that drive the app against a fake badge and run every line of
  both files. They cover every kind of `GITHUB_USERNAME` (a name, padded with
  spaces, empty, spaces only, missing line, missing `secrets` module, an `@`,
  a space, a whole address, an underscore, too long, accents and other
  scripts), both username pages and how they fit the screen, looking someone up
  from them, saving only the `GITHUB_USERNAME` user's graph, and ignoring the
  file an earlier version left behind.
- The same code on MicroPython 1.29.0 (WebAssembly build), giving the same
  results as desktop Python, including for each of those usernames.
- The web simulator (https://badger.github.io/simulator) with `GITHUB_USERNAME`
  set to a real name, empty, spaces only, `@octocat`, a name that is too long,
  a non-ASCII name, a name padded with spaces, and a name that does not exist:
  the right page appears each time. With a real name, live data loads, the
  cursor moves, SELECT refreshes, the user can be changed, an unknown user is
  rejected, and the app recovers after being offline. Looking someone up from
  the username page, and an unknown user there, also work. The simulator does
  not keep saved files between runs and always has Wi-Fi set up, so the saved
  graph and the username page's "Wi-Fi is not set up" footer are only checked
  by the desktop tests and MicroPython.
