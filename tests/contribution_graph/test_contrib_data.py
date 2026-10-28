import ast
import datetime
import json
import unittest
from pathlib import Path

import fake_badge  # noqa: F401  (puts the app folder on sys.path)
import payloads
import contrib_data as logic

SOURCE = Path(fake_badge.APP_SOURCE)
SUNDAY = logic.parse_date("2025-10-26")


def make_graph(counts, handle="octocat", no_data_tail=0):
    """A graph starting on a Sunday, with levels derived from the counts."""
    levels = "".join(str(payloads.level_for(c)) for c in counts) + logic.NO_DATA * no_data_tail
    return logic.Graph(handle, SUNDAY, levels, list(counts) + [0] * no_data_tail)


class CalendarTests(unittest.TestCase):
    def test_matches_datetime_for_every_day_from_1970_to_2100(self):
        day = datetime.date(1970, 1, 1)
        end = datetime.date(2100, 12, 31)
        number = 0
        while day <= end:
            self.assertEqual(logic.days_from_civil(day.year, day.month, day.day), number)
            self.assertEqual(logic.civil_from_days(number), (day.year, day.month, day.day))
            self.assertEqual(logic.weekday(number), (day.weekday() + 1) % 7)
            day += datetime.timedelta(days=1)
            number += 1

    def test_parse_date(self):
        self.assertEqual(logic.parse_date("1970-01-01"), 0)
        self.assertEqual(logic.parse_date("2025-10-26"), SUNDAY)
        self.assertEqual(logic.parse_date("2024-02-29"), logic.days_from_civil(2024, 2, 29))
        self.assertEqual(logic.parse_date("2025-10-26T22:15:01Z"), SUNDAY)

    def test_parse_date_rejects_bad_input(self):
        for bad in ("2025-02-29", "2025-13-01", "2025-00-10", "2025-10-32", "2025/10/26",
                    "25-10-26", "2025-1-26", "", "abc", "2025-10-2x", None, 20251026, []):
            with self.subTest(bad=bad):
                self.assertIsNone(logic.parse_date(bad))

    def test_formatting(self):
        day = logic.parse_date("2025-10-28")
        self.assertEqual(logic.format_date(day), "2025-10-28")
        self.assertEqual(logic.long_date(day), "Tue, Oct 28, 2025")
        self.assertEqual(logic.short_date(day), "Oct 28")
        leap = logic.parse_date("2024-02-29")
        self.assertEqual(logic.long_date(leap), "Thu, Feb 29, 2024")
        self.assertEqual(logic.format_date(logic.parse_date("2026-01-05")), "2026-01-05")
        self.assertEqual(logic.short_date(logic.parse_date("2026-01-05")), "Jan 5")


class HandleTests(unittest.TestCase):
    def test_valid(self):
        for ok in ("RHSplinter", "a", "a-b", "A1-b2", "-", "x" * 39, "0"):
            with self.subTest(handle=ok):
                self.assertTrue(logic.valid_handle(ok))

    def test_invalid(self):
        for bad in ("", "x" * 40, "has space", "under_score", "dot.name", "n\u00e9", "a/b",
                    "../x", "x?y", "x#y", "x%2fy", "line\nbreak", None, 5, ["a"]):
            with self.subTest(handle=bad):
                self.assertFalse(logic.valid_handle(bad))

    def test_same_handle_ignores_case(self):
        self.assertTrue(logic.same_handle("RHSplinter", "rhsplinter"))
        self.assertFalse(logic.same_handle("RHSplinter", "octocat"))
        self.assertFalse(logic.same_handle("RHSplinter", None))
        self.assertFalse(logic.same_handle(None, None))

    def test_url(self):
        self.assertEqual(logic.contribs_url("octocat"), "https://github.com/octocat.contribs")

    def test_there_is_no_built_in_default_user(self):
        self.assertFalse(hasattr(logic, "DEFAULT_HANDLE"))


