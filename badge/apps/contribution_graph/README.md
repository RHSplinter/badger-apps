# Contribution Graph

Contribution Graph shows any GitHub user's yearly contribution heatmap, starting with RHSplinter.

It draws the last year of contributions as the familiar grid of green squares,
one column per week, and shows the current streak, longest streak and busiest
day underneath. The app always opens on **RHSplinter**; you can look up anyone
else with an on-screen keyboard, and that choice lasts until you leave the app.

## Usage

Open **Contribution Graph** from the badge menu. The graph appears as soon as
it has been downloaded, and refreshes by itself every 30 minutes while the app
is open. RHSplinter's last graph is saved on the badge, so it shows immediately
next time, even when Wi-Fi is not available. Graphs for other users are not
saved.

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
   comes back with "User not found" so you can fix the name. The previous user
   stays selected; press **MENU** to leave the keyboard.

The chosen user is not saved. Their graph stays up until you leave the app, and
the next time you open it, it starts on RHSplinter again. Names may contain
letters, numbers and hyphens, up to 39 characters.

## Requirements

- Wi-Fi: the badge needs its Wi-Fi details set up (Settings app, stored in the
  badge's `secrets.py`). The app never reads or stores credentials itself. Without
  them it shows the saved graph if there is one, and otherwise the standard
  "missing details" screen.
- Data comes from `https://github.com/<user>.contribs`, a public JSON feed with
  one entry per day. No token or sign-in is needed.
- Network problems never close the app: it keeps showing what it has and
  retries after 30 s, then 60 s, then every 2 minutes.

## Files

- `__init__.py`: screens, buttons and networking.
- `contrib_data.py`: parsing, dates, statistics and keyboard logic. It has no
  badge dependencies, so it also runs on a desktop for testing.
- `icon.png`: 48x48 menu icon.

Saved on the badge: `/state/contribution_graph_cache.json` (RHSplinter's last
graph, about 1.5 KB). The app does not record which user you looked up last. An
old `/state/contribution_graph.json` from earlier versions, which stored that
choice, is ignored and deleted when the app starts.

## Status

Not yet run on a physical badge, so timing, memory use and how the dark squares
look on the real screen are still to be confirmed.

Checked so far:

- The static validator, for both the badge and the simulator, with no warnings.
- Desktop tests that drive the app against a fake badge and run every line of
  both files. They cover starting on RHSplinter every time, never saving
  another user, and ignoring the file an earlier version left behind.
- The same code on MicroPython 1.29.0, giving the same results as desktop Python.
- The web simulator (https://badger.github.io/simulator): live data loads, the
  cursor moves, SELECT refreshes, the user can be changed, an unknown user is
  rejected, and the app recovers after being offline. Running the app again
  there starts on RHSplinter. The simulator does not keep saved files between
  runs, so the saved graph is only checked by the desktop tests and MicroPython.
