"""Pure helpers for the Contribution Graph app.

Nothing in this module touches the badge runtime, so the same code runs on
the badge (MicroPython) and on a desktop for unit tests.
"""

CONTRIBS_URL = "https://github.com/{}.contribs"
MAX_HANDLE_LENGTH = 39
MAX_SHOWN_LENGTH = 30
MAX_WEEKS = 54
MAX_DETAIL_LENGTH = 40
CACHE_VERSION = 1
NO_DATA = "."
RETRY_DELAYS_MS = (30000, 60000, 120000)

_HANDLE_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
_SPACE = " \t\n\r\x0b\x0c"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


# ---------------------------------------------------------------------------
# Handles
# ---------------------------------------------------------------------------

def valid_handle(handle):
    """True for text that is safe to put in the .contribs URL.

    Only letters, digits and hyphens are allowed, up to 39 characters. GitHub
    itself decides whether the account exists.
    """
    if not isinstance(handle, str) or not 1 <= len(handle) <= MAX_HANDLE_LENGTH:
        return False
    for ch in handle:
        if ch not in _HANDLE_CHARS:
            return False
    return True


def same_handle(a, b):
    return isinstance(a, str) and isinstance(b, str) and a.lower() == b.lower()


def configured_handle(value):
    """(handle, rejected) for the GITHUB_USERNAME setting in secrets.py.

    handle is the username to use, or None when the setting can't be used.
    In that case rejected is "" for a blank setting and otherwise the text that
    was refused, as printable ASCII short enough to draw. Only ASCII
    whitespace is trimmed, so the badge and a desktop give the same answer.
    """
    text = str(value or "").strip(_SPACE)
    if valid_handle(text):
        return text, ""
    rejected = "".join(ch if " " <= ch <= "~" else "?" for ch in text)
    if len(rejected) > MAX_SHOWN_LENGTH:
        rejected = rejected[:MAX_SHOWN_LENGTH - 3] + "..."
    return None, rejected


def contribs_url(handle):
    return CONTRIBS_URL.format(handle)


# ---------------------------------------------------------------------------
# Calendar maths (no datetime module on the badge)
# ---------------------------------------------------------------------------