class ConfiguredHandleTests(unittest.TestCase):
    def test_a_valid_setting_is_used_as_it_is(self):
        for value in ("RHSplinter", "octocat", "a", "-", "x" * 39, "a-b-1", "0"):
            with self.subTest(value=value):
                self.assertEqual(logic.configured_handle(value), (value, ""))

    def test_surrounding_whitespace_is_trimmed(self):
        for value in (" octocat", "octocat ", "\toctocat\r\n", "\x0b\x0coctocat \t", "  octocat  "):
            with self.subTest(value=value):
                self.assertEqual(logic.configured_handle(value), ("octocat", ""))

    def test_a_blank_setting_is_not_a_username(self):
        for value in ("", " ", "   ", "\t", "\r\n", " \t\n\r\x0b\x0c ", None, 0, False, [], {}):
            with self.subTest(value=value):
                self.assertEqual(logic.configured_handle(value), (None, ""))

    def test_a_number_is_read_as_its_digits(self):
        self.assertEqual(logic.configured_handle(12345), ("12345", ""))

    def test_text_that_cannot_be_a_username_is_handed_back_for_the_error_page(self):
        for value, shown in (("@octocat", "@octocat"), ("octo cat", "octo cat"),
                             ("octo_cat", "octo_cat"), ("github.com/octocat", "github.com/octocat"),
                             (" @octocat\n", "@octocat"), ("octocat!", "octocat!"), ("-~-", "-~-"),
                             (["a"], "['a']")):
            with self.subTest(value=value):
                self.assertEqual(logic.configured_handle(value), (None, shown))

    def test_a_username_that_is_too_long_is_refused(self):
        self.assertEqual(logic.configured_handle("x" * 40), (None, "x" * 27 + "..."))

    def test_the_refused_text_is_made_printable(self):
        for value, shown in (("caf\u00e9", "caf?"), ("a\x00b", "a?b"), ("a\x7fb", "a?b"),
                             ("\u00a0", "?"), ("\u00a0octocat", "?octocat"), ("a\nb", "a?b"),
                             ("tab\there", "tab?here"), ("\U0001f419", "?"), ("a b", "a b")):
            with self.subTest(value=value):
                self.assertEqual(logic.configured_handle(value), (None, shown))

    def test_long_refused_text_is_cut_to_fit_the_screen(self):
        limit = logic.MAX_SHOWN_LENGTH
        self.assertEqual(logic.configured_handle("!" * limit), (None, "!" * limit))
        self.assertEqual(logic.configured_handle("!" * (limit + 1)), (None, "!" * (limit - 3) + "..."))
        shown = logic.configured_handle("https://github.com/" + "o" * 100)[1]
        self.assertEqual(len(shown), limit)
        self.assertTrue(shown.endswith("..."))

    def test_only_ascii_whitespace_is_trimmed(self):
        self.assertEqual(logic.configured_handle("\u00a0"), (None, "?"))
        self.assertEqual(logic.configured_handle("\u3000octocat"), (None, "?octocat"))


class TextTests(unittest.TestCase):
    def test_with_commas(self):
        for number, text in ((0, "0"), (7, "7"), (999, "999"), (1000, "1,000"),
                             (12345, "12,345"), (1234567, "1,234,567")):
            self.assertEqual(logic.with_commas(number), text)

    def test_counts(self):
        self.assertEqual(logic.count_text(0), "0 contributions")
        self.assertEqual(logic.count_text(1), "1 contribution")
        self.assertEqual(logic.count_text(1234), "1,234 contributions")
        self.assertEqual(logic.days_text(1), "1 day")
        self.assertEqual(logic.days_text(0), "0 days")
        self.assertEqual(logic.days_text(2500), "2,500 days")


