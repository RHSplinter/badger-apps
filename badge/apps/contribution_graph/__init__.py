"""Contribution Graph: any GitHub user's yearly contribution heatmap."""

import gc
import json
import os
import sys

APP_DIR = "/system/apps/contribution_graph"
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

import fetch
import missing_details

try:
    import secrets
except ImportError:
    secrets = None

import contrib_data as logic

badge.mode(HIRES | VSYNC)
screen.antialias = image.X2

# github.com answers with very large headers
fetch.AsyncFetch.MAX_HEADER_BYTES = 8192

MISSING = missing_details.missing("WIFI_SSID")
if MISSING:
    wifi = None
else:
    import wifi

# The user to show comes from GITHUB_USERNAME in secrets.py. CONFIGURED is None
# when that can't be used, and REJECTED is then the text that was refused.
CONFIGURED, REJECTED = logic.configured_handle(getattr(secrets, "GITHUB_USERNAME", ""))

try:
    FONT = missing_details.mona_sans()
except Exception:
    FONT = font.nope
screen.font = FONT

STATE_DIR = "/state"
CACHE_FILE = STATE_DIR + "/contribution_graph_cache.json"
DOWNLOAD_FILE = STATE_DIR + "/contribution_graph_download.json"
OLD_USER_FILE = STATE_DIR + "/contribution_graph.json"
HEADERS = {"User-Agent": "GitHub Universe Badge 2026"}
REFRESH_MS = 30 * 60 * 1000
MAX_DOWNLOAD_BYTES = 64 * 1024
WIFI_TIMEOUT = 10
WIFI_RETRIES = 100000
HINT = "MENU change user   SELECT refresh"

BG = color.rgb(13, 17, 23)
PANEL = color.rgb(22, 27, 34)
TEXT = color.rgb(230, 237, 243)
MUTED = color.rgb(139, 148, 158)
LIME = color.rgb(211, 250, 55)
RED = color.rgb(255, 123, 114)
WHITE = color.rgb(255, 255, 255)
GREEN = color.rgb(0, 109, 50)
LEVEL_COLORS = (
    color.rgb(33, 40, 49),
    color.rgb(14, 68, 41),
    color.rgb(0, 109, 50),
    color.rgb(38, 166, 65),
    color.rgb(57, 211, 83),
)

WIDTH = screen.width
MARGIN = 8
TITLE_SIZE = 20
SUMMARY_SIZE = 13
STAT_SIZE = 20
SMALL = 11
HINT_SIZE = 12

TITLE_Y = 6
SUMMARY_Y = 31
MONTHS_Y = 51
GRAPH_Y = 64
LEGEND_Y = 111
LEGEND_CELL = 8
LEGEND_GAP = 3
PANEL_Y = 130
PANEL_H = 42
STATS_Y = 181
FOOTER_Y = 224
STAT_WIDTH = (WIDTH - 2 * MARGIN) // 3

FIELD_X, FIELD_Y, FIELD_W, FIELD_H = MARGIN, 28, WIDTH - 2 * MARGIN, 36
KEY_W, KEY_H, KEY_PITCH_X, KEY_PITCH_Y = 28, 29, 30, 31
KEYS_X = (WIDTH - (logic.KEY_COLUMNS * KEY_PITCH_X - 2)) // 2
KEYS_Y = 86

SETUP_TITLE_Y = 14
SETUP_BODY_TOP = 40
SETUP_BODY_BOTTOM = 130
SETUP_LINE_GAP = 8
SETUP_PANEL_Y = 136
SETUP_PANEL_H = 38
SETUP_AFTER_Y = 186
SETUP_EXAMPLE = 'GITHUB_USERNAME = "your-handle"'