def days_from_civil(year, month, day):
    """Days since 1970-01-01 for a Gregorian date."""
    if month <= 2:
        year -= 1
    era = year // 400
    yoe = year - era * 400
    doy = (153 * (month + (9 if month <= 2 else -3)) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(days):
    """(year, month, day) for a day number from days_from_civil."""
    days += 719468
    era = days // 146097
    doe = days - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    year = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + 3 if mp < 10 else mp - 9
    if month <= 2:
        year += 1
    return year, month, day


def weekday(days):
    """0 for Sunday through 6 for Saturday."""
    return (days + 4) % 7


def parse_date(text):
    """Day number for 'YYYY-MM-DD' (extra characters are ignored), else None."""
    if not isinstance(text, str) or len(text) < 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        year = int(text[0:4])
        month = int(text[5:7])
        day = int(text[8:10])
    except ValueError:
        return None
    days = days_from_civil(year, month, day)
    if civil_from_days(days) != (year, month, day):
        return None
    return days


def format_date(days):
    year, month, day = civil_from_days(days)
    return "{:04d}-{:02d}-{:02d}".format(year, month, day)


def long_date(days):
    """For example 'Tue, Oct 28, 2025'."""
    year, month, day = civil_from_days(days)
    return "{}, {} {}, {}".format(_WEEKDAYS[weekday(days)], _MONTHS[month - 1], day, year)


def short_date(days):
    """For example 'Oct 28'."""
    _, month, day = civil_from_days(days)
    return "{} {}".format(_MONTHS[month - 1], day)


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def with_commas(number):
    digits = str(number)
    out = ""
    while len(digits) > 3:
        out = "," + digits[-3:] + out
        digits = digits[:-3]
    return digits + out


def count_text(count, noun="contribution"):
    return "{} {}{}".format(with_commas(count), noun, "" if count == 1 else "s")


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------

class Graph:
    """One user's contributions in a Sunday-first grid of whole weeks.

    Cell number = week * 7 + weekday, so a cell's date is start + number.
    """

    def __init__(self, handle, start, levels, counts):
        self.handle = handle
        self.start = start          # day number of cell 0, always a Sunday
        self.levels = levels        # one character per cell: "0".."4", or NO_DATA
        self.counts = counts        # contributions per cell
        self.total = sum(counts)
        self.weeks = len(levels) // 7
        self.first = 0
        while self.first < len(levels) and levels[self.first] == NO_DATA:
            self.first += 1
        self.last = len(levels) - 1
        while self.last >= 0 and levels[self.last] == NO_DATA:
            self.last -= 1

    def day(self, index):
        return self.start + index

    def index_for_day(self, day):
        """Cell number for a day number, clamped to cells that have data."""
        return clamp(day - self.start, self.first, self.last)

    def to_dict(self):
        return {"v": CACHE_VERSION, "h": self.handle, "s": format_date(self.start),
                "l": self.levels, "c": self.counts}


def clamp(value, low, high):
    return low if value < low else high if value > high else value


def parse_contribs(data, handle):
    """Build a Graph from the .contribs JSON.

    Raises ValueError, KeyError or TypeError when the data is not usable.
    Dates come from each week's first_day, so the grid is always Sunday-first
    whatever the weekday fields say.
    """
    weeks = data["weeks"]
    if not isinstance(weeks, list) or not weeks:
        raise ValueError("no weeks")
    low = high = None
    for week in weeks:
        day = parse_date(week["first_day"])
        if day is None:
            raise ValueError("bad week date")
        end = day + len(week["contribution_days"]) - 1
        if low is None or day < low:
            low = day
        if high is None or end > high:
            high = end
    start = low - weekday(low)
    cells = (high - start) // 7 * 7 + 7
    if cells > MAX_WEEKS * 7:
        raise ValueError("too many weeks")
    levels = [NO_DATA] * cells
    counts = [0] * cells
    for week in weeks:
        day = parse_date(week["first_day"])
        for entry in week["contribution_days"]:
            count = entry["count"]
            level = entry["level"]
            if not isinstance(count, int) or not isinstance(level, int) or count < 0:
                raise ValueError("bad day")
            index = day - start
            levels[index] = str(clamp(level, 0, 4))
            counts[index] = count
            day += 1
    graph = Graph(handle, start, "".join(levels), counts)
    if graph.last < 0:
        raise ValueError("no days")
    return graph


def graph_from_dict(obj):
    """Rebuild a Graph from Graph.to_dict(); raises ValueError if it is damaged."""
    if not isinstance(obj, dict) or obj.get("v") != CACHE_VERSION:
        raise ValueError("unknown cache")
    handle = obj.get("h")
    start = parse_date(obj.get("s"))
    levels = obj.get("l")
    counts = obj.get("c")
    if not valid_handle(handle) or start is None or weekday(start) != 0:
        raise ValueError("bad cache header")
    if not isinstance(levels, str) or not isinstance(counts, list):
        raise ValueError("bad cache body")
    size = len(levels)
    if size == 0 or size % 7 or size > MAX_WEEKS * 7 or len(counts) != size:
        raise ValueError("bad cache size")
    for ch in levels:
        if ch not in "01234" + NO_DATA:
            raise ValueError("bad level")
    for count in counts:
        if not isinstance(count, int) or count < 0:
            raise ValueError("bad count")
    graph = Graph(handle, start, levels, counts)
    if graph.last < 0:
        raise ValueError("no days")
    return graph


# ---------------------------------------------------------------------------
# Numbers shown on screen
# ---------------------------------------------------------------------------

def compute_stats(graph):
    """Streaks and the busiest day.

    The current streak counts back from the last day. If that day has no
    contributions yet it is skipped rather than ending the streak, because
    the day is not over.
    """
    counts = graph.counts
    longest = run = active = busiest = 0
    for i in range(graph.first, graph.last + 1):
        n = counts[i]
        if n > 0:
            run += 1
            active += 1
            if run > longest:
                longest = run
            if n > busiest:
                busiest = n
        else:
            run = 0
    i = graph.last
    if counts[i] == 0:
        i -= 1
    current = 0
    while i >= graph.first and counts[i] > 0:
        current += 1
        i -= 1
    return {"current": current, "longest": longest, "active": active, "busiest": busiest}


def days_text(count):
    return "{} day{}".format(with_commas(count), "" if count == 1 else "s")


def summary_text(graph):
    if graph.total == 0:
        return "No contributions in the last year"
    return count_text(graph.total) + " in the last year"


def day_lines(graph, index):
    """(date, contributions) text for one cell."""
    n = graph.counts[index]
    return long_date(graph.day(index)), ("No contributions" if n == 0 else count_text(n))


def stat_lines(stats):
    """(value, label) text for the three numbers under the graph."""
    return (
        (days_text(stats["current"]), "Current streak"),
        (days_text(stats["longest"]), "Longest streak"),
        (with_commas(stats["busiest"]), "Busiest day"),
    )


def month_labels(graph, min_gap=4):
    """(week column, 'Oct') pairs, one per month, for the row above the graph.

    A month is labelled at the first week that starts in it. A label that
    would sit closer than min_gap columns to the next is dropped, which
    removes the partial month at the left edge.
    """
    labels = []
    previous = None
    for week in range(graph.weeks):
        month = civil_from_days(graph.start + week * 7)[1]
        if month != previous:
            previous = month
            if labels and week - labels[-1][0] < min_gap:
                labels.pop()
            labels.append((week, _MONTHS[month - 1]))
    return labels


def layout_cells(graph, x0, y0, pitch):
    """Pixel position of every cell, in five lists (one per level) of (x, y)."""
    groups = [[], [], [], [], []]
    levels = graph.levels
    for i in range(len(levels)):
        ch = levels[i]
        if ch != NO_DATA:
            groups[int(ch)].append((x0 + (i // 7) * pitch, y0 + (i % 7) * pitch))
    return groups


def move_cursor(graph, index, step):
    """Move the day cursor by one day (+-1) or one week (+-7).

    Moves that would leave the data stay put, except that a week move into
    a partial first or last week lands on the nearest day that has data.
    """
    target = index + step
    if step == 7 or step == -7:
        if target < 0 or target >= len(graph.levels):
            return index
        return clamp(target, graph.first, graph.last)
    if target < graph.first or target > graph.last:
        return index
    return target


# ---------------------------------------------------------------------------
# Errors from the fetch layer
# ---------------------------------------------------------------------------

def http_status(error):
    """The HTTP status carried by a fetch error, or None for other failures.

    The firmware raises an HTTPException that holds fetch.http_status; the
    browser simulator reports plain text such as "HTTP 404".
    """
    status = getattr(getattr(error, "fetch", None), "http_status", None)
    if isinstance(status, int):
        return status
    text = str(error)
    if text.strip().upper().startswith("HTTP"):
        for word in text.replace(":", " ").replace(",", " ").split():
            if len(word) == 3 and word.isdigit():
                return int(word)
    return None


def describe_error(error):
    """(headline, detail) for an error from the download or the parser."""
    status = http_status(error)
    if status == 404:
        return "User not found", ""
    if status is not None:
        return "GitHub answered HTTP {}".format(status), ""
    if isinstance(error, (ValueError, KeyError, TypeError)):
        return "Unexpected data from GitHub", ""
    text = str(error) or type(error).__name__
    if len(text) > MAX_DETAIL_LENGTH:
        text = text[:MAX_DETAIL_LENGTH - 3] + "..."
    return "Couldn't reach GitHub", text


def retry_delay_ms(failures):
    """How long to wait before trying again after this many failures in a row."""
    return RETRY_DELAYS_MS[clamp(failures, 1, len(RETRY_DELAYS_MS)) - 1]


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

class Repeater:
    """Turns a held button into repeated actions.

    poll() is True on the first frame the button is down, again after
    `delay` ms, then every `interval` ms while it stays down.
    """

    def __init__(self, delay=380, interval=90):
        self.delay = delay
        self.interval = interval
        self.due = None

    def poll(self, down, now):
        if not down:
            self.due = None
            return False
        if self.due is None:
            self.due = now + self.delay
            return True
        if now >= self.due:
            self.due = now + self.interval
            return True
        return False


KEY_ROWS = ("abcdefghij", "klmnopqrst", "uvwxyz0123", "456789-")
SHIFT_KEY = "Aa"
DELETE_KEY = "DEL"
ENTER_KEY = "OK"
KEYS = tuple(ch for row in KEY_ROWS for ch in row) + (SHIFT_KEY, DELETE_KEY, ENTER_KEY)
KEY_COLUMNS = 10


class Editor:
    """Text and key selection for the on-screen username keyboard."""

    def __init__(self, text="", error=None):
        self.text = text
        self.error = error
        self.cursor = 0
        self.shift = False

    def move(self, dx, dy):
        """Move the highlighted key, wrapping around the 10 x 4 grid."""
        self.cursor = (self.cursor + dx + dy * KEY_COLUMNS) % len(KEYS)

    def key(self):
        return KEYS[self.cursor]

    def label(self, index):
        key = KEYS[index]
        return key.upper() if self.shift and len(key) == 1 else key

    def type(self, ch):
        if len(self.text) >= MAX_HANDLE_LENGTH:
            self.error = "That is the longest a username can be"
            return
        if self.shift:
            ch = ch.upper()
            self.shift = False
        self.text += ch
        self.error = None

    def backspace(self):
        self.text = self.text[:-1]
        self.error = None

    def press(self):
        """Press the highlighted key. True means the OK key was pressed."""
        key = self.key()
        if key == ENTER_KEY:
            return True
        if key == SHIFT_KEY:
            self.shift = not self.shift
        elif key == DELETE_KEY:
            self.backspace()
        else:
            self.type(key)
        return False