class ParseTests(unittest.TestCase):
    def test_full_year(self):
        payload = payloads.build()
        graph = logic.parse_contribs(payload, "RHSplinter")
        counts = payloads.flat_counts(payload)
        self.assertEqual(graph.handle, "RHSplinter")
        self.assertEqual(graph.weeks, 53)
        self.assertEqual(len(graph.levels), 53 * 7)
        self.assertEqual(logic.weekday(graph.start), 0)
        self.assertEqual(logic.format_date(graph.start), "2025-10-26")
        self.assertEqual(graph.first, 0)
        self.assertEqual(graph.last, len(counts) - 1)
        self.assertEqual(logic.format_date(graph.day(graph.last)), "2026-10-27")
        self.assertEqual(graph.total, payload["total_contributions"])
        self.assertEqual(graph.counts[:len(counts)], counts)
        self.assertEqual(graph.levels[len(counts):], logic.NO_DATA * (53 * 7 - len(counts)))
        expected = "".join(str(d["level"]) for w in payload["weeks"] for d in w["contribution_days"])
        self.assertEqual(graph.levels[:len(counts)], expected)

    def test_cells_follow_the_weekday_of_each_date(self):
        payload = payloads.build(count_for=lambda index: index)
        graph = logic.parse_contribs(payload, "x")
        for index in range(graph.last + 1):
            self.assertEqual(graph.counts[index], index)
            self.assertEqual(logic.weekday(graph.day(index)), index % 7)

    def test_partial_first_week(self):
        payload = payloads.build(weeks=3, last_week_days=7, first_week_start=3,
                                 count_for=lambda index: index + 1)
        graph = logic.parse_contribs(payload, "x")
        self.assertEqual(logic.format_date(graph.start), "2025-10-26")
        self.assertEqual(graph.first, 3)
        self.assertEqual(graph.last, 20)
        self.assertEqual(graph.levels[:3], logic.NO_DATA * 3)
        self.assertEqual(graph.counts[3], 4)
        self.assertEqual(graph.weeks, 3)

    def test_single_day_of_data(self):
        graph = logic.parse_contribs(payloads.build(weeks=1, last_week_days=1), "x")
        self.assertEqual((graph.weeks, graph.first, graph.last), (1, 0, 0))

    def test_weeks_that_are_out_of_order_are_placed_by_date(self):
        payload = payloads.build(weeks=3, last_week_days=7, count_for=lambda index: index)
        payload["weeks"].reverse()
        graph = logic.parse_contribs(payload, "x")
        self.assertEqual(graph.counts, list(range(21)))

    def test_levels_are_clamped(self):
        payload = payloads.build(weeks=1, last_week_days=3)
        payload["weeks"][0]["contribution_days"][0]["level"] = 9
        payload["weeks"][0]["contribution_days"][1]["level"] = -3
        graph = logic.parse_contribs(payload, "x")
        self.assertEqual(graph.levels[:2], "40")

    def test_index_for_day_is_clamped_to_days_with_data(self):
        graph = logic.parse_contribs(payloads.build(weeks=3, last_week_days=3, first_week_start=2), "x")
        self.assertEqual(graph.index_for_day(graph.start + 9), 9)
        self.assertEqual(graph.index_for_day(graph.start - 40), graph.first)
        self.assertEqual(graph.index_for_day(graph.start + 400), graph.last)

    def test_rejects_unusable_data(self):
        good = payloads.build(weeks=2)

        def broken(change):
            payload = json.loads(json.dumps(good))
            change(payload)
            return payload

        cases = {
            "no weeks key": ({}, KeyError),
            "empty weeks": ({"weeks": []}, ValueError),
            "weeks not a list": ({"weeks": "x"}, ValueError),
            "not a dict": ([], TypeError),
            "none": (None, TypeError),
            "no days key": ({"weeks": [{"first_day": "2025-10-26"}]}, KeyError),
            "bad date": (broken(lambda p: p["weeks"][0].update(first_day="2025-99-99")), ValueError),
            "negative count": (broken(lambda p: p["weeks"][0]["contribution_days"][0].update(count=-1)), ValueError),
            "text count": (broken(lambda p: p["weeks"][0]["contribution_days"][0].update(count="3")), ValueError),
            "text level": (broken(lambda p: p["weeks"][0]["contribution_days"][0].update(level="2")), ValueError),
            "missing count": (broken(lambda p: p["weeks"][0]["contribution_days"][0].pop("count")), KeyError),
            "no days at all": ({"weeks": [{"first_day": "2025-10-26", "contribution_days": []}]}, ValueError),
            "too many weeks": (payloads.build(weeks=logic.MAX_WEEKS + 1), ValueError),
        }
        for name, (data, error) in cases.items():
            with self.subTest(name):
                with self.assertRaises(error):
                    logic.parse_contribs(data, "x")

    def test_largest_accepted_size(self):
        graph = logic.parse_contribs(payloads.build(weeks=logic.MAX_WEEKS, last_week_days=7), "x")
        self.assertEqual(graph.weeks, logic.MAX_WEEKS)


