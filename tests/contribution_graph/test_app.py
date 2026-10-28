"""Runs the real app on a fake badge and checks what a person would see and do.

These tests exercise badge/apps/contribution_graph/__init__.py as it is, so
they cover the screens, buttons, saved files and network handling. They cannot
say anything about speed, memory or how the screen looks on the hardware.
"""

import datetime
import json
import os
import random
import re
import tempfile
import types
import unittest

from fake_badge import CACHE_FILE, DOWNLOAD_FILE, STATE_FILE, Reply, Runtime
import payloads
import contrib_data as logic

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")   # datetime.weekday() order
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
SECOND = 1000
MINUTE = 60 * SECOND
JUST_AFTER_REFRESH = 30 * MINUTE + 3 * SECOND
RANDOM_SEEDS = int(os.environ.get("CONTRIB_RANDOM_SEEDS", "5"))
RANDOM_STEPS = int(os.environ.get("CONTRIB_RANDOM_STEPS", "500"))
HINT = "MENU change user   SELECT refresh"
DATE_TEXT = re.compile(r"^[A-Z][a-z]{2}, [A-Z][a-z]{2} \d{1,2}, \d{4}$")
RETRY_TEXT = re.compile(r"^(.+) - retrying in (\d+)s$")


def date_text(index, first=payloads.FIRST_SUNDAY):
    day = first + datetime.timedelta(days=index)
    return "{}, {} {}, {}".format(WEEKDAYS[day.weekday()], MONTHS[day.month - 1], day.day, day.year)


def count_text(count):
    if count == 0:
        return "No contributions"
    return "{:,} contribution{}".format(count, "" if count == 1 else "s")


def summary_text(total):
    if total == 0:
        return "No contributions in the last year"
    return count_text(total) + " in the last year"


def days_text(count):
    return "{} day{}".format(count, "" if count == 1 else "s")


def expected_stats(counts):
    """(current streak, longest streak, busiest day), worked out the long way."""
    longest = run = 0
    for count in counts:
        run = run + 1 if count else 0
        longest = max(longest, run)
    end = len(counts) - 1
    if counts[end] == 0:
        end -= 1
    current = 0
    while end >= 0 and counts[end]:
        current += 1
        end -= 1
    return current, longest, max(counts)


def other_payload(**kwargs):
    """Another user's data, easy to tell apart from the default payload."""
    kwargs.setdefault("count_for", lambda index: 1)
    return payloads.build(**kwargs)


def footer(rt):
    """(text, colour) of the status line at the bottom of the graph and loading screens."""
    y = rt.namespace["FOOTER_Y"]
    found = [(op[1], op[5]) for op in rt.screen.ops if op[0] == "text" and op[3] == y]
    assert len(found) == 1, found
    return found[0]


def text_op(rt, text):
    """(text, x, y, size, colour) of the one operation that draws `text`."""
    found = [op[1:] for op in rt.screen.ops if op[0] == "text" and op[1] == text]
    assert len(found) == 1, (text, found)
    return found[0]


def pessimistic(text, size):
    """A guess at text width that is wider than most fonts."""
    return len(text) * size * 0.62


class AppCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = folder.name
        self.payload = payloads.build()
        self.total = self.payload["total_contributions"]

    def launch(self, *replies, root=None, **options):
        return Runtime(root or self.root, replies=list(replies), **options).start()

    def launched(self, *replies, **options):
        """Launch, then run long enough for the first download to be handled."""
        rt = self.launch(*replies, **options)
        rt.frames_for(6)
        return rt

    def retry_footer(self, rt):
        """(problem, seconds) from a red "<problem> - retrying in Ns" footer."""
        text, pen = footer(rt)
        match = RETRY_TEXT.match(text)
        self.assertTrue(match, text)
        self.assertEqual(pen, rt.namespace["RED"])
        return match.group(1), int(match.group(2))


class LaunchTests(AppCase):
    def test_runtime_setup(self):
        rt = self.launch()
        self.assertEqual(rt.badge.mode_value, rt.namespace["HIRES"] | rt.namespace["VSYNC"])
        self.assertEqual(rt.screen.antialias, rt.namespace["image"].X2)
        self.assertEqual(rt.fetch.AsyncFetch.MAX_HEADER_BYTES, 8192)
        self.assertEqual(rt.wifi.calls, [((), {"timeout": 10, "retries": 100000})])
        self.assertEqual(rt.os.cwd, "/system/apps/contribution_graph")

    def test_the_app_still_starts_if_the_font_cannot_be_loaded(self):
        def broken():
            raise OSError("no font")

        rt = Runtime(self.root, replies=[Reply(self.payload)])
        rt.missing_details.mona_sans = broken
        rt.start()
        self.assertEqual(rt.namespace["FONT"], "font.nope")
        rt.frames_for(6)
        self.assertIn(summary_text(self.total), rt.texts())

    def test_a_graph_is_shown_even_when_it_cannot_be_saved(self):
        rt = self.launch(Reply(self.payload))
        os.makedirs(rt.host(CACHE_FILE))
        rt.frames_for(6)
        self.assertIsNotNone(rt.app.graph)
        self.assertIn(summary_text(self.total), rt.texts())

    def test_the_default_user_is_fetched_on_first_launch(self):
        rt = self.launch(Reply(self.payload))
        rt.frame()
        self.assertIsNone(rt.app.graph)
        self.assertIn("@RHSplinter", rt.texts())
        self.assertTrue([t for t in rt.texts() if t.startswith("Loading contributions")])
        self.assertEqual(footer(rt), ("Fetching contributions", rt.namespace["MUTED"]))
        rt.frames_for(4)
        self.assertEqual(len(rt.requests), 1)
        request = rt.requests[0]
        self.assertEqual(request.url, "https://github.com/RHSplinter.contribs")
        self.assertEqual(request.headers, {"User-Agent": "GitHub Universe Badge 2026"})
        self.assertEqual(request.path, DOWNLOAD_FILE)
        self.assertIsNotNone(rt.app.graph)
        self.assertIn(summary_text(self.total), rt.texts())
        self.assertIn("@RHSplinter", rt.texts())
        self.assertEqual(footer(rt), (HINT, rt.namespace["MUTED"]))
        self.assertFalse(rt.exists(DOWNLOAD_FILE))
        cache = rt.read_json(CACHE_FILE)
        self.assertEqual(cache["h"], "RHSplinter")
        self.assertEqual(len(cache["l"]), 53 * 7)
        self.assertEqual(sum(cache["c"]), self.total)

    def test_the_default_user_is_not_saved_until_it_is_changed(self):
        rt = self.launched(Reply(self.payload))
        self.assertFalse(rt.exists(STATE_FILE))

    def test_a_saved_graph_is_shown_on_the_first_frame_while_it_updates(self):
        self.launched(Reply(self.payload))
        rt = self.launch(Reply(self.payload, pumps=3))
        rt.frame()
        self.assertIn(summary_text(self.total), rt.texts())
        self.assertIn(date_text(366), rt.texts())
        self.assertEqual(footer(rt)[0], "Fetching contributions")
        rt.frames_for(6)
        self.assertEqual(footer(rt)[0], HINT)

    def test_a_cache_for_another_user_is_not_shown(self):
        cache = logic.parse_contribs(self.payload, "octocat").to_dict()
        rt = self.launch(Reply(self.payload), cache=cache)
        rt.frame()
        self.assertIsNone(rt.app.graph)
        self.assertIn("@RHSplinter", rt.texts())

    def test_the_cache_is_matched_to_the_user_without_regard_to_case(self):
        cache = logic.parse_contribs(self.payload, "rhsplinter").to_dict()
        rt = self.launch(Reply(self.payload, pumps=50), cache=cache)
        rt.frame()
        self.assertIsNotNone(rt.app.graph)

    def test_damaged_caches_are_ignored(self):
        good = logic.parse_contribs(self.payload, "RHSplinter").to_dict()
        cases = (
            ("not json", "{oops"),
            ("empty file", ""),
            ("a list", "[]"),
            ("an empty object", "{}"),
            ("wrong version", dict(good, v=99)),
            ("bad levels", dict(good, l="x" * len(good["l"]))),
            ("short counts", dict(good, c=good["c"][:-1])),
            ("start not a Sunday", dict(good, s="2025-10-27")),
        )
        for name, content in cases:
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as root:
                    rt = self.launch(Reply(self.payload), root=root, cache=content)
                    rt.frame()
                    self.assertIsNone(rt.app.graph)
                    rt.frames_for(5)
                    self.assertIn(summary_text(self.total), rt.texts())
                    self.assertEqual(rt.read_json(CACHE_FILE)["h"], "RHSplinter")

    def test_a_saved_handle_is_used(self):
        rt = self.launch(Reply(self.payload), state={"handle": "octocat"})
        rt.frames_for(5)
        self.assertEqual(rt.requests[0].url, "https://github.com/octocat.contribs")
        self.assertIn("@octocat", rt.texts())

    def test_unusable_saved_handles_fall_back_to_the_default(self):
        cases = ({"handle": "bad handle!"}, {"handle": ""}, {"handle": 7}, {"handle": None},
                 {"handle": "x" * 40}, {"handle": "a/b"}, {"other": 1}, [], "not json at all")
        for saved in cases:
            with self.subTest(saved=saved):
                with tempfile.TemporaryDirectory() as root:
                    rt = self.launch(Reply(self.payload), root=root, state=saved)
                    rt.frames_for(2)
                    self.assertEqual(rt.requests[0].url, "https://github.com/RHSplinter.contribs")

    def test_buttons_do_nothing_harmful_while_loading(self):
        rt = self.launch(Reply(self.payload, pumps=100))
        for name in ("UP", "DOWN", "LEFT", "RIGHT", "BACK", "SELECT"):
            rt.press(name)
        self.assertIsNone(rt.app.graph)
        self.assertEqual(len(rt.requests), 1)
        rt.press("MENU")
        self.assertIsNotNone(rt.app.editor)


