"""A fake badge runtime so badge/apps/contribution_graph/__init__.py runs on a desktop.

The app is executed exactly as it is on the badge: as a script that expects
`badge`, `screen`, `run` and friends to exist as globals. Everything it
touches is replaced by a small fake, and the badge's /state folder is mapped
onto a temporary folder.

This checks the app's logic and control flow. It does not check how things
look or how fast they run on the real hardware.
"""

import builtins
import json
import os
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_SOURCE = HERE.parents[1] / "badge" / "apps" / "contribution_graph"
APP_DIR = "/system/apps/contribution_graph"
OLD_USER_FILE = "/state/contribution_graph.json"    # where earlier versions saved the last user
CACHE_FILE = "/state/contribution_graph_cache.json"
DOWNLOAD_FILE = "/state/contribution_graph_download.json"

if str(APP_SOURCE) not in sys.path:
    sys.path.insert(0, str(APP_SOURCE))

BUTTONS = {"UP": 1, "DOWN": 2, "LEFT": 3, "RIGHT": 4, "SELECT": 5, "BACK": 6, "MENU": 7}


class HTTPException(Exception):
    """What the firmware's fetch module raises for a reply other than 200."""

    def __init__(self, status):
        super().__init__("HTTP error {}".format(status))
        self.fetch = types.SimpleNamespace(http_status=status)


class Reply:
    """How one fetch.url() request should turn out."""

    def __init__(self, payload=None, *, status=200, pumps=1, error=None, body=None,
                 hold=False, raises=None, never=False, style="firmware", state=None,
                 pump_raises=None):
        self.payload = payload
        self.status = status
        self.pumps = pumps        # bool(request) calls that say "not yet" first
        self.error = error        # an exception to report instead of a status
        self.body = body          # raw text for the downloaded file
        self.hold = hold          # stay pending until request.release()
        self.raises = raises      # raise from fetch.url() itself
        self.pump_raises = pump_raises   # raise from bool(request) once it would have finished
        self.never = never
        self.style = style        # "firmware" (exception object) or "browser" (text)
        self.state = state        # what request.state reads while the request is pending


class Request:
    """Stands in for fetch.url(...).to(path)."""

    def __init__(self, runtime, url, headers, reply):
        self.runtime = runtime
        self.url = url
        self.headers = headers
        self.reply = reply
        self.path = None
        self.error = None
        self.pumps = 0
        self.done = False
        self.released = not reply.hold

    def to(self, path):
        self.path = path
        return self

    def release(self):
        self.released = True

    @property
    def state(self):
        if self.reply.state is not None and not self.done:
            return self.reply.state
        if self.error is not None:
            return "Error: {}".format(self.error)
        return "Done" if self.done else "Fetching"

    def __bool__(self):
        self.pumps += 1
        if self.done:
            return self.error is None
        reply = self.reply
        if reply.never or not self.released or self.pumps <= reply.pumps:
            return False
        self.done = True
        if reply.pump_raises is not None:
            raise reply.pump_raises
        if reply.error is not None:
            self.error = reply.error
            return False
        if reply.status != 200:
            if reply.style == "firmware":
                self.write(reply.body if reply.body is not None else '{"error":"Not Found"}')
                self.error = HTTPException(reply.status)
            else:
                self.error = "HTTP {}".format(reply.status)
            return False
        body = reply.body if reply.body is not None else json.dumps(reply.payload)
        self.write(body)
        return True

    def write(self, text):
        with open(self.runtime.host(self.path), "w") as f:
            f.write(text)


class FakeFetch:
    def __init__(self, runtime):
        self.runtime = runtime
        self.AsyncFetch = type("AsyncFetch", (), {"MAX_HEADER_BYTES": 4096})

    def url(self, url, every=None, headers=None, debug=False):
        runtime = self.runtime
        reply = runtime.replies.pop(0) if runtime.replies else Reply(never=True)
        if reply.raises is not None:
            runtime.start_failures.append(url)
            raise reply.raises
        request = Request(runtime, url, headers, reply)
        runtime.requests.append(request)
        return request