class CacheTests(unittest.TestCase):
    def test_round_trip_through_json(self):
        graph = logic.parse_contribs(payloads.build(), "RHSplinter")
        again = logic.graph_from_dict(json.loads(json.dumps(graph.to_dict())))
        for name in ("handle", "start", "levels", "counts", "total", "weeks", "first", "last"):
            self.assertEqual(getattr(again, name), getattr(graph, name), name)

    def test_cache_is_small(self):
        graph = logic.parse_contribs(payloads.build(), "RHSplinter")
        self.assertLess(len(json.dumps(graph.to_dict())), 3000)

    def test_rejects_damaged_caches(self):
        good = logic.parse_contribs(payloads.build(weeks=3), "octocat").to_dict()

        def damaged(**change):
            copy = dict(good)
            copy.update(change)
            return copy

        cases = {
            "not a dict": [],
            "none": None,
            "string": "cache",
            "other version": damaged(v=99),
            "no version": {k: v for k, v in good.items() if k != "v"},
            "bad handle": damaged(h="no good"),
            "no handle": damaged(h=None),
            "bad start": damaged(s="soon"),
            "start not a sunday": damaged(s="2025-10-27"),
            "levels not text": damaged(l=[0, 1]),
            "counts not a list": damaged(c="0,1"),
            "levels not whole weeks": damaged(l=good["l"][:-1], c=good["c"][:-1]),
            "empty": damaged(l="", c=[]),
            "counts length differs": damaged(c=good["c"][:-1]),
            "bad level character": damaged(l="9" + good["l"][1:]),
            "negative count": damaged(c=[-1] + good["c"][1:]),
            "text count": damaged(c=["1"] + good["c"][1:]),
            "no data at all": damaged(l=logic.NO_DATA * len(good["l"])),
            "too long": damaged(l="0" * (logic.MAX_WEEKS * 7 + 7), c=[0] * (logic.MAX_WEEKS * 7 + 7)),
        }
        for name, data in cases.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    logic.graph_from_dict(data)


class StatsTests(unittest.TestCase):
    def test_streaks_and_busiest_day(self):
        graph = make_graph([0, 1, 2, 0, 3, 3, 3,
                            0, 0, 5, 5, 0, 0, 0])
        self.assertEqual(logic.compute_stats(graph),
                         {"current": 0, "longest": 3, "active": 7, "busiest": 5})

    def test_current_streak_ends_on_the_last_day(self):
        graph = make_graph([0, 0, 0, 0, 2, 1, 1,
                            1, 4, 1, 1])
        stats = logic.compute_stats(graph)
        self.assertEqual(stats["current"], 7)
        self.assertEqual(stats["longest"], 7)
        self.assertEqual(stats["busiest"], 4)

    def test_an_empty_last_day_does_not_break_the_streak(self):
        stats = logic.compute_stats(make_graph([0, 5, 1, 2, 0]))
        self.assertEqual((stats["current"], stats["longest"]), (3, 3))

    def test_two_empty_days_do_break_it(self):
        self.assertEqual(logic.compute_stats(make_graph([4, 4, 0, 0]))["current"], 0)

    def test_no_contributions(self):
        stats = logic.compute_stats(make_graph([0] * 7))
        self.assertEqual(stats, {"current": 0, "longest": 0, "active": 0, "busiest": 0})

    def test_days_after_the_last_day_with_data_are_ignored(self):
        graph = make_graph([2, 3, 1], no_data_tail=4)
        self.assertEqual(graph.last, 2)
        self.assertEqual(logic.compute_stats(graph),
                         {"current": 3, "longest": 3, "active": 3, "busiest": 3})

    def test_days_before_the_first_day_with_data_are_ignored(self):
        graph = logic.Graph("x", SUNDAY, "...1100", [0, 0, 0, 4, 5, 0, 0])
        self.assertEqual(graph.first, 3)
        self.assertEqual(logic.compute_stats(graph),
                         {"current": 0, "longest": 2, "active": 2, "busiest": 5})

    def test_stat_lines(self):
        lines = logic.stat_lines({"current": 1, "longest": 1234, "active": 3, "busiest": 56})
        self.assertEqual(lines, (("1 day", "Current streak"),
                                 ("1,234 days", "Longest streak"),
                                 ("56", "Busiest day")))

    def test_summary_and_day_lines(self):
        graph = make_graph([0, 3, 0, 1234])
        self.assertEqual(logic.summary_text(graph), "1,237 contributions in the last year")
        self.assertEqual(logic.summary_text(make_graph([0, 0])), "No contributions in the last year")
        self.assertEqual(logic.summary_text(make_graph([1])), "1 contribution in the last year")
        self.assertEqual(logic.day_lines(graph, 0), ("Sun, Oct 26, 2025", "No contributions"))
        self.assertEqual(logic.day_lines(graph, 1), ("Mon, Oct 27, 2025", "3 contributions"))
        self.assertEqual(logic.day_lines(make_graph([1]), 0)[1], "1 contribution")


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.graph = logic.parse_contribs(payloads.build(), "x")

    def test_month_labels(self):
        self.assertEqual(logic.month_labels(self.graph),
                         [(1, "Nov"), (6, "Dec"), (10, "Jan"), (14, "Feb"), (18, "Mar"),
                          (23, "Apr"), (27, "May"), (32, "Jun"), (36, "Jul"), (40, "Aug"),
                          (45, "Sep"), (49, "Oct")])

    def test_month_labels_keep_the_first_month_when_there_is_room(self):
        graph = logic.parse_contribs(payloads.build(first_sunday=datetime.date(2025, 10, 5), weeks=10), "x")
        self.assertEqual(logic.month_labels(graph)[0], (0, "Oct"))

    def test_labels_never_get_closer_than_the_gap(self):
        for weeks in range(1, 55):
            graph = logic.parse_contribs(payloads.build(weeks=weeks, last_week_days=7), "x")
            columns = [week for week, _ in logic.month_labels(graph)]
            for a, b in zip(columns, columns[1:]):
                self.assertGreaterEqual(b - a, 4, weeks)

    def test_layout_cells(self):
        groups = logic.layout_cells(self.graph, 1, 64, 6)
        self.assertEqual(len(groups), 5)
        self.assertEqual(sum(len(g) for g in groups), self.graph.last + 1)
        for level, cells in enumerate(groups):
            for x, y in cells:
                index = (x - 1) // 6 * 7 + (y - 64) // 6
                self.assertEqual(self.graph.levels[index], str(level))
        self.assertIn((1, 64), groups[int(self.graph.levels[0])])
        last_week = self.graph.last // 7
        self.assertIn((1 + last_week * 6, 64 + (self.graph.last % 7) * 6),
                      groups[int(self.graph.levels[self.graph.last])])

    def test_layout_skips_cells_without_data(self):
        graph = logic.parse_contribs(payloads.build(weeks=2, last_week_days=2, first_week_start=4), "x")
        groups = logic.layout_cells(graph, 0, 0, 6)
        self.assertEqual(sum(len(g) for g in groups), 3 + 2)