class GraphScreenTests(AppCase):
    def setUp(self):
        super().setUp()
        self.rt = self.launched(Reply(self.payload))

    def test_every_day_is_drawn_in_its_own_cell(self):
        rt = self.rt
        palette = rt.namespace["LEVEL_COLORS"]
        top = rt.namespace["GRAPH_Y"]
        left = (320 - (53 * 6 - 1)) // 2            # 53 columns of 6 px, centred
        expected = set()
        for week in self.payload["weeks"]:
            for day in week["contribution_days"]:
                expected.add((left + week["index"] * 6, top + day["weekday"] * 6, palette[day["level"]]))
        drawn = [(r[1], r[2], r[5]) for r in rt.rects() if (r[3], r[4]) == (5, 5)]
        self.assertEqual(len(drawn), 367)
        self.assertEqual(set(drawn), expected)

    def test_the_selected_day_has_a_white_outline(self):
        rt = self.rt
        left = (320 - (53 * 6 - 1)) // 2
        x = left + (366 // 7) * 6
        y = rt.namespace["GRAPH_Y"] + (366 % 7) * 6
        outline = [r[1:5] for r in rt.rects() if r[5] == rt.namespace["WHITE"]]
        self.assertEqual(sorted(outline),
                         sorted([(x - 1, y - 1, 7, 1), (x - 1, y + 5, 7, 1), (x - 1, y, 1, 5), (x + 5, y, 1, 5)]))

    def test_months_are_labelled_in_order(self):
        names = [t for t in self.rt.texts() if t in MONTHS]
        self.assertEqual(names, ["Nov", "Dec", "Jan", "Feb", "Mar", "Apr",
                                 "May", "Jun", "Jul", "Aug", "Sep", "Oct"])

    def test_the_texts_around_the_graph(self):
        texts = self.rt.texts()
        for text in ("@RHSplinter", summary_text(self.total), "as of Oct 27", "Less", "More",
                     "Current streak", "Longest streak", "Busiest day"):
            self.assertIn(text, texts)

    def test_the_three_numbers_under_the_graph(self):
        designed = payloads.build(count_for=lambda i: 5 if 100 <= i < 110 else 3 if i >= 364 else 0)
        self.assertEqual(expected_stats(payloads.flat_counts(designed)), (3, 10, 5))
        for name, data in (("designed", designed), ("default", self.payload)):
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as root:
                    rt = self.launched(Reply(data), root=root)
                    current, longest, busiest = expected_stats(payloads.flat_counts(data))
                    y = rt.namespace["STATS_Y"]
                    values = [op for op in rt.screen.ops if op[0] == "text" and op[3] == y]
                    values.sort(key=lambda op: op[2])
                    self.assertEqual([op[1] for op in values],
                                     [days_text(current), days_text(longest), str(busiest)])
                    labels = [op for op in rt.screen.ops if op[0] == "text" and op[3] == y + 24]
                    labels.sort(key=lambda op: op[2])
                    self.assertEqual([op[1] for op in labels], ["Current streak", "Longest streak", "Busiest day"])

    def test_big_numbers_get_thousands_separators(self):
        payload = payloads.build(count_for=lambda i: 3000)
        rt = self.launched(Reply(payload))
        self.assertIn("1,101,000 contributions in the last year", rt.texts())
        self.assertIn("3,000 contributions", rt.texts())
        self.assertIn("3,000", rt.texts())
        self.assertIn("367 days", rt.texts())

    def test_a_year_without_contributions(self):
        rt = self.launched(Reply(payloads.build(count_for=lambda i: 0)))
        texts = rt.texts()
        self.assertIn("No contributions in the last year", texts)
        self.assertIn("No contributions", texts)
        self.assertIn("0 days", texts)
        self.assertIn("0", texts)
        palette = rt.namespace["LEVEL_COLORS"]
        self.assertEqual({r[5] for r in rt.rects() if (r[3], r[4]) == (5, 5)}, {palette[0]})


class NavigationTests(AppCase):
    def setUp(self):
        super().setUp()
        self.counts = payloads.flat_counts(self.payload)
        self.last = len(self.counts) - 1
        self.rt = self.launched(Reply(self.payload))

    def assertShowing(self, index):
        texts = self.rt.texts()
        self.assertEqual(self.rt.app.cursor, index)
        self.assertIn(date_text(index), texts)
        self.assertIn(count_text(self.counts[index]), texts)
        self.assertEqual([t for t in texts if DATE_TEXT.match(t)], [date_text(index)])

    def test_it_starts_on_the_latest_day(self):
        self.assertEqual(self.last, 366)
        self.assertEqual(date_text(self.last), "Tue, Oct 27, 2026")
        self.assertShowing(self.last)

    def test_up_and_down_move_one_day(self):
        rt = self.rt
        rt.press("UP")
        self.assertShowing(self.last - 1)
        rt.press("UP")
        self.assertShowing(self.last - 2)
        rt.press("DOWN")
        self.assertShowing(self.last - 1)

    def test_left_and_right_move_one_week(self):
        rt = self.rt
        rt.press("LEFT")
        self.assertShowing(self.last - 7)
        rt.press("LEFT")
        self.assertShowing(self.last - 14)
        rt.press("RIGHT")
        self.assertShowing(self.last - 7)

    def test_moving_right_into_the_partial_last_week_lands_on_its_last_day(self):
        rt = self.rt
        rt.press("LEFT")
        rt.press("DOWN")
        self.assertShowing(self.last - 6)
        rt.press("RIGHT")
        self.assertShowing(self.last)

    def test_there_is_nowhere_to_go_past_the_latest_day(self):
        rt = self.rt
        rt.press("DOWN")
        rt.press("RIGHT")
        self.assertShowing(self.last)
        rt.press("UP")
        rt.press("UP")
        self.assertShowing(self.last - 2)
        rt.press("RIGHT")
        self.assertShowing(self.last - 2)

    def test_back_returns_to_the_latest_day(self):
        rt = self.rt
        rt.press("LEFT")
        rt.press("LEFT")
        rt.press("UP")
        rt.press("BACK")
        self.assertShowing(self.last)

    def test_the_cursor_stops_at_the_first_day(self):
        rt = self.rt
        for _ in range(60):
            rt.press("LEFT")
        self.assertShowing(2)
        self.assertEqual(date_text(2), "Tue, Oct 28, 2025")
        rt.press("UP")
        rt.press("UP")
        self.assertShowing(0)
        self.assertEqual(date_text(0), "Sun, Oct 26, 2025")
        rt.press("UP")
        rt.press("LEFT")
        self.assertShowing(0)

    def test_holding_a_button_repeats_after_a_pause(self):
        rt = self.rt
        rt.hold("UP", 200)
        self.assertShowing(self.last - 1)
        rt.press("BACK")
        rt.hold("UP", 1000)
        moved = self.last - rt.app.cursor
        self.assertTrue(6 <= moved <= 10, moved)

    def test_the_selected_day_is_described_in_a_panel(self):
        rt = self.rt
        rt.press("UP")
        text = count_text(self.counts[self.last - 1])
        self.assertIn(text, rt.texts())
        self.assertNotEqual(text, count_text(self.counts[self.last]))


class ChangeUserTests(AppCase):
    def test_menu_opens_the_keyboard_with_the_current_name(self):
        rt = self.launched(Reply(self.payload))
        rt.press("MENU")
        self.assertEqual(rt.app.editor.text, "RHSplinter")
        texts = rt.texts()
        self.assertIn("GitHub username", texts)
        self.assertIn("RHSplinter", texts)
        for key in logic.KEYS:
            self.assertIn(key, texts)

    def test_menu_again_cancels(self):
        rt = self.launched(Reply(self.payload))
        rt.press("MENU")
        rt.press("MENU")
        self.assertIsNone(rt.app.editor)
        self.assertEqual(len(rt.requests), 1)
        self.assertEqual(rt.app.handle, "RHSplinter")
        self.assertFalse(rt.exists(STATE_FILE))
        self.assertIn(summary_text(self.total), rt.texts())

    def test_back_deletes_letters_and_closes_the_keyboard_when_the_box_is_empty(self):
        rt = self.launched(Reply(self.payload))
        rt.press("MENU")
        rt.press("BACK")
        self.assertEqual(rt.app.editor.text, "RHSplinte")
        for _ in range(9):
            rt.press("BACK")
        self.assertEqual(rt.app.editor.text, "")
        self.assertIsNotNone(rt.app.editor)
        rt.press("BACK")
        self.assertIsNone(rt.app.editor)

    def test_holding_back_clears_the_box_without_closing_the_keyboard(self):
        rt = self.launched(Reply(self.payload))
        rt.press("MENU")
        rt.hold("BACK", 4000)
        self.assertIsNotNone(rt.app.editor)
        self.assertEqual(rt.app.editor.text, "")
        rt.press("BACK")
        self.assertIsNone(rt.app.editor)

    def test_the_arrow_buttons_move_the_highlighted_key(self):
        rt = self.launched(Reply(self.payload))
        rt.press("MENU")
        editor = rt.app.editor
        rt.press("RIGHT")
        self.assertEqual(editor.key(), "b")
        rt.press("DOWN")
        self.assertEqual(editor.key(), "l")
        rt.press("LEFT")
        rt.press("UP")
        self.assertEqual(editor.key(), "a")
        rt.press("LEFT")
        self.assertEqual(editor.cursor, 39)

    def test_entering_a_new_user_switches_and_remembers_it(self):
        other = other_payload()
        self.assertNotEqual(self.total, other["total_contributions"])
        rt = self.launched(Reply(self.payload), Reply(other, pumps=20))
        rt.enter_user("Octo-Cat9")
        self.assertIsNone(rt.app.editor)
        self.assertEqual(rt.app.handle, "Octo-Cat9")
        self.assertEqual(rt.read_json(STATE_FILE), {"handle": "Octo-Cat9"})
        rt.frame()
        self.assertIn("@Octo-Cat9", rt.texts())
        self.assertNotIn(summary_text(self.total), rt.texts())
        self.assertEqual(rt.requests[1].url, "https://github.com/Octo-Cat9.contribs")
        rt.frames_for(30)
        self.assertIn(summary_text(other["total_contributions"]), rt.texts())
        self.assertIn("@Octo-Cat9", rt.texts())
        self.assertEqual(rt.read_json(CACHE_FILE)["h"], "Octo-Cat9")
        self.assertEqual(rt.app.cursor, 366)

    def test_holding_select_repeats_only_on_the_delete_key(self):
        rt = self.launched(Reply(self.payload))
        rt.press("MENU")
        rt.goto_key("a")
        rt.hold("SELECT", 1000)
        self.assertEqual(rt.app.editor.text, "RHSplintera")
        rt.goto_key("DEL")
        rt.hold("SELECT", 1000)
        self.assertTrue(2 <= len(rt.app.editor.text) <= 5, rt.app.editor.text)

    def test_a_name_with_other_characters_is_refused(self):
        rt = self.launched(Reply(self.payload))
        rt.press("MENU")
        rt.app.editor.text = "bad/name"
        rt.goto_key("OK")
        rt.press("SELECT")
        self.assertEqual(rt.app.editor.error, "Use letters, numbers and hyphens")
        self.assertIn("Use letters, numbers and hyphens", rt.texts())
        self.assertEqual(rt.app.handle, "RHSplinter")
        self.assertEqual(len(rt.requests), 1)
        self.assertFalse(rt.exists(STATE_FILE))

    def test_a_new_user_is_shown_even_when_it_cannot_be_remembered(self):
        other = other_payload()
        rt = self.launched(Reply(self.payload), Reply(other))
        os.makedirs(rt.host(STATE_FILE))
        rt.enter_user("octocat")
        rt.frames_for(6)
        self.assertEqual(rt.app.handle, "octocat")
        self.assertIn(summary_text(other["total_contributions"]), rt.texts())

    def test_an_empty_name_is_refused(self):
        rt = self.launched(Reply(self.payload))
        rt.press("MENU")
        for _ in range(10):
            rt.press("BACK")
        rt.goto_key("OK")
        rt.press("SELECT")
        self.assertIsNotNone(rt.app.editor)
        self.assertEqual(rt.app.editor.error, "Type a username first")
        self.assertIn("Type a username first", rt.texts())
        self.assertEqual(len(rt.requests), 1)
        self.assertFalse(rt.exists(STATE_FILE))

    def test_typing_clears_the_error(self):
        rt = self.launched(Reply(self.payload))
        rt.press("MENU")
        for _ in range(10):
            rt.press("BACK")
        rt.goto_key("OK")
        rt.press("SELECT")
        rt.goto_key("a")
        rt.press("SELECT")
        self.assertIsNone(rt.app.editor.error)
        self.assertNotIn("Type a username first", rt.texts())

    def test_names_stop_at_39_characters(self):
        rt = self.launched(Reply(self.payload))
        rt.press("MENU")
        rt.clear_text()
        rt.type_text("a" * 41)
        self.assertEqual(rt.app.editor.text, "a" * 39)
        self.assertEqual(rt.app.editor.error, "That is the longest a username can be")
        rt.goto_key("OK")
        rt.press("SELECT")
        self.assertEqual(rt.requests[-1].url, "https://github.com/{}.contribs".format("a" * 39))

    def test_the_same_user_in_another_case_refreshes_right_away(self):
        rt = self.launched(Reply(self.payload), Reply(self.payload, pumps=20))
        rt.enter_user("rhsplinter")
        self.assertEqual(rt.app.handle, "rhsplinter")
        self.assertEqual(len(rt.requests), 2)
        self.assertEqual(rt.requests[1].url, "https://github.com/rhsplinter.contribs")
        self.assertEqual(rt.read_json(STATE_FILE), {"handle": "rhsplinter"})
        rt.frame()
        self.assertIn("@rhsplinter", rt.texts())
        self.assertIn(summary_text(self.total), rt.texts())
        self.assertEqual(footer(rt)[0], "Fetching contributions")
        rt.frames_for(30)
        self.assertEqual(rt.read_json(CACHE_FILE)["h"], "rhsplinter")
        self.assertEqual(footer(rt)[0], HINT)

    def test_a_press_just_after_the_keyboard_reopens_is_not_lost(self):
        rt = self.launched(Reply(self.payload), Reply(self.payload, pumps=100))
        rt.press("MENU")
        rt.goto_key("OK")
        rt.frame("SELECT")
        rt.frame()
        rt.frame("MENU")
        rt.frame()
        self.assertEqual(rt.app.editor.text, "RHSplinter")
        rt.frame("SELECT")
        self.assertEqual(rt.app.editor.text, "RHSplintera")

    def test_buttons_held_when_the_keyboard_opens_do_not_run_ahead(self):
        rt = self.launched(Reply(self.payload))
        rt.frame("MENU", "RIGHT")
        rt.frame("RIGHT")
        rt.frame("RIGHT")
        self.assertIn(rt.app.editor.cursor, (1, 2))
        rt.hold("RIGHT", 100)
        self.assertLessEqual(rt.app.editor.cursor, 3)


class UnknownUserTests(AppCase):
    def test_an_unknown_user_goes_back_to_the_previous_graph(self):
        for style in ("firmware", "browser"):
            with self.subTest(style):
                with tempfile.TemporaryDirectory() as root:
                    rt = self.launched(Reply(self.payload), Reply(status=404, style=style), root=root)
                    rt.enter_user("nosuchuser")
                    rt.frames_for(6)
                    app = rt.app
                    self.assertEqual(app.handle, "RHSplinter")
                    self.assertEqual(rt.read_json(STATE_FILE), {"handle": "RHSplinter"})
                    self.assertFalse(rt.exists(DOWNLOAD_FILE))
                    self.assertEqual(app.editor.text, "nosuchuser")
                    self.assertEqual(app.editor.error, "User not found")
                    self.assertIn("User not found", rt.texts())
                    rt.press("MENU")
                    self.assertIn("@RHSplinter", rt.texts())
                    self.assertIn(summary_text(self.total), rt.texts())
                    self.assertEqual(footer(rt)[0], HINT)
                    rt.wait(25 * MINUTE, step=SECOND)
                    self.assertEqual(len(rt.requests), 2)
                    rt.wait(6 * MINUTE, step=SECOND)
                    self.assertEqual(len(rt.requests), 3)
                    self.assertEqual(rt.requests[2].url, "https://github.com/RHSplinter.contribs")

    def test_a_lookup_that_fails_while_the_keyboard_is_open(self):
        rt = self.launched(Reply(self.payload), Reply(status=404, pumps=300))
        rt.enter_user("nosuchuser")
        rt.press("MENU")
        rt.frames_for(320)
        self.assertEqual(rt.app.handle, "RHSplinter")
        self.assertEqual(rt.app.editor.text, "nosuchuser")
        self.assertEqual(rt.app.editor.error, "nosuchuser was not found")
        self.assertEqual(rt.read_json(STATE_FILE), {"handle": "RHSplinter"})
        rt.press("MENU")
        self.assertIn(summary_text(self.total), rt.texts())

    def test_an_unknown_first_user_is_reported_without_retrying(self):
        for style in ("firmware", "browser"):
            with self.subTest(style):
                with tempfile.TemporaryDirectory() as root:
                    other = other_payload()
                    rt = self.launch(Reply(status=404, style=style), Reply(other), root=root,
                                     state={"handle": "ghost"})
                    rt.frames_for(6)
                    self.assertEqual(rt.app.handle, "ghost")
                    self.assertIsNone(rt.app.graph)
                    self.assertIn("User not found", rt.texts())
                    self.assertEqual(footer(rt), ("User not found - MENU change user", rt.namespace["RED"]))
                    rt.wait(10 * MINUTE, step=SECOND)
                    self.assertEqual(len(rt.requests), 1)
                    rt.enter_user("octocat")
                    rt.frames_for(6)
                    self.assertEqual(rt.app.handle, "octocat")
                    self.assertIn(summary_text(other["total_contributions"]), rt.texts())
                    self.assertEqual(rt.read_json(STATE_FILE), {"handle": "octocat"})
                    self.assertEqual(footer(rt)[0], HINT)

    def test_two_unknown_users_in_a_row_do_not_loop(self):
        rt = self.launch(Reply(status=404), Reply(status=404), Reply(status=404), state={"handle": "ghost"})
        rt.frames_for(6)
        rt.enter_user("nosuchuser")
        rt.frames_for(6)
        self.assertEqual(rt.app.editor.error, "User not found")
        rt.press("MENU")
        rt.wait(10 * MINUTE, step=SECOND)
        self.assertEqual(len(rt.requests), 3)
        self.assertEqual(rt.app.handle, "ghost")
        self.assertEqual(footer(rt)[0], "User not found - MENU change user")

    def test_an_unknown_user_after_a_failed_lookup_still_returns_to_the_first_graph(self):
        rt = self.launched(Reply(self.payload), Reply(error=OSError("down")), Reply(status=404))
        rt.enter_user("octocat")
        rt.frames_for(4)
        self.assertIn("Couldn't reach GitHub", rt.texts())
        rt.enter_user("ghost")
        rt.frames_for(6)
        self.assertEqual(rt.app.handle, "RHSplinter")
        self.assertEqual(rt.read_json(STATE_FILE), {"handle": "RHSplinter"})
        self.assertEqual(rt.app.editor.text, "ghost")
        self.assertEqual(rt.app.editor.error, "User not found")
        rt.press("MENU")
        self.assertIn("@RHSplinter", rt.texts())
        self.assertIn(summary_text(self.total), rt.texts())

    def test_an_unknown_user_returns_to_the_last_user_that_worked(self):
        other = other_payload()
        rt = self.launched(Reply(self.payload), Reply(other), Reply(status=404))
        rt.enter_user("octocat")
        rt.frames_for(6)
        self.assertIn(summary_text(other["total_contributions"]), rt.texts())
        rt.enter_user("ghost")
        rt.frames_for(6)
        self.assertEqual(rt.app.handle, "octocat")
        self.assertEqual(rt.read_json(STATE_FILE), {"handle": "octocat"})
        rt.press("MENU")
        self.assertIn("@octocat", rt.texts())
        self.assertIn(summary_text(other["total_contributions"]), rt.texts())

    def test_going_back_from_an_unknown_user_selects_the_newest_day_again(self):
        rt = self.launched(Reply(self.payload), Reply(status=404))
        rt.press("LEFT")
        rt.press("LEFT")
        self.assertEqual(rt.app.cursor, 352)
        rt.enter_user("ghost")
        rt.frames_for(6)
        rt.press("MENU")
        self.assertEqual(rt.app.cursor, 366)
        self.assertEqual(rt.app.view.index, 366)
        self.assertIn(date_text(366), rt.texts())
        rt.press("LEFT")
        self.assertEqual(rt.app.cursor, 359)

    def test_an_unknown_user_wipes_out_earlier_failures_and_problems(self):
        rt = self.launched(Reply(self.payload), Reply(error=OSError("one")), Reply(error=OSError("two")),
                           Reply(status=404), Reply(error=OSError("again")))
        rt.enter_user("octocat")
        rt.frames_for(4)
        rt.wait(31 * SECOND, step=SECOND)
        rt.frames_for(4)
        rt.wait(61 * SECOND, step=SECOND)
        rt.frames_for(4)
        self.assertEqual(len(rt.requests), 4)
        self.assertEqual(rt.app.handle, "RHSplinter")
        self.assertEqual(rt.app.editor.error, "User not found")
        rt.press("MENU")
        self.assertEqual(footer(rt), (HINT, rt.namespace["MUTED"]))
        rt.wait(JUST_AFTER_REFRESH, step=SECOND)
        rt.frames_for(3)
        self.assertEqual(len(rt.requests), 5)
        self.assertLessEqual(self.retry_footer(rt)[1], 30)


class NetworkProblemTests(AppCase):
    def test_failed_downloads_are_retried_after_30s_then_60s_then_2_minutes(self):
        replies = [Reply(error=OSError("ETIMEDOUT")) for _ in range(5)] + [Reply(self.payload)]
        rt = self.launch(*replies)
        rt.screen.recording = False
        starts = []
        while len(rt.requests) < 6 and rt.badge.ticks < 20 * MINUTE:
            rt.frame(ms=100)
            if len(rt.requests) > len(starts):
                starts.append(rt.badge.ticks)
        rt.screen.recording = True
        rt.frames_for(5)
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        self.assertEqual(len(gaps), 5)
        for gap, delay in zip(gaps, (30, 60, 120, 120, 120)):
            self.assertTrue(delay * SECOND <= gap <= delay * SECOND + 500, (gap, delay))
        self.assertIsNone(rt.app.problem)
        self.assertEqual(footer(rt)[0], HINT)
        self.assertIn(summary_text(self.total), rt.texts())

    def test_the_problem_and_a_countdown_are_shown_when_there_is_no_graph(self):
        rt = self.launch(Reply(error=OSError("ETIMEDOUT")), Reply(self.payload))
        rt.frames_for(3)
        texts = rt.texts()
        self.assertIn("@RHSplinter", texts)
        self.assertIn("Couldn't reach GitHub", texts)
        self.assertIn("ETIMEDOUT", texts)
        text, pen = footer(rt)
        self.assertEqual(text, "Couldn't reach GitHub - retrying in 30s")
        self.assertEqual(pen, rt.namespace["RED"])
        rt.wait(10 * SECOND, step=SECOND)
        match = RETRY_TEXT.match(footer(rt)[0])
        self.assertTrue(match and 19 <= int(match.group(2)) <= 21, footer(rt))

    def test_a_failed_refresh_keeps_the_graph_on_screen(self):
        rt = self.launched(Reply(self.payload), Reply(error=OSError("boom")), Reply(self.payload))
        rt.wait(JUST_AFTER_REFRESH, step=SECOND)
        rt.frames_for(3)
        self.assertEqual(len(rt.requests), 2)
        self.assertIn(summary_text(self.total), rt.texts())
        headline, seconds = self.retry_footer(rt)
        self.assertEqual(headline, "Couldn't reach GitHub")
        self.assertTrue(25 <= seconds <= 30, seconds)
        rt.wait(31 * SECOND, step=SECOND)
        rt.frames_for(5)
        self.assertEqual(len(rt.requests), 3)
        self.assertEqual(footer(rt)[0], HINT)

    def test_other_http_errors_are_retried(self):
        rt = self.launch(Reply(status=503), Reply(self.payload))
        rt.frames_for(4)
        self.assertIn("GitHub answered HTTP 503", rt.texts())
        self.assertEqual(footer(rt)[0], "GitHub answered HTTP 503 - retrying in 30s")
        rt.wait(31 * SECOND, step=SECOND)
        rt.frames_for(4)
        self.assertEqual(len(rt.requests), 2)
        self.assertIn(summary_text(self.total), rt.texts())
        self.assertFalse(rt.exists(DOWNLOAD_FILE))

    def test_a_failure_to_start_the_download_is_handled(self):
        rt = self.launch(Reply(raises=OSError("no route")), Reply(self.payload))
        rt.frames_for(3)
        self.assertEqual(rt.start_failures, ["https://github.com/RHSplinter.contribs"])
        self.assertIn("Couldn't reach GitHub", rt.texts())
        self.assertIn("no route", rt.texts())
        rt.wait(31 * SECOND, step=SECOND)
        rt.frames_for(4)
        self.assertIn(summary_text(self.total), rt.texts())

    def test_a_download_that_breaks_while_it_is_being_checked_is_handled(self):
        rt = self.launch(Reply(pump_raises=OSError("socket closed")), Reply(self.payload))
        rt.frames_for(4)
        self.assertIsNone(rt.app.request)
        self.assertIn("Couldn't reach GitHub", rt.texts())
        self.assertIn("socket closed", rt.texts())
        self.assertFalse(rt.exists(DOWNLOAD_FILE))
        rt.wait(31 * SECOND, step=SECOND)
        rt.frames_for(4)
        self.assertIn(summary_text(self.total), rt.texts())

    def test_unusable_downloads_are_reported_and_cleaned_up(self):
        bad_day = dict(self.payload, weeks=[{"first_day": "2025-10-26",
                                              "contribution_days": [{"count": "x", "level": 1}]}])
        cases = (
            ("not json", "this is not json"),
            ("empty", ""),
            ("too large", json.dumps(self.payload) + " " * 70000),
            ("no weeks", json.dumps({"weeks": []})),
            ("wrong shape", json.dumps({"hello": "world"})),
            ("a list", "[]"),
            ("a day that is not a number", json.dumps(bad_day)),
            ("too many weeks", json.dumps(payloads.build(weeks=55))),
        )
        for name, body in cases:
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as root:
                    rt = self.launch(Reply(body=body), root=root)
                    rt.frames_for(5)
                    self.assertIsNone(rt.app.graph)
                    self.assertEqual(rt.app.problem, ("Unexpected data from GitHub", ""))
                    self.assertIn("Unexpected data from GitHub", rt.texts())
                    self.assertFalse(rt.exists(DOWNLOAD_FILE))
                    self.assertFalse(rt.exists(CACHE_FILE))

    def test_bad_data_does_not_replace_a_good_graph(self):
        rt = self.launched(Reply(self.payload), Reply(body="garbage"))
        rt.wait(JUST_AFTER_REFRESH, step=SECOND)
        rt.frames_for(3)
        self.assertEqual(len(rt.requests), 2)
        self.assertIn(summary_text(self.total), rt.texts())
        self.assertEqual(self.retry_footer(rt)[0], "Unexpected data from GitHub")
        self.assertEqual(sum(rt.read_json(CACHE_FILE)["c"]), self.total)
        self.assertFalse(rt.exists(DOWNLOAD_FILE))

    def test_the_size_limit_is_64_kb(self):
        text = json.dumps(self.payload)
        exact = text + " " * (64 * 1024 - len(text))
        self.assertEqual(len(exact), 64 * 1024)
        rt = self.launched(Reply(body=exact))
        self.assertIsNotNone(rt.app.graph)
        with tempfile.TemporaryDirectory() as root:
            rt = self.launched(Reply(body=exact + " "), root=root)
            self.assertIsNone(rt.app.graph)

    def test_a_wifi_problem_is_shown_in_red(self):
        rt = self.launch(Reply(never=True))
        rt.wifi.failed = True
        rt.wifi.status_value = (4, "Incorrect password.")
        rt.frames_for(3)
        self.assertEqual(footer(rt), ("Incorrect password.", rt.namespace["RED"]))
        rt.wifi.failed = False
        rt.frame()
        self.assertEqual(footer(rt), ("Fetching contributions", rt.namespace["MUTED"]))

    def test_the_connection_progress_is_shown_while_waiting(self):
        rt = self.launch(Reply(never=True, state="Connecting to badge-net"))
        rt.frames_for(3)
        self.assertEqual(footer(rt), ("Connecting to badge-net", rt.namespace["MUTED"]))

    def test_a_status_error_from_the_wifi_module_does_not_crash_the_screen(self):
        rt = self.launch(Reply(never=True))
        rt.wifi.failure = lambda: 1 / 0
        rt.frames_for(3)
        self.assertEqual(footer(rt)[0], "Fetching contributions")

    def fail_twice(self, *more):
        """Two failed downloads in a row, so the next retry is 60 seconds away."""
        rt = self.launch(Reply(error=OSError("one")), Reply(error=OSError("two")), *more)
        rt.frames_for(4)
        rt.wait(31 * SECOND, step=SECOND)
        rt.frames_for(4)
        self.assertEqual(len(rt.requests), 2)
        self.assertGreater(self.retry_footer(rt)[1], 30)
        return rt

    def test_a_new_user_replaces_the_problem_of_the_old_one(self):
        other = other_payload()
        rt = self.launched(Reply(self.payload), Reply(error=OSError("boom")), Reply(other, hold=True))
        rt.wait(JUST_AFTER_REFRESH, step=SECOND)
        rt.frames_for(3)
        self.assertEqual(self.retry_footer(rt)[0], "Couldn't reach GitHub")
        rt.enter_user("octocat")
        rt.frames_for(5)
        self.assertEqual([t for t in rt.texts() if t.startswith("Couldn't")], [])
        self.assertTrue([t for t in rt.texts() if t.startswith("Loading contributions")])

    def test_a_new_user_starts_the_retry_delays_again(self):
        rt = self.fail_twice(Reply(error=OSError("three")))
        rt.enter_user("octocat")
        rt.frames_for(4)
        self.assertEqual(len(rt.requests), 3)
        self.assertLessEqual(self.retry_footer(rt)[1], 30)

    def test_select_starts_the_retry_delays_again(self):
        rt = self.fail_twice(Reply(error=OSError("three")))
        rt.press("SELECT")
        rt.frames_for(4)
        self.assertEqual(len(rt.requests), 3)
        self.assertLessEqual(self.retry_footer(rt)[1], 30)

    def test_select_during_a_download_does_not_forget_the_failures(self):
        rt = self.fail_twice(Reply(error=OSError("three"), hold=True))
        rt.wait(61 * SECOND, step=SECOND)
        rt.frames_for(4)
        self.assertEqual(len(rt.requests), 3)
        self.assertFalse(rt.requests[2].done)
        rt.press("SELECT")
        rt.requests[2].release()
        rt.frames_for(4)
        self.assertEqual(len(rt.requests), 3)
        self.assertGreater(self.retry_footer(rt)[1], 60)

    def test_a_good_refresh_starts_the_retry_delays_again(self):
        rt = self.launched(Reply(self.payload), Reply(error=OSError("one")), Reply(self.payload),
                           Reply(error=OSError("two")))
        rt.wait(JUST_AFTER_REFRESH, step=SECOND)
        rt.frames_for(3)
        self.assertEqual(len(rt.requests), 2)
        self.retry_footer(rt)
        rt.wait(31 * SECOND, step=SECOND)
        rt.frames_for(4)
        self.assertEqual(len(rt.requests), 3)
        self.assertEqual(footer(rt)[0], HINT)
        rt.wait(JUST_AFTER_REFRESH, step=SECOND)
        rt.frames_for(3)
        self.assertEqual(len(rt.requests), 4)
        self.assertLessEqual(self.retry_footer(rt)[1], 30)


class RefreshTests(AppCase):
    def test_the_graph_refreshes_every_30_minutes(self):
        newer = payloads.build(last_week_days=4)
        rt = self.launched(Reply(self.payload), Reply(newer))
        rt.wait(29 * MINUTE, step=SECOND)
        self.assertEqual(len(rt.requests), 1)
        rt.wait(2 * MINUTE, step=SECOND)
        self.assertEqual(len(rt.requests), 2)
        rt.frames_for(5)
        self.assertIn(summary_text(newer["total_contributions"]), rt.texts())
        self.assertIn("as of Oct 28", rt.texts())

    def test_the_cursor_follows_the_newest_day_when_it_was_on_it(self):
        rt = self.launched(Reply(self.payload), Reply(payloads.build(last_week_days=4)))
        self.assertEqual(rt.app.cursor, 366)
        rt.wait(31 * MINUTE, step=SECOND)
        rt.frames_for(5)
        self.assertEqual(rt.app.cursor, 367)
        self.assertIn(date_text(367), rt.texts())

    def test_a_cursor_that_was_moved_stays_on_its_date(self):
        shifted = payloads.build(first_sunday=payloads.FIRST_SUNDAY + datetime.timedelta(days=7))
        rt = self.launched(Reply(self.payload), Reply(shifted))
        for _ in range(3):
            rt.press("LEFT")
        self.assertIn(date_text(345), rt.texts())
        rt.wait(31 * MINUTE, step=SECOND)
        rt.frames_for(5)
        self.assertEqual(len(rt.requests), 2)
        self.assertEqual(rt.app.cursor, 338)
        self.assertIn(date_text(345), rt.texts())

    def test_select_refreshes_immediately_but_only_one_download_runs_at_a_time(self):
        rt = self.launched(Reply(self.payload), Reply(self.payload, pumps=10), Reply(self.payload))
        rt.press("SELECT")
        self.assertEqual(len(rt.requests), 2)
        rt.press("SELECT")
        rt.frames_for(3)
        self.assertEqual(len(rt.requests), 2)
        rt.frames_for(20)
        rt.press("SELECT")
        self.assertEqual(len(rt.requests), 3)

    def test_select_retries_straight_away_after_a_failure(self):
        rt = self.launch(Reply(error=OSError("boom")), Reply(self.payload))
        rt.frames_for(5)
        self.assertEqual(len(rt.requests), 1)
        rt.press("SELECT")
        self.assertEqual(len(rt.requests), 2)
        rt.frames_for(5)
        self.assertIn(summary_text(self.total), rt.texts())

    def test_the_keyboard_holds_back_a_refresh_until_it_closes(self):
        rt = self.launched(Reply(self.payload), Reply(self.payload))
        rt.press("MENU")
        rt.wait(35 * MINUTE, step=SECOND)
        self.assertEqual(len(rt.requests), 1)
        rt.press("MENU")
        self.assertEqual(len(rt.requests), 2)

    def test_a_late_reply_for_the_previous_user_is_discarded(self):
        other = other_payload()
        rt = self.launched(Reply(self.payload), Reply(self.payload, hold=True), Reply(other))
        rt.press("SELECT")
        self.assertEqual(len(rt.requests), 2)
        rt.enter_user("octocat")
        rt.frames_for(10)
        self.assertEqual(len(rt.requests), 2)
        self.assertIsNone(rt.app.graph)
        rt.requests[1].release()
        rt.frames_for(10)
        self.assertEqual(len(rt.requests), 3)
        self.assertEqual(rt.requests[2].url, "https://github.com/octocat.contribs")
        self.assertIn("@octocat", rt.texts())
        self.assertIn(summary_text(other["total_contributions"]), rt.texts())
        self.assertEqual(rt.read_json(CACHE_FILE)["h"], "octocat")
        self.assertFalse(rt.exists(DOWNLOAD_FILE))

    def test_a_late_reply_for_the_previous_user_is_cleaned_up_even_if_nothing_replaces_it(self):
        rt = self.launched(Reply(self.payload), Reply(self.payload, hold=True), Reply(other_payload()))
        rt.press("SELECT")
        self.assertEqual(len(rt.requests), 2)
        rt.enter_user("octocat")
        rt.press("MENU")
        rt.requests[1].release()
        rt.frames_for(5)
        self.assertEqual(len(rt.requests), 2)
        self.assertTrue(rt.requests[1].done)
        self.assertIsNone(rt.app.request)
        self.assertFalse(rt.exists(DOWNLOAD_FILE))

    def test_the_download_is_polled_once_per_frame(self):
        rt = self.launch(Reply(self.payload, pumps=6))
        rt.frame()
        request = rt.requests[0]
        for expected in range(1, 7):
            rt.frame()
            self.assertEqual(request.pumps, expected)
        self.assertIsNone(rt.app.graph)
        rt.frame()
        self.assertEqual(request.pumps, 7)
        self.assertIsNotNone(rt.app.graph)
        rt.frames_for(5)
        self.assertEqual(request.pumps, 7)


class MissingWifiTests(AppCase):
    def test_without_wifi_details_the_app_explains_and_stays_offline(self):
        rt = self.launch(Reply(self.payload), missing=["WIFI_SSID"])
        rt.frames_for(5)
        self.assertEqual(rt.missing_details.shown[-1], ["WIFI_SSID"])
        self.assertIn("@RHSplinter", rt.texts())
        rt.wait(5 * MINUTE, step=SECOND)
        rt.press("SELECT")
        self.assertEqual(rt.requests, [])
        self.assertNotIn("wifi", rt.imports)
        self.assertEqual(rt.wifi.calls, [])

    def test_a_saved_graph_is_still_shown_without_wifi(self):
        self.launched(Reply(self.payload))
        rt = self.launch(Reply(self.payload), missing=["WIFI_SSID"])
        rt.frames_for(3)
        self.assertIn(summary_text(self.total), rt.texts())
        self.assertEqual(footer(rt), ("Wi-Fi isn't set up - showing saved data", rt.namespace["MUTED"]))
        rt.wait(40 * MINUTE, step=2 * SECOND)
        rt.press("SELECT")
        self.assertEqual(rt.requests, [])
        rt.press("LEFT")
        self.assertIn(date_text(359), rt.texts())

    def test_new_users_cannot_be_looked_up_without_wifi(self):
        self.launched(Reply(self.payload))
        rt = self.launch(missing=["WIFI_SSID"])
        rt.frames_for(3)
        rt.enter_user("octocat")
        self.assertIsNotNone(rt.app.editor)
        self.assertEqual(rt.app.editor.error, "Set up Wi-Fi to look up users")
        self.assertIn("Set up Wi-Fi to look up users", rt.texts())
        self.assertEqual(rt.app.handle, "RHSplinter")
        self.assertFalse(rt.exists(STATE_FILE))
        self.assertEqual(rt.requests, [])


class ReopenTests(AppCase):
    def test_the_chosen_user_and_graph_are_still_there_after_reopening(self):
        other = other_payload()
        rt = self.launched(Reply(self.payload), Reply(other))
        rt.enter_user("octocat")
        rt.frames_for(6)
        reopened = self.launch(Reply(other, pumps=10))
        reopened.frame()
        self.assertEqual(reopened.app.handle, "octocat")
        self.assertIn("@octocat", reopened.texts())
        self.assertIn(summary_text(other["total_contributions"]), reopened.texts())
        self.assertEqual(reopened.requests[0].url, "https://github.com/octocat.contribs")

    def test_a_rejected_user_is_not_remembered(self):
        rt = self.launched(Reply(self.payload), Reply(status=404))
        rt.enter_user("nosuchuser")
        rt.frames_for(6)
        reopened = self.launch(Reply(self.payload, pumps=10))
        reopened.frame()
        self.assertEqual(reopened.app.handle, "RHSplinter")
        self.assertEqual(reopened.requests[0].url, "https://github.com/RHSplinter.contribs")
        self.assertIn(summary_text(self.total), reopened.texts())

    def test_a_half_finished_download_from_an_earlier_run_is_harmless(self):
        for name, reply in (("the new download fails", Reply(error=OSError("boom"))),
                            ("the new download works", Reply(self.payload))):
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as root:
                    rt = Runtime(root, replies=[reply])
                    rt.write_file(DOWNLOAD_FILE, "{half a download")
                    rt.start()
                    rt.frames_for(6)
                    self.assertFalse(rt.exists(DOWNLOAD_FILE))
                    self.assertEqual(rt.app.graph is not None, reply.error is None)

    def test_a_leftover_download_file_is_removed_before_a_new_download_starts(self):
        with tempfile.TemporaryDirectory() as root:
            rt = Runtime(root, replies=[Reply(self.payload, hold=True)])
            rt.write_file(DOWNLOAD_FILE, "{half a download")
            rt.start()
            rt.frames_for(3)
            self.assertEqual(len(rt.requests), 1)
            self.assertFalse(rt.requests[0].done)
            self.assertFalse(rt.exists(DOWNLOAD_FILE))


class FitSizeTests(AppCase):
    """fit_size picks the largest font size, up to the one asked for, at which a text fits."""

    def setUp(self):
        super().setUp()
        self.fit = self.launch().namespace["fit_size"]

    def test_text_that_fits_keeps_its_size(self):
        self.assertEqual(self.fit("abc", 20, 100, 12), 20)
        self.assertEqual(self.fit("", 20, 100, 12), 20)

    def test_wider_text_shrinks_in_proportion(self):
        # The test font makes a letter 0.55 of the size wide: ten letters at size 20 are 110 pixels.
        self.assertAlmostEqual(self.fit("a" * 10, 20, 100, 5), 20 * 100 / 110)
        self.assertAlmostEqual(self.fit("a" * 20, 20, 100, 5), 20 * 100 / 220)

    def test_text_is_never_shrunk_below_the_smallest_size(self):
        self.assertEqual(self.fit("a" * 40, 20, 100, 12), 12)
        self.assertEqual(self.fit("a" * 40, 20, 100, 8), 8)


class CentringTests(AppCase):
    def assertCentred(self, rt, text):
        _, x, _, size, _ = text_op(rt, text)
        self.assertAlmostEqual(x, (320 - rt.screen.measure_text(text, size)[0]) / 2, msg=text)

    def test_the_loading_screen_is_centred(self):
        rt = self.launched(Reply(error=OSError("ETIMEDOUT")))
        for text in ("@RHSplinter", "Couldn't reach GitHub", "ETIMEDOUT"):
            self.assertCentred(rt, text)

    def test_the_loading_message_stays_put_while_its_dots_come_and_go(self):
        rt = self.launch(Reply(never=True))
        seen = {}
        for _ in range(100):
            rt.frame()
            for op in rt.screen.ops:
                if op[0] == "text" and op[1].startswith("Loading contributions"):
                    seen[op[1]] = (op[2], op[5])
        self.assertEqual(sorted(seen), ["Loading contributions.", "Loading contributions..",
                                        "Loading contributions..."])
        widest = rt.screen.measure_text("Loading contributions...", 16)[0]
        for text, (x, pen) in seen.items():
            self.assertAlmostEqual(x, (320 - widest) / 2, msg=text)
            self.assertEqual(pen, rt.namespace["MUTED"])

    def test_the_wifi_setup_backdrop_is_centred(self):
        rt = self.launch(missing=["WIFI_SSID"], state={"handle": "octocat"})
        rt.frames_for(2)
        self.assertCentred(rt, "@octocat")
        self.assertEqual(text_op(rt, "@octocat")[2], 90)


class GraphLayoutTests(AppCase):
    def test_cells_are_sized_and_centred_for_any_number_of_weeks(self):
        for weeks in (1, 2, 20, 45, 46, 53, 54):
            with self.subTest(weeks=weeks):
                with tempfile.TemporaryDirectory() as root:
                    payload = payloads.build(weeks=weeks, last_week_days=7)
                    rt = self.launched(Reply(payload), root=root)
                    pitch = min(6, 318 // weeks)
                    left = (320 - (weeks * pitch - 1)) // 2
                    top = rt.namespace["GRAPH_Y"]
                    palette = rt.namespace["LEVEL_COLORS"]
                    expected = {(left + week["index"] * pitch, top + day["weekday"] * pitch, palette[day["level"]])
                                for week in payload["weeks"] for day in week["contribution_days"]}
                    drawn = {(r[1], r[2], r[5]) for r in rt.rects() if (r[3], r[4]) == (pitch - 1, pitch - 1)}
                    self.assertEqual(len(drawn), weeks * 7)
                    self.assertEqual(drawn, expected)

    def month_labels(self, rt):
        return [op for op in rt.screen.ops if op[0] == "text" and op[1] in MONTHS]

    def assertLabelsApart(self, rt, labels):
        """Every label ends at least two pixels before the next one starts."""
        labels = sorted(labels, key=lambda op: op[2])
        for (_, text, x, _, size, _), (_, _, next_x, _, _, _) in zip(labels, labels[1:]):
            self.assertLessEqual(x + rt.screen.measure_text(text, size)[0], next_x - 2 + 0.01, (text, size))

    def test_month_labels_are_grey_text_in_the_row_above_the_graph(self):
        rt = self.launched(Reply(self.payload))
        labels = self.month_labels(rt)
        self.assertEqual(len(labels), 12)
        for _, text, _, y, _, pen in labels:
            self.assertEqual((y, pen), (rt.namespace["MONTHS_Y"], rt.namespace["MUTED"]), text)

    def test_a_month_that_starts_in_the_last_column_gets_no_label(self):
        # The last week starts on Sunday 1 November: a label there would run off the screen.
        payload = payloads.build(first_sunday=datetime.date(2025, 11, 2))
        for name, measure in (("a narrow font", None), ("a wide font", pessimistic)):
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as root:
                    rt = self.launched(Reply(payload), root=root, measure=measure)
                    labels = self.month_labels(rt)
                    self.assertEqual([op[1] for op in labels], list(MONTHS[10:] + MONTHS[:10]))
                    for _, text, x, _, size, _ in labels:
                        self.assertLessEqual(x + rt.screen.measure_text(text, size)[0], 318, text)

    def test_month_labels_keep_their_size_when_there_is_room(self):
        rt = self.launched(Reply(self.payload))
        self.assertEqual({op[4] for op in self.month_labels(rt)}, {rt.namespace["SMALL"]})

    def test_a_lone_month_label_keeps_its_full_size(self):
        rt = self.launched(Reply(payloads.build(weeks=1, last_week_days=7)))
        self.assertEqual([(op[1], op[4]) for op in self.month_labels(rt)], [("Oct", rt.namespace["SMALL"])])

    def test_month_labels_shrink_just_enough_to_stay_apart(self):
        # A 54-week graph puts some labels only four columns (20 pixels) apart.
        payload = payloads.build(weeks=54, last_week_days=1)
        fonts = (("narrow", None), ("average", pessimistic), ("wide", lambda text, size: len(text) * size * 0.7))
        for name, measure in fonts:
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as root:
                    rt = self.launched(Reply(payload), root=root, measure=measure)
                    labels = self.month_labels(rt)
                    self.assertGreaterEqual(len(labels), 11)
                    self.assertLabelsApart(rt, labels)
                    for _, text, _, _, size, _ in labels:
                        self.assertTrue(8 <= size <= rt.namespace["SMALL"], (text, size))
                    if measure is not None:
                        self.assertLess(labels[0][4], rt.namespace["SMALL"])

    def test_month_labels_are_not_shrunk_below_the_smallest_size(self):
        # In a font this wide even the smallest size runs into the next label. Keep them readable instead.
        rt = self.launched(Reply(payloads.build(weeks=54, last_week_days=1)),
                           measure=lambda text, size: len(text) * size)
        labels = self.month_labels(rt)
        self.assertGreaterEqual(len(labels), 11)
        self.assertEqual({op[4] for op in labels}, {8})

    def test_the_tightest_pair_decides_the_size_wherever_it_is_in_the_row(self):
        payload = payloads.build(weeks=54, last_week_days=1)
        names = [name for _, name in logic.month_labels(logic.parse_contribs(payload, "octocat"))]
        for position in range(len(names) - 1):
            wide = names[position]
            with self.subTest(wide=wide, position=position):
                with tempfile.TemporaryDirectory() as root:
                    # One label is a lot wider than the rest, so only the pair it starts can be too tight.
                    rt = self.launched(Reply(payload), root=root,
                                       measure=lambda text, size: size * (2.2 if text == wide else 1.0))
                    labels = self.month_labels(rt)
                    self.assertEqual([op[1] for op in labels], names)
                    self.assertEqual(len({op[4] for op in labels}), 1)
                    _, _, x, _, size, _ = labels[position]
                    self.assertAlmostEqual(x + 2.2 * size, labels[position + 1][2] - 2)

    def test_labels_stay_apart_however_the_months_fall(self):
        # Over 28 years every combination of month lengths and weekdays comes round.
        arrangements = {}
        sunday = datetime.date(2024, 1, 7)
        for _ in range(28 * 52 + 2):
            start = logic.days_from_civil(sunday.year, sunday.month, sunday.day)
            columns = tuple(week for week, _ in logic.month_labels(types.SimpleNamespace(start=start, weeks=54)))
            arrangements.setdefault(columns, sunday)
            sunday += datetime.timedelta(weeks=1)
        self.assertGreater(len(arrangements), 100)
        rt = self.launch(measure=pessimistic)
        for columns, first in arrangements.items():
            with self.subTest(first=str(first)):
                graph = logic.parse_contribs(payloads.build(first_sunday=first, weeks=54, last_week_days=1), "octocat")
                view = rt.namespace["GraphView"](graph, "octocat")
                self.assertEqual(len(view.labels), len(columns))
                for (x, name), (next_x, _) in zip(view.labels, view.labels[1:]):
                    self.assertLessEqual(x + rt.screen.measure_text(name, view.label_size)[0], next_x - 2 + 0.01)


class GraphDetailsTests(AppCase):
    def test_the_day_panel_matches_the_level_of_the_selected_day(self):
        counts = {366: 0, 365: 2, 364: 5, 363: 9, 362: 14}
        rt = self.launched(Reply(payloads.build(count_for=lambda i: counts.get(i, 0))))
        ns = rt.namespace
        for level, index in enumerate((366, 365, 364, 363, 362)):
            with self.subTest(level=level):
                self.assertEqual(payloads.level_for(counts[index]), level)
                self.assertEqual(rt.app.cursor, index)
                swatch = [op for op in rt.rects() if (op[3], op[4]) == (14, 14)]
                self.assertEqual(len(swatch), 1)
                self.assertEqual(swatch[0][5], ns["LEVEL_COLORS"][level])
                self.assertTrue(ns["PANEL_Y"] <= swatch[0][2] < ns["PANEL_Y"] + ns["PANEL_H"])
                self.assertEqual(text_op(rt, count_text(counts[index]))[4], ns["LIME"] if level else ns["MUTED"])
                rt.press("UP")

    def test_the_legend_runs_from_the_palest_to_the_darkest_shade(self):
        rt = self.launched(Reply(self.payload))
        ns = rt.namespace
        swatches = sorted((op[1], op[2], op[5]) for op in rt.rects() if (op[3], op[4]) == (8, 8))
        self.assertEqual([s[2] for s in swatches], list(ns["LEVEL_COLORS"]))
        self.assertEqual({s[1] for s in swatches}, {ns["LEGEND_Y"] + 2})
        self.assertEqual({b[0] - a[0] for a, b in zip(swatches, swatches[1:])}, {11})
        _, less_x, less_y, size, _ = text_op(rt, "Less")
        _, more_x, more_y, _, _ = text_op(rt, "More")
        self.assertEqual((less_y, more_y), (ns["LEGEND_Y"], ns["LEGEND_Y"]))
        self.assertAlmostEqual(less_x + rt.screen.measure_text("Less", size)[0] + 4, swatches[0][0])
        self.assertAlmostEqual(swatches[-1][0] + 8 + 4, more_x)
        self.assertAlmostEqual(more_x + rt.screen.measure_text("More", size)[0], 320 - ns["MARGIN"])

    def test_the_numbers_under_the_graph_are_bright_and_their_labels_grey(self):
        rt = self.launched(Reply(self.payload))
        ns = rt.namespace
        texts = [op for op in rt.screen.ops if op[0] == "text"]
        self.assertEqual([op[5] for op in texts if op[3] == ns["STATS_Y"]], [ns["LIME"]] * 3)
        self.assertEqual([op[5] for op in texts if op[3] == ns["STATS_Y"] + 24], [ns["MUTED"]] * 3)

    def test_each_number_stays_inside_its_own_column(self):
        for name, count in (("a year of activity", 1), ("huge numbers", 123456)):
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as root:
                    payload = payloads.build(count_for=lambda i: count)
                    rt = self.launched(Reply(payload), root=root, measure=pessimistic)
                    ns = rt.namespace
                    numbers = [op for op in rt.screen.ops if op[0] == "text" and op[3] == ns["STATS_Y"]]
                    self.assertEqual(len(numbers), 3)
                    for _, text, _, _, size, _ in numbers:
                        self.assertLessEqual(pessimistic(text, size), ns["STAT_WIDTH"] - 4 + 1e-9, text)

    def test_the_loading_screen_colours(self):
        rt = self.launched(Reply(error=OSError("ETIMEDOUT")))
        ns = rt.namespace
        self.assertEqual(text_op(rt, "@RHSplinter")[4], ns["TEXT"])
        self.assertEqual(text_op(rt, "Couldn't reach GitHub")[4], ns["RED"])
        self.assertEqual(text_op(rt, "ETIMEDOUT")[4], ns["MUTED"])


class KeyboardLookTests(AppCase):
    def setUp(self):
        super().setUp()
        self.rt = self.launched(Reply(self.payload))
        self.ns = self.rt.namespace
        self.rt.press("MENU")

    def look(self, key):
        """(key colour, label colour) of one key on the screen."""
        ns = self.ns
        x, y = ns["KEY_POSITIONS"][logic.KEYS.index(key)]
        faces = [op[5] for op in self.rt.rects() if op[1:5] == (x, y, ns["KEY_W"], ns["KEY_H"])]
        labels = [op[5] for op in self.rt.screen.ops
                  if op[0] == "text" and x <= op[2] < x + ns["KEY_W"] and y <= op[3] < y + ns["KEY_H"]]
        self.assertEqual((len(faces), len(labels)), (1, 1), key)
        return faces[0], labels[0]

    def test_keys_are_coloured_by_what_they_do(self):
        rt, ns = self.rt, self.ns
        self.assertEqual(self.look("a"), (ns["LIME"], ns["BG"]))
        self.assertEqual(self.look("OK"), (ns["GREEN"], ns["TEXT"]))
        self.assertEqual(self.look("DEL"), (ns["PANEL"], ns["RED"]))
        for key in logic.KEYS:
            if key not in ("a", "OK", "DEL"):
                self.assertEqual(self.look(key), (ns["PANEL"], ns["TEXT"]), key)
        rt.goto_key("OK")
        self.assertEqual(self.look("OK"), (ns["LIME"], ns["BG"]))
        self.assertEqual(self.look("a"), (ns["PANEL"], ns["TEXT"]))

    def test_the_shift_key_lights_up_while_shift_is_on(self):
        rt, ns = self.rt, self.ns
        rt.goto_key("Aa")
        rt.press("SELECT")
        rt.press("RIGHT")
        self.assertEqual(self.look("Aa"), (ns["MUTED"], ns["BG"]))
        self.assertIn("A", rt.texts())
        self.assertNotIn("a", rt.texts())
        rt.goto_key("Aa")
        rt.press("SELECT")
        rt.press("RIGHT")
        self.assertEqual(self.look("Aa"), (ns["PANEL"], ns["TEXT"]))
        self.assertIn("a", rt.texts())

    def test_an_empty_box_shows_a_grey_placeholder(self):
        rt = self.rt
        self.assertNotIn("username", rt.texts())
        rt.clear_text()
        self.assertEqual(text_op(rt, "username")[4], self.ns["MUTED"])
        rt.type_text("a")
        self.assertNotIn("username", rt.texts())

    def test_the_line_under_the_box_is_a_hint_or_a_red_error(self):
        rt, ns = self.rt, self.ns
        hint = "SELECT types the highlighted key"
        _, _, hint_y, _, pen = text_op(rt, hint)
        self.assertEqual(pen, ns["MUTED"])
        rt.clear_text()
        rt.goto_key("OK")
        rt.press("SELECT")
        self.assertNotIn(hint, rt.texts())
        _, _, error_y, _, pen = text_op(rt, "Type a username first")
        self.assertEqual((error_y, pen), (hint_y, ns["RED"]))
        rt.goto_key("a")
        rt.press("SELECT")
        self.assertIn(hint, rt.texts())

    def test_the_footer_explains_back_and_menu(self):
        _, x, y, _, pen = text_op(self.rt, "BACK delete   MENU cancel")
        self.assertEqual((x, y, pen), (self.ns["MARGIN"], self.ns["FOOTER_Y"] - 4, self.ns["MUTED"]))

    def test_the_caret_blinks_at_the_end_of_the_text(self):
        rt, ns = self.rt, self.ns
        caret_size = (2, ns["FIELD_H"] - 12)
        text_start = ns["FIELD_X"] + 12

        def carets_over(frames):
            """The caret's (x, y) on each frame that shows one."""
            shown = []
            for _ in range(frames):
                rt.frame()
                found = [op[1:3] for op in rt.rects() if op[5] == ns["LIME"] and (op[3], op[4]) == caret_size]
                if found:
                    shown.append(found)
            return shown

        shown = carets_over(70)
        self.assertTrue(20 <= len(shown) <= 50, len(shown))
        end = text_start + int(rt.screen.measure_text("RHSplinter", 22)[0]) + 2
        for found in shown:
            self.assertEqual(found, [(end, ns["FIELD_Y"] + 6)])
        rt.clear_text()
        shown = carets_over(70)
        self.assertTrue(20 <= len(shown) <= 50, len(shown))
        for found in shown:
            self.assertEqual(found, [(text_start + 2, ns["FIELD_Y"] + 6)])


class ScreenFitTests(AppCase):
    def assertFits(self, rt, name):
        self.assertTrue(rt.screen.ops, name)
        for op in rt.screen.ops:
            kind = op[0]
            if kind == "rect":
                self.assertInside(name, op, op[1], op[2], op[3], op[4])
            elif kind == "shape":
                outline = op[1]
                self.assertInside(name, op, outline[1], outline[2], outline[3], outline[4])
            elif kind == "text":
                _, text, x, y, size, _ = op
                self.assertInside(name, op, x, y, pessimistic(text, size), size)
        self.assertNoOverlap(rt, name)

    def assertInside(self, name, op, x, y, w, h):
        self.assertTrue(x >= 0 and y >= 0 and x + w <= 320 and y + h <= 240, (name, op, w))

    def assertNoOverlap(self, rt, name):
        """No two pieces of text may share any pixels."""
        boxes = [(op, op[2], op[3], op[2] + pessimistic(op[1], op[4]), op[3] + op[4])
                 for op in rt.screen.ops if op[0] == "text"]
        for i, (a, ax0, ay0, ax1, ay1) in enumerate(boxes):
            for b, bx0, by0, bx1, by1 in boxes[i + 1:]:
                apart = ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0
                self.assertTrue(apart, (name, a, b))

    def test_graph_screens(self):
        cases = (
            ("default", {}),
            ("fifty-four weeks", {"weeks": 54, "last_week_days": 7}),
            ("one week", {"weeks": 1}),
            ("a single day", {"weeks": 1, "last_week_days": 1}),
            ("huge totals", {"count_for": lambda i: 3000}),
            ("enormous totals", {"count_for": lambda i: 123456}),
            ("a streak of a whole year", {"count_for": lambda i: 1}),
            ("nothing at all", {"count_for": lambda i: 0}),
            ("partial first week", {"first_week_start": 5}),
        )
        for name, options in cases:
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as root:
                    rt = self.launched(Reply(payloads.build(**options)), root=root, measure=pessimistic)
                    self.assertFits(rt, name)
                    for button in ("LEFT", "UP", "UP", "BACK"):
                        rt.press(button)
                        self.assertFits(rt, name + " " + button)

    def test_a_long_user_name_on_the_graph(self):
        rt = self.launched(Reply(self.payload), state={"handle": "a" * 39}, measure=pessimistic)
        self.assertIsNotNone(rt.app.graph)
        self.assertIn("@" + "a" * 39, rt.texts())
        self.assertFits(rt, "graph")

    def test_loading_and_problem_screens(self):
        name = "a" * 39
        errors = (
            ("loading", Reply(never=True)),
            ("long detail", Reply(error=OSError("x" * 200))),
            ("http", Reply(status=503)),
            ("bad data", Reply(body="nope")),
            ("not found", Reply(status=404)),
        )
        for label, reply in errors:
            with self.subTest(label):
                with tempfile.TemporaryDirectory() as root:
                    rt = self.launch(reply, root=root, state={"handle": name}, measure=pessimistic)
                    rt.frames_for(4)
                    self.assertFits(rt, label)
                    rt.wait(100 * SECOND, step=SECOND)
                    self.assertFits(rt, label + " later")

    def test_a_long_problem_headline_on_a_graph(self):
        rt = self.launched(Reply(self.payload), Reply(body="nope"), measure=pessimistic)
        rt.wait(JUST_AFTER_REFRESH, step=SECOND)
        rt.frames_for(3)
        self.assertEqual(self.retry_footer(rt)[0], "Unexpected data from GitHub")
        self.assertFits(rt, "problem footer")

    def test_keyboard_screens(self):
        rt = self.launched(Reply(self.payload), measure=pessimistic)
        rt.press("MENU")
        self.assertFits(rt, "keyboard")
        rt.press("RIGHT")
        self.assertFits(rt, "keyboard moved")
        rt.clear_text()
        rt.type_text("a" * 41)
        self.assertFits(rt, "full box")
        rt.goto_key("Aa")
        rt.press("SELECT")
        self.assertFits(rt, "shift")
        rt.goto_key("OK")
        rt.press("SELECT")

    def test_a_long_rejected_name_in_the_keyboard(self):
        rt = self.launched(Reply(self.payload), Reply(status=404, pumps=300), measure=pessimistic)
        rt.press("MENU")
        rt.clear_text()
        rt.type_text("b" * 39)
        rt.goto_key("OK")
        rt.press("SELECT")
        rt.press("MENU")
        rt.frames_for(320)
        self.assertTrue(rt.app.editor.error.endswith(" was not found"))
        self.assertFits(rt, "long rejected name")

    def test_the_wifi_setup_screen(self):
        rt = self.launch(missing=["WIFI_SSID"], state={"handle": "a" * 39}, measure=pessimistic)
        rt.frames_for(2)
        self.assertFits(rt, "wifi setup backdrop")

    def test_the_graph_screen_stays_within_its_drawing_budget(self):
        rt = self.launched(Reply(self.payload))
        self.assertLess(len(rt.screen.ops), 450)


class RandomUseTests(AppCase):
    """Presses buttons and lets time pass at random, checking that nothing ever breaks."""

    def make_reply(self, rng, pool):
        roll = rng.random()
        pumps = rng.randint(0, 4)
        if roll < 0.40:
            return Reply(rng.choice(pool), pumps=pumps)
        if roll < 0.50:
            return Reply(status=404, style=rng.choice(("firmware", "browser")), pumps=pumps)
        if roll < 0.58:
            return Reply(status=rng.choice((403, 500, 503)), pumps=pumps)
        if roll < 0.68:
            return Reply(error=OSError("boom"), pumps=pumps)
        if roll < 0.74:
            return Reply(body=rng.choice(("garbage", "", "[]", "{}")), pumps=pumps)
        if roll < 0.80:
            return Reply(raises=OSError("no route"))
        if roll < 0.84:
            return Reply(pump_raises=OSError("socket closed"), pumps=pumps)
        return Reply(rng.choice(pool), hold=True)

    def check_invariants(self, rt, seed, step):
        app = rt.app
        where = (seed, step)
        self.assertTrue(logic.valid_handle(app.handle), where)
        self.assertEqual(app.graph is None, app.view is None, where)
        if app.graph is not None:
            self.assertTrue(app.graph.first <= app.cursor <= app.graph.last, where)
            self.assertEqual(app.view.index, app.cursor, where)
            self.assertTrue(logic.same_handle(app.graph.handle, app.handle), where)
        if app.editor is not None:
            self.assertLessEqual(len(app.editor.text), logic.MAX_HANDLE_LENGTH, where)
        self.assertLessEqual(len([r for r in rt.requests if not r.done]), 1, where)
        if rt.exists(STATE_FILE):
            self.assertTrue(logic.valid_handle(rt.read_json(STATE_FILE)["handle"]), where)
        if rt.exists(CACHE_FILE):
            logic.graph_from_dict(rt.read_json(CACHE_FILE))
        if app.request is None:
            self.assertFalse(rt.exists(DOWNLOAD_FILE), where)

    def run_seed(self, seed):
        rng = random.Random(seed)
        pool = [self.payload, other_payload(),
                payloads.build(weeks=rng.choice((1, 20, 54)), last_week_days=rng.randint(1, 7)),
                payloads.build(first_week_start=rng.randint(0, 6))]
        replies = [self.make_reply(rng, pool) for _ in range(400)]
        with tempfile.TemporaryDirectory() as root:
            rt = self.launch(*replies, root=root)
            rt.screen.recording = False
            buttons = ("UP", "DOWN", "LEFT", "RIGHT", "SELECT", "BACK", "MENU")
            for step in range(RANDOM_STEPS):
                roll = rng.random()
                if roll < 0.45:
                    rt.press(rng.choice(buttons))
                elif roll < 0.55:
                    rt.hold(rng.choice(buttons), rng.randint(100, 1500))
                elif roll < 0.60:
                    rt.frame(*rng.sample(buttons, rng.randint(2, 3)))
                elif roll < 0.80:
                    span = rng.choice((SECOND, 10 * SECOND, 90 * SECOND, 31 * MINUTE))
                    rt.wait(span, step=max(SECOND, span // 300))
                elif roll < 0.90:
                    for request in rt.requests:
                        request.release()
                else:
                    rt.frames_for(rng.randint(1, 12))
                self.check_invariants(rt, seed, step)
            for request in rt.requests:
                request.release()
            rt.wait(5 * MINUTE, step=SECOND)
            self.check_invariants(rt, seed, "end")

    def test_random_use(self):
        for seed in range(RANDOM_SEEDS):
            with self.subTest(seed=seed):
                self.run_seed(seed)


if __name__ == "__main__":
    unittest.main()