class FakeWifi:
    def __init__(self):
        self.calls = []
        self.failed = False
        self.status_value = (3, "Connected")

    def connect(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return True

    def failure(self):
        return self.failed

    def status(self):
        return self.status_value


class FakeMissingDetails:
    def __init__(self, missing):
        self.unset = list(missing)
        self.shown = []

    def missing(self, *names):
        return [name for name in names if name in self.unset]

    def mona_sans(self):
        return "mona-sans"

    def show(self, names, background=None, details=()):
        self.shown.append(list(names))
        if background is not None:
            background()


class FakeOS:
    """The few os calls the app uses, with the badge's paths mapped to a temp folder."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.cwd = None

    def chdir(self, path):
        self.cwd = path

    def mkdir(self, path):
        os.mkdir(self.runtime.host(path))

    def remove(self, path):
        os.remove(self.runtime.host(path))

    def stat(self, path):
        return os.stat(self.runtime.host(path))


class FakeBadge:
    def __init__(self):
        self.ticks = 0
        self.down = set()
        self.previous = set()
        self.mode_value = None

    def mode(self, value):
        self.mode_value = value

    def pressed(self, button):
        return button in self.down and button not in self.previous

    def held(self, button):
        return button in self.down and button in self.previous

    def released(self, button):
        return button in self.previous and button not in self.down

    def touched(self, button):
        return button in self.down


def default_measure(text, size):
    return len(text) * size * 0.55


class FakeScreen:
    width = 320
    height = 240

    def __init__(self, measure=None):
        self.pen = None
        self.font = None
        self.antialias = None
        self.ops = []
        self.recording = True
        self.measure = measure or default_measure

    def clear(self):
        self.ops = [("clear", self.pen)] if self.recording else []

    def rectangle(self, x, y, w, h):
        if self.recording:
            self.ops.append(("rect", x, y, w, h, self.pen))

    def shape(self, outline):
        if self.recording:
            self.ops.append(("shape", outline, self.pen))

    def text(self, text, x, y, size):
        if self.recording:
            self.ops.append(("text", text, x, y, size, self.pen))

    def measure_text(self, text, font_size):
        return self.measure(text, font_size), font_size


class Runtime:
    """Runs the app and lets a test press buttons and let time pass."""

    FRAME_MS = 33
    source_override = None    # lets the mutation check run a modified copy of the app

    def __init__(self, root, *, missing=(), old_user=None, cache=None, replies=(), measure=None):
        self.root = Path(root)
        self.state_dir = self.root / "state"
        self.replies = list(replies)
        self.requests = []
        self.start_failures = []
        self.imports = []
        self.badge = FakeBadge()
        self.screen = FakeScreen(measure)
        self.wifi = FakeWifi()
        self.missing_details = FakeMissingDetails(missing)
        self.fetch = FakeFetch(self)
        self.os = FakeOS(self)
        self.registered = None
        self.namespace = None
        self.frames = 0
        if old_user is not None:
            self.write_file(OLD_USER_FILE, old_user)
        if cache is not None:
            self.write_file(CACHE_FILE, cache)

    # -- the badge's file system --------------------------------------

    def host(self, path):
        if path == "/state" or path.startswith("/state/"):
            return str(self.state_dir / path[len("/state/"):])
        if path.startswith(APP_DIR):
            return str(APP_SOURCE / path[len(APP_DIR) + 1:])
        return path

    def write_file(self, path, content):
        target = Path(self.host(path))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content if isinstance(content, str) else json.dumps(content))

    def read_json(self, path):
        with open(self.host(path)) as f:
            return json.load(f)

    def exists(self, path):
        return Path(self.host(path)).exists()

    # -- running the app ----------------------------------------------

    def start(self):
        modules = {
            "os": self.os,
            "sys": types.SimpleNamespace(path=[]),
            "fetch": self.fetch,
            "missing_details": self.missing_details,
            "wifi": self.wifi,
        }
        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            self.imports.append(name)
            if name in modules:
                return modules[name]
            return real_import(name, globals, locals, fromlist, level)

        def fake_open(path, *args, **kwargs):
            return builtins.open(self.host(path), *args, **kwargs)

        fake_builtins = dict(vars(builtins))
        fake_builtins["__import__"] = fake_import
        fake_builtins["open"] = fake_open

        def make_color(r, g, b, a=255):
            return (r, g, b)

        namespace = {
            "__name__": "contribution_graph",
            "__builtins__": fake_builtins,
            "badge": self.badge,
            "screen": self.screen,
            "color": types.SimpleNamespace(rgb=make_color),
            "shape": types.SimpleNamespace(
                rounded_rectangle=lambda x, y, w, h, r: ("rounded", x, y, w, h, r)),
            "image": types.SimpleNamespace(X2=2),
            "font": types.SimpleNamespace(nope="font.nope", sins="font.sins"),
            "HIRES": 1,
            "VSYNC": 2,
            "run": self.register,
        }
        for name, value in BUTTONS.items():
            namespace["BUTTON_" + name] = value
        self.namespace = namespace

        path = APP_SOURCE / "__init__.py"
        source = self.source_override
        if source is None:
            source = path.read_text(encoding="utf-8")
        exec(compile(source, str(path), "exec"), namespace)
        if self.registered is None:
            raise AssertionError("the app never called run(update)")
        return self

    def register(self, update):
        self.registered = update

    @property
    def app(self):
        return self.namespace["app"]

    # -- time and buttons ---------------------------------------------

    def frame(self, *buttons, ms=None):
        self.badge.previous = self.badge.down
        self.badge.down = {BUTTONS[name] for name in buttons}
        self.badge.ticks += self.FRAME_MS if ms is None else ms
        self.screen.ops = []
        self.registered()
        self.frames += 1

    def frames_for(self, count):
        for _ in range(count):
            self.frame()

    def press(self, name):
        """A quick tap: one frame down, one frame up."""
        self.frame(name)
        self.frame()

    def hold(self, name, ms):
        end = self.badge.ticks + ms
        while self.badge.ticks < end:
            self.frame(name)
        self.frame()

    def wait(self, ms, step=500, record=False):
        """Let time pass with no buttons down."""
        end = self.badge.ticks + ms
        was = self.screen.recording
        self.screen.recording = record
        try:
            while self.badge.ticks < end:
                self.frame(ms=min(step, end - self.badge.ticks))
        finally:
            self.screen.recording = was
        self.frame()

    # -- what is on screen --------------------------------------------

    def texts(self):
        return [op[1] for op in self.screen.ops if op[0] == "text"]

    def has_text(self, text):
        return text in self.texts()

    def rects(self):
        return [op for op in self.screen.ops if op[0] == "rect"]

    # -- driving the keyboard -----------------------------------------

    def goto_key(self, key):
        from contrib_data import KEYS, KEY_COLUMNS
        editor = self.app.editor
        rows, columns = divmod((KEYS.index(key) - editor.cursor) % len(KEYS), KEY_COLUMNS)
        for _ in range(rows):
            self.press("DOWN")
        for _ in range(columns):
            self.press("RIGHT")
        assert editor.key() == key, (editor.key(), key)

    def type_text(self, text):
        for ch in text:
            if ch.isupper():
                self.goto_key("Aa")
                self.press("SELECT")
                ch = ch.lower()
            self.goto_key(ch)
            self.press("SELECT")

    def clear_text(self):
        """Delete the box's text one letter at a time.

        One BACK per letter, never more: BACK on an empty box closes the keyboard.
        """
        for _ in range(len(self.app.editor.text)):
            self.press("BACK")
        assert self.app.editor is not None and not self.app.editor.text, "BACK did not empty the box"

    def enter_user(self, text):
        """MENU, clear the box, type a name and accept it."""
        self.press("MENU")
        assert self.app.editor is not None
        self.clear_text()
        self.type_text(text)
        self.goto_key("OK")
        self.press("SELECT")