class CursorTests(unittest.TestCase):
    def setUp(self):
        self.graph = logic.parse_contribs(payloads.build(weeks=3, last_week_days=3), "x")  # cells 0..16

    def test_day_moves(self):
        self.assertEqual(logic.move_cursor(self.graph, 5, 1), 6)
        self.assertEqual(logic.move_cursor(self.graph, 5, -1), 4)
        self.assertEqual(logic.move_cursor(self.graph, 7, -1), 6)

    def test_day_moves_stop_at_the_ends(self):
        self.assertEqual(logic.move_cursor(self.graph, 0, -1), 0)
        self.assertEqual(logic.move_cursor(self.graph, 16, 1), 16)

    def test_week_moves(self):
        self.assertEqual(logic.move_cursor(self.graph, 9, 7), 16)
        self.assertEqual(logic.move_cursor(self.graph, 9, -7), 2)
        self.assertEqual(logic.move_cursor(self.graph, 2, 7), 9)

    def test_week_move_into_the_partial_last_week_lands_on_the_last_day(self):
        self.assertEqual(logic.move_cursor(self.graph, 10, 7), 16)
        self.assertEqual(logic.move_cursor(self.graph, 13, 7), 16)

    def test_week_moves_stop_at_the_ends(self):
        self.assertEqual(logic.move_cursor(self.graph, 16, 7), 16)
        self.assertEqual(logic.move_cursor(self.graph, 3, -7), 3)
        self.assertEqual(logic.move_cursor(self.graph, 0, -7), 0)

    def test_week_move_out_of_the_last_week_stays_put(self):
        self.assertEqual(logic.move_cursor(self.graph, 14, 7), 14)
        self.assertEqual(logic.move_cursor(self.graph, 15, 7), 15)

    def test_partial_first_week(self):
        graph = logic.parse_contribs(payloads.build(weeks=3, last_week_days=7, first_week_start=3), "x")
        self.assertEqual(graph.first, 3)
        self.assertEqual(logic.move_cursor(graph, 8, -7), 3)
        self.assertEqual(logic.move_cursor(graph, 3, -1), 3)
        self.assertEqual(logic.move_cursor(graph, 3, -7), 3)

    def test_the_cursor_never_leaves_the_days_with_data(self):
        graph = logic.parse_contribs(payloads.build(weeks=4, last_week_days=2, first_week_start=5), "x")
        for start in range(graph.first, graph.last + 1):
            for step in (-7, -1, 1, 7):
                moved = logic.move_cursor(graph, start, step)
                self.assertTrue(graph.first <= moved <= graph.last, (start, step, moved))