PANEL_SHAPE = shape.rounded_rectangle(MARGIN, PANEL_Y, WIDTH - 2 * MARGIN, PANEL_H, 6)
FIELD_SHAPE = shape.rounded_rectangle(FIELD_X, FIELD_Y, FIELD_W, FIELD_H, 6)
SETUP_SHAPE = shape.rounded_rectangle(MARGIN, SETUP_PANEL_Y, WIDTH - 2 * MARGIN, SETUP_PANEL_H, 6)
KEY_POSITIONS = [
    (KEYS_X + (i % logic.KEY_COLUMNS) * KEY_PITCH_X, KEYS_Y + (i // logic.KEY_COLUMNS) * KEY_PITCH_Y)
    for i in range(len(logic.KEYS))
]
key_widths = {}

try:
    os.mkdir(STATE_DIR)
except OSError:
    pass


def remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def read_cache(handle):
    try:
        with open(CACHE_FILE) as f:
            cached = logic.graph_from_dict(json.load(f))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return cached if logic.same_handle(cached.handle, handle) else None


def write_cache(graph):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(graph.to_dict(), f)
    except OSError:
        pass


def fit_size(string, size, max_width, min_size):
    width, _ = screen.measure_text(string, font_size=size)
    if width > max_width:
        size = max(min_size, size * max_width / width)
    return size


def draw_text(string, x, y, size, pen):
    screen.pen = pen
    screen.text(string, x, y, size)


def center_text(string, y, size, pen):
    width, _ = screen.measure_text(string, font_size=size)
    draw_text(string, (WIDTH - width) / 2, y, size, pen)


def center_fit(string, y, size, min_size, pen):
    center_text(string, y, fit_size(string, size, WIDTH - 2 * MARGIN, min_size), pen)


def key_width(label, size):
    pair = (label, size)
    if pair not in key_widths:
        key_widths[pair] = screen.measure_text(label, font_size=size)[0]
    return key_widths[pair]


def fire(repeater, button):
    return repeater.poll(badge.pressed(button) or badge.held(button), badge.ticks)


def network_status(req):
    """(text, failed) for a download that is still in progress."""
    try:
        if wifi is not None and wifi.failure():
            return wifi.status()[1], True
    except Exception:
        pass
    state = req.state
    if state in ("Idle", "Fetching", "Done"):
        return "Fetching contributions", False
    return state, False


class GraphView:
    """Everything about a graph that is worked out once instead of every frame."""

    def __init__(self, graph, handle):
        self.graph = graph
        weeks = graph.weeks
        self.pitch = min(6, (WIDTH - 2) // weeks)
        self.cell = self.pitch - 1
        self.x0 = (WIDTH - (weeks * self.pitch - 1)) // 2
        self.groups = logic.layout_cells(graph, self.x0, GRAPH_Y, self.pitch)

        labels = []
        for week, name in logic.month_labels(graph):
            x = self.x0 + week * self.pitch
            width, _ = screen.measure_text(name, font_size=SMALL)
            if x + width <= WIDTH - 2:
                labels.append((x, name))
        # Labels sit as little as four columns apart on a 54-week graph; shrink them just enough to keep clear.
        self.label_size = SMALL
        for i in range(len(labels) - 1):
            room = labels[i + 1][0] - labels[i][0] - 2
            self.label_size = min(self.label_size, fit_size(labels[i][1], SMALL, room, 8))
        self.labels = labels

        self.title = "@" + handle
        self.title_size = fit_size(self.title, TITLE_SIZE, WIDTH - 2 * MARGIN, 12)
        self.summary = logic.summary_text(graph)
        self.summary_size = fit_size(self.summary, SUMMARY_SIZE, WIDTH - 2 * MARGIN, 9)
        self.as_of = "as of " + logic.short_date(graph.day(graph.last))
        self.stats = logic.stat_lines(logic.compute_stats(graph))
        self.stat_sizes = [fit_size(value, STAT_SIZE, STAT_WIDTH - 4, 12) for value, _ in self.stats]

        less_width, _ = screen.measure_text("Less", font_size=SMALL)
        more_width, _ = screen.measure_text("More", font_size=SMALL)
        swatches = 5 * LEGEND_CELL + 4 * LEGEND_GAP
        self.more_x = WIDTH - MARGIN - more_width
        self.swatch_x = self.more_x - 4 - swatches
        self.less_x = self.swatch_x - 4 - less_width

        self.select(graph.last)

    def select(self, index):
        self.index = index
        self.day_date, self.day_count = logic.day_lines(self.graph, index)
        level = self.graph.levels[index]
        self.day_level = 0 if level == logic.NO_DATA else int(level)
        self.cx = self.x0 + (index // 7) * self.pitch
        self.cy = GRAPH_Y + (index % 7) * self.pitch


class App:
    def __init__(self):
        # The app opens on the user from secrets.py. Earlier versions saved the last user here.
        remove(OLD_USER_FILE)
        self.handle = CONFIGURED
        self.graph = read_cache(self.handle)
        self.view = None
        self.cursor = 0
        self.editor = None
        self.request = None
        self.request_handle = ""
        self.previous = None      # (handle, graph) to return to if a new user is not found
        self.problem = None       # (headline, detail) of the latest failure
        self.failures = 0
        self.next_fetch_at = None if MISSING or self.handle is None else 0
        self.repeaters = []
        self.rep_up = self.new_repeater()
        self.rep_down = self.new_repeater()
        self.rep_left = self.new_repeater()
        self.rep_right = self.new_repeater()
        self.rep_back = self.new_repeater()
        self.rep_select = self.new_repeater()
        if self.graph is not None:
            self.cursor = self.graph.last
            self.view = GraphView(self.graph, self.handle)
        if wifi is not None:
            wifi.connect(timeout=WIFI_TIMEOUT, retries=WIFI_RETRIES)

    def new_repeater(self):
        repeater = logic.Repeater()
        self.repeaters.append(repeater)
        return repeater

    def set_editor(self, editor):
        """Open or close the keyboard; held buttons must not carry over."""
        self.editor = editor
        for repeater in self.repeaters:
            repeater.due = None

    # -- frame ---------------------------------------------------------

    def step(self):
        if self.editor is not None:
            self.editor_input()
        else:
            self.main_input()
        self.poll_network()
        self.draw()

    # -- input ---------------------------------------------------------

    def main_input(self):
        left = fire(self.rep_left, BUTTON_LEFT)
        right = fire(self.rep_right, BUTTON_RIGHT)
        up = fire(self.rep_up, BUTTON_UP)
        down = fire(self.rep_down, BUTTON_DOWN)
        if self.graph is not None:
            step = -7 if left else 7 if right else -1 if up else 1 if down else 0
            if step:
                moved = logic.move_cursor(self.graph, self.cursor, step)
                if moved != self.cursor:
                    self.cursor = moved
                    self.view.select(moved)
            if badge.pressed(BUTTON_BACK):
                self.cursor = self.graph.last
                self.view.select(self.cursor)
        if badge.pressed(BUTTON_SELECT):
            self.refresh_now()
        if badge.pressed(BUTTON_MENU):
            self.open_editor(self.handle or "")

    def editor_input(self):
        ed = self.editor
        dx = (1 if fire(self.rep_right, BUTTON_RIGHT) else 0) - (1 if fire(self.rep_left, BUTTON_LEFT) else 0)
        dy = (1 if fire(self.rep_down, BUTTON_DOWN) else 0) - (1 if fire(self.rep_up, BUTTON_UP) else 0)
        if dx or dy:
            ed.move(dx, dy)
        if badge.pressed(BUTTON_MENU):
            self.set_editor(None)
            return
        if fire(self.rep_back, BUTTON_BACK):
            if ed.text:
                ed.backspace()
            elif badge.pressed(BUTTON_BACK):
                self.set_editor(None)
                return
        if fire(self.rep_select, BUTTON_SELECT) and (badge.pressed(BUTTON_SELECT) or ed.key() == logic.DELETE_KEY):
            if ed.press():
                self.commit(ed)

    def open_editor(self, text, error=None):
        self.set_editor(logic.Editor(text, error))

    def commit(self, ed):
        text = ed.text
        if not text:
            ed.error = "Type a username first"
        elif not logic.valid_handle(text):
            ed.error = "Use letters, numbers and hyphens"
        elif MISSING:
            ed.error = "Set up Wi-Fi to look up users"
        else:
            self.set_editor(None)
            self.switch_user(text)

    # -- user changes --------------------------------------------------

    def switch_user(self, handle):
        if logic.same_handle(handle, self.handle):
            self.handle = handle
            if self.graph is not None:
                self.view = GraphView(self.graph, handle)
                self.view.select(self.cursor)
            self.refresh_now()
            return
        if self.previous is None:
            self.previous = (self.handle, self.graph)
        self.handle = handle
        self.graph = None
        self.view = None
        self.problem = None
        self.failures = 0
        self.next_fetch_at = 0

    def user_not_found(self):
        rejected = self.handle
        self.failures = 0
        if self.previous is None:
            self.next_fetch_at = None
            hint = "Check GITHUB_USERNAME in secrets.py" if logic.same_handle(rejected, CONFIGURED) else ""
            self.problem = ("User not found", hint)
            return
        self.handle, self.graph = self.previous
        self.previous = None
        self.problem = None
        self.view = None
        if self.graph is not None:
            self.next_fetch_at = badge.ticks + REFRESH_MS
            self.cursor = self.graph.last
            self.view = GraphView(self.graph, self.handle)
        else:
            self.next_fetch_at = None if self.handle is None else 0
        if self.editor is None:
            self.open_editor(rejected, "User not found")
        else:
            self.editor.error = rejected + " was not found"

    def show_graph(self, fresh):
        old = self.graph
        if old is None or self.cursor == old.last:
            self.cursor = fresh.last
        else:
            self.cursor = fresh.index_for_day(old.day(self.cursor))
        self.graph = fresh
        self.view = GraphView(fresh, self.handle)
        self.view.select(self.cursor)
        self.previous = None
        self.problem = None
        self.failures = 0
        self.next_fetch_at = badge.ticks + REFRESH_MS
        if logic.same_handle(self.handle, CONFIGURED):
            write_cache(fresh)

    # -- network -------------------------------------------------------

    def refresh_now(self):
        if MISSING or self.handle is None or self.request is not None:
            return
        self.failures = 0
        self.next_fetch_at = 0

    def poll_network(self):
        if self.request is not None:
            self.pump_request()
        if (self.request is None and self.next_fetch_at is not None and self.editor is None
                and badge.ticks >= self.next_fetch_at):
            self.start_fetch()

    def start_fetch(self):
        self.next_fetch_at = None
        remove(DOWNLOAD_FILE)
        self.request_handle = self.handle
        try:
            self.request = fetch.url(logic.contribs_url(self.handle), headers=HEADERS).to(DOWNLOAD_FILE)
        except Exception as error:
            self.request = None
            self.fail(error)

    def pump_request(self):
        try:
            done = bool(self.request)
            error = None if done else getattr(self.request, "error", None)
        except Exception as caught:
            done = False
            error = caught
        if not done and not error:
            return
        self.request = None
        if not logic.same_handle(self.request_handle, self.handle):
            remove(DOWNLOAD_FILE)
            return
        if done:
            self.finish_download()
        else:
            remove(DOWNLOAD_FILE)
            self.fail(error)

    def finish_download(self):
        try:
            if os.stat(DOWNLOAD_FILE)[6] > MAX_DOWNLOAD_BYTES:
                raise ValueError("response too large")
            with open(DOWNLOAD_FILE) as f:
                payload = json.load(f)
            fresh = logic.parse_contribs(payload, self.handle)
        except (OSError, ValueError, KeyError, TypeError) as error:
            remove(DOWNLOAD_FILE)
            self.fail(error)
            return
        payload = None
        remove(DOWNLOAD_FILE)
        gc.collect()
        self.show_graph(fresh)

    def fail(self, error):
        if logic.http_status(error) == 404:
            self.user_not_found()
            return
        self.failures += 1
        self.problem = logic.describe_error(error)
        self.next_fetch_at = badge.ticks + logic.retry_delay_ms(self.failures)

    # -- drawing -------------------------------------------------------

    def draw(self):
        if self.editor is not None:
            self.draw_editor()
        elif self.handle is None:
            self.draw_setup()
        elif self.graph is not None:
            self.draw_graph()
        elif MISSING:
            missing_details.show(MISSING, self.draw_backdrop)
        else:
            self.draw_loading()

    def draw_backdrop(self):
        screen.pen = BG
        screen.clear()
        title = "@" + self.handle
        center_text(title, 90, fit_size(title, 26, WIDTH - 2 * MARGIN, 12), TEXT)

    def footer(self):
        """(text, colour) for the line at the bottom of the screen."""
        if self.handle is None:
            return ("Wi-Fi isn't set up either - set WIFI_SSID" if MISSING else "MENU look up a user"), MUTED
        if self.request is not None:
            text, failed = network_status(self.request)
            return text, (RED if failed else MUTED)
        if self.problem is not None:
            headline = self.problem[0]
            if self.next_fetch_at is not None:
                seconds = max(0, (self.next_fetch_at - badge.ticks + 999) // 1000)
                return "{} - retrying in {}s".format(headline, seconds), RED
            return headline + " - MENU change user", RED
        if MISSING:
            return "Wi-Fi isn't set up - showing saved data", MUTED
        return HINT, MUTED

    def draw_footer(self):
        text, pen = self.footer()
        draw_text(text, MARGIN, FOOTER_Y, fit_size(text, HINT_SIZE, WIDTH - 2 * MARGIN, 9), pen)

    def draw_graph(self):
        v = self.view
        screen.pen = BG
        screen.clear()

        draw_text(v.title, MARGIN, TITLE_Y, v.title_size, TEXT)
        draw_text(v.summary, MARGIN, SUMMARY_Y, v.summary_size, MUTED)
        for x, name in v.labels:
            draw_text(name, x, MONTHS_Y, v.label_size, MUTED)

        size = v.cell
        for level in range(5):
            screen.pen = LEVEL_COLORS[level]
            for x, y in v.groups[level]:
                screen.rectangle(x, y, size, size)

        screen.pen = WHITE
        screen.rectangle(v.cx - 1, v.cy - 1, size + 2, 1)
        screen.rectangle(v.cx - 1, v.cy + size, size + 2, 1)
        screen.rectangle(v.cx - 1, v.cy, 1, size)
        screen.rectangle(v.cx + size, v.cy, 1, size)

        draw_text(v.as_of, MARGIN, LEGEND_Y, SMALL, MUTED)
        draw_text("Less", v.less_x, LEGEND_Y, SMALL, MUTED)
        for level in range(5):
            screen.pen = LEVEL_COLORS[level]
            screen.rectangle(v.swatch_x + level * (LEGEND_CELL + LEGEND_GAP), LEGEND_Y + 2, LEGEND_CELL, LEGEND_CELL)
        draw_text("More", v.more_x, LEGEND_Y, SMALL, MUTED)

        screen.pen = PANEL
        screen.shape(PANEL_SHAPE)
        draw_text(v.day_date, MARGIN + 10, PANEL_Y + 6, 15, TEXT)
        draw_text(v.day_count, MARGIN + 10, PANEL_Y + 24, 13, LIME if v.day_level else MUTED)
        screen.pen = LEVEL_COLORS[v.day_level]
        screen.rectangle(WIDTH - MARGIN - 24, PANEL_Y + 14, 14, 14)

        for i in range(3):
            value, label = v.stats[i]
            x = MARGIN + i * STAT_WIDTH
            draw_text(value, x, STATS_Y, v.stat_sizes[i], LIME)
            draw_text(label, x, STATS_Y + 24, SMALL, MUTED)

        self.draw_footer()

    def draw_setup(self):
        screen.pen = BG
        screen.clear()
        if REJECTED:
            quoted = '"' + REJECTED + '"'
            title = "Invalid GitHub username"
            body = ((quoted, 18, TEXT),
                    ("Use letters, numbers and hyphens", 13, MUTED),
                    ("Fix it in secrets.py on your badge:", 16, TEXT))
        else:
            title = "GitHub username not set"
            body = (("Set your GitHub handle in the", 16, TEXT),
                    ("secrets.py file on your badge:", 16, TEXT))
        center_fit(title, SETUP_TITLE_Y, 22, 14, RED)
        height = sum(size for _, size, _ in body) + SETUP_LINE_GAP * (len(body) - 1)
        y = SETUP_BODY_TOP + (SETUP_BODY_BOTTOM - SETUP_BODY_TOP - height) // 2
        for text, size, pen in body:
            center_fit(text, y, size, 10, pen)
            y += size + SETUP_LINE_GAP
        screen.pen = PANEL
        screen.shape(SETUP_SHAPE)
        center_fit(SETUP_EXAMPLE, SETUP_PANEL_Y + 10, 16, 10, LIME)
        center_fit("Then open this app again.", SETUP_AFTER_Y, 14, 10, MUTED)
        self.draw_footer()

    def draw_loading(self):
        screen.pen = BG
        screen.clear()
        title = "@" + self.handle
        center_text(title, 72, fit_size(title, 26, WIDTH - 2 * MARGIN, 12), TEXT)
        if self.problem is not None:
            headline, detail = self.problem
            center_text(headline, 114, fit_size(headline, 16, WIDTH - 2 * MARGIN, 12), RED)
            if detail:
                center_text(detail, 138, fit_size(detail, 12, WIDTH - 2 * MARGIN, 9), MUTED)
        else:
            dots = "." * (1 + badge.ticks // 350 % 3)
            width, _ = screen.measure_text("Loading contributions...", font_size=16)
            draw_text("Loading contributions" + dots, (WIDTH - width) / 2, 114, 16, MUTED)
        self.draw_footer()

    def draw_editor(self):
        ed = self.editor
        screen.pen = BG
        screen.clear()
        draw_text("GitHub username", MARGIN, TITLE_Y, 14, MUTED)

        screen.pen = PANEL
        screen.shape(FIELD_SHAPE)
        text_x = FIELD_X + 12
        if ed.text:
            size = fit_size(ed.text, 22, FIELD_W - 28, 12)
            width, _ = screen.measure_text(ed.text, font_size=size)
            draw_text(ed.text, text_x, FIELD_Y + (FIELD_H - size) / 2 - 1, size, TEXT)
        else:
            width = 0
            draw_text("username", text_x, FIELD_Y + 6, 22, MUTED)
        if badge.ticks // 500 % 2 == 0:
            screen.pen = LIME
            screen.rectangle(text_x + int(width) + 2, FIELD_Y + 6, 2, FIELD_H - 12)

        if ed.error:
            draw_text(ed.error, MARGIN, 69, fit_size(ed.error, HINT_SIZE, WIDTH - 2 * MARGIN, 9), RED)
        else:
            draw_text("SELECT types the highlighted key", MARGIN, 69, HINT_SIZE, MUTED)

        for i in range(len(logic.KEYS)):
            key = logic.KEYS[i]
            x, y = KEY_POSITIONS[i]
            if i == ed.cursor:
                face, ink = LIME, BG
            elif key == logic.SHIFT_KEY and ed.shift:
                face, ink = MUTED, BG
            elif key == logic.ENTER_KEY:
                face, ink = GREEN, TEXT
            elif key == logic.DELETE_KEY:
                face, ink = PANEL, RED
            else:
                face, ink = PANEL, TEXT
            screen.pen = face
            screen.rectangle(x, y, KEY_W, KEY_H)
            label = ed.label(i)
            size = 16 if len(key) == 1 else 12
            draw_text(label, x + (KEY_W - key_width(label, size)) / 2, y + (KEY_H - size) / 2 - 1, size, ink)

        draw_text("BACK delete   MENU cancel", MARGIN, FOOTER_Y - 4, HINT_SIZE, MUTED)


app = App()


def update():
    screen.font = FONT
    app.step()


run(update)