class FirmwareError(Exception):
    """Like the HTTPException the firmware raises."""

    def __init__(self, status, message=None):
        super().__init__(message or "HTTP error {}".format(status))
        self.fetch = type("Fetch", (), {"http_status": status})()


class ErrorTests(unittest.TestCase):
    def test_http_status(self):
        cases = (
            (FirmwareError(404), 404),
            (FirmwareError(503), 503),
            (FirmwareError(404, "request failed"), 404),
            (FirmwareError(None, "HTTP error 500"), 500),
            (FirmwareError(None, "request failed"), None),
            (Exception("HTTP 2 errors, last was 502"), 502),
            (Exception("HTTP request failed after 10 attempts"), None),
            ("HTTP 404", 404),
            (Exception("HTTP 404"), 404),
            (Exception("HTTP error 503"), 503),
            (Exception("http: 429, slow down"), 429),
            (Exception("HTTP/1.1 500 Internal Server Error"), 500),
            (OSError(110, "ETIMEDOUT"), None),
            (Exception("timed out"), None),
            (Exception("connect to https://github.com failed 443"), None),
            (Exception("HTTP error"), None),
            (Exception(""), None),
            (None, None),
        )
        for error, status in cases:
            with self.subTest(error=str(error)):
                self.assertEqual(logic.http_status(error), status)

    def test_describe_error(self):
        self.assertEqual(logic.describe_error(FirmwareError(404)), ("User not found", ""))
        self.assertEqual(logic.describe_error("HTTP 404"), ("User not found", ""))
        self.assertEqual(logic.describe_error(FirmwareError(503)), ("GitHub answered HTTP 503", ""))
        self.assertEqual(logic.describe_error(ValueError("x")), ("Unexpected data from GitHub", ""))
        self.assertEqual(logic.describe_error(KeyError("weeks")), ("Unexpected data from GitHub", ""))
        self.assertEqual(logic.describe_error(TypeError("x")), ("Unexpected data from GitHub", ""))
        self.assertEqual(logic.describe_error(OSError("boom")), ("Couldn't reach GitHub", "boom"))
        self.assertEqual(logic.describe_error(RuntimeError()), ("Couldn't reach GitHub", "RuntimeError"))
        self.assertEqual(logic.describe_error("wifi down"), ("Couldn't reach GitHub", "wifi down"))
        headline, detail = logic.describe_error(OSError("x" * 200))
        self.assertEqual(len(detail), logic.MAX_DETAIL_LENGTH)
        self.assertEqual(logic.MAX_DETAIL_LENGTH, 40)

    def test_a_long_error_detail_is_cut_with_an_ellipsis(self):
        self.assertEqual(logic.describe_error(OSError("x" * 200))[1], "x" * 37 + "...")
        self.assertEqual(logic.describe_error(OSError("y" * 41))[1], "y" * 37 + "...")
        self.assertEqual(logic.describe_error(OSError("z" * 40))[1], "z" * 40)

    def test_retry_delay_grows_then_levels_off(self):
        self.assertEqual([logic.retry_delay_ms(n) for n in (0, 1, 2, 3, 4, 50)],
                         [30000, 30000, 60000, 120000, 120000, 120000])


class RepeaterTests(unittest.TestCase):
    def test_first_press_then_delay_then_interval(self):
        rep = logic.Repeater(delay=400, interval=100)
        fired = [t for t in range(0, 1000, 10) if rep.poll(True, t)]
        self.assertEqual(fired, [0, 400, 500, 600, 700, 800, 900])

    def test_releasing_resets(self):
        rep = logic.Repeater(delay=400, interval=100)
        self.assertTrue(rep.poll(True, 0))
        self.assertFalse(rep.poll(False, 50))
        self.assertTrue(rep.poll(True, 60))
        self.assertFalse(rep.poll(True, 200))

    def test_idle_never_fires(self):
        rep = logic.Repeater()
        self.assertFalse(any(rep.poll(False, t) for t in range(0, 5000, 33)))


class EditorTests(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(len(logic.KEYS), 40)
        self.assertEqual(len(set(logic.KEYS)), 40)
        singles = [k for k in logic.KEYS if len(k) == 1]
        self.assertEqual(sorted(singles), sorted("abcdefghijklmnopqrstuvwxyz0123456789-"))
        for key in singles:
            self.assertTrue(logic.valid_handle(key))

    def test_move_wraps_around_the_grid(self):
        ed = logic.Editor()
        ed.move(-1, 0)
        self.assertEqual(ed.cursor, 39)
        ed.move(1, 0)
        self.assertEqual(ed.cursor, 0)
        ed.move(0, -1)
        self.assertEqual(ed.cursor, 30)
        ed.move(0, 1)
        self.assertEqual(ed.cursor, 0)
        for _ in range(4):
            ed.move(0, 1)
        self.assertEqual(ed.cursor, 0)

    def test_every_key_can_be_reached(self):
        ed = logic.Editor()
        seen = set()
        for _ in range(len(logic.KEYS)):
            seen.add(ed.key())
            ed.move(1, 0)
        self.assertEqual(seen, set(logic.KEYS))

    def test_typing(self):
        ed = logic.Editor("ab")
        ed.cursor = logic.KEYS.index("c")
        self.assertFalse(ed.press())
        self.assertEqual(ed.text, "abc")

    def test_shift_applies_to_one_letter(self):
        ed = logic.Editor()
        ed.cursor = logic.KEYS.index(logic.SHIFT_KEY)
        ed.press()
        self.assertTrue(ed.shift)
        self.assertEqual(ed.label(logic.KEYS.index("a")), "A")
        self.assertEqual(ed.label(logic.KEYS.index("5")), "5")
        self.assertEqual(ed.label(logic.KEYS.index(logic.DELETE_KEY)), "DEL")
        self.assertEqual(ed.label(logic.KEYS.index(logic.SHIFT_KEY)), "Aa")
        self.assertEqual(ed.label(logic.KEYS.index(logic.ENTER_KEY)), "OK")
        ed.cursor = logic.KEYS.index("a")
        ed.press()
        ed.press()
        self.assertEqual(ed.text, "Aa")
        self.assertFalse(ed.shift)

    def test_shift_toggles_off(self):
        ed = logic.Editor()
        ed.cursor = logic.KEYS.index(logic.SHIFT_KEY)
        ed.press()
        ed.press()
        self.assertFalse(ed.shift)

    def test_delete(self):
        ed = logic.Editor("abc", error="x")
        ed.cursor = logic.KEYS.index(logic.DELETE_KEY)
        ed.press()
        self.assertEqual((ed.text, ed.error), ("ab", None))
        ed.backspace()
        ed.backspace()
        ed.backspace()
        self.assertEqual(ed.text, "")

    def test_ok_key_reports_done(self):
        ed = logic.Editor("abc")
        ed.cursor = logic.KEYS.index(logic.ENTER_KEY)
        self.assertTrue(ed.press())
        self.assertEqual(ed.text, "abc")

    def test_length_limit(self):
        ed = logic.Editor("x" * logic.MAX_HANDLE_LENGTH)
        ed.cursor = logic.KEYS.index("a")
        ed.press()
        self.assertEqual(len(ed.text), logic.MAX_HANDLE_LENGTH)
        self.assertIsNotNone(ed.error)

    def test_typing_clears_the_error(self):
        ed = logic.Editor("a", error="User not found")
        ed.cursor = logic.KEYS.index("b")
        ed.press()
        self.assertIsNone(ed.error)


class PortabilityTests(unittest.TestCase):
    """The badge runs MicroPython, so the logic module may not lean on much of CPython."""

    def test_logic_module_imports_nothing(self):
        tree = ast.parse((SOURCE / "contrib_data.py").read_text(encoding="utf-8"))
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [])

    def test_sources_avoid_features_micropython_lacks(self):
        banned = ("import datetime", "import typing", "import dataclasses", "import enum",
                  "import pathlib", "from __future__", "os.path", ":=", "{:,}", "key=", ".removeprefix(")
        for name in ("__init__.py", "contrib_data.py"):
            source = (SOURCE / name).read_text(encoding="utf-8")
            for text in banned:
                with self.subTest(file=name, text=text):
                    self.assertNotIn(text, source)


if __name__ == "__main__":
    unittest.main()
