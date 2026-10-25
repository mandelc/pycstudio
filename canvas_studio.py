"""Desktop Pygame implementation of the Python Canvas Studio API.

Install the desktop dependency with ``python -m pip install -r
requirements-desktop.txt``. Then run a Python file that imports this module::

    import canvas_studio as studio

    def draw():
        studio.clear("#ffffff")
        studio.circle(studio.mouse_x, studio.mouse_y, 24)

    studio.start(draw)

On desktop, ``start()`` owns the Pygame event loop and returns when the window
closes. Drawing and input helpers are available from the ``canvas_studio``
module just as they are in the browser version.
"""

import importlib
import ipaddress
import json
import math
from pathlib import Path
import threading
import traceback


__all__ = [
    "CanvasImage",
    "CanvasChannel",
    "CanvasConnection",
    "CanvasSound",
    "arc",
    "background",
    "button",
    "circle",
    "clear",
    "connect",
    "connect_broadcast",
    "configure_images",
    "configure_sounds",
    "ellipse",
    "get_canvas_height",
    "get_canvas_width",
    "hide_mouse_pointer",
    "image",
    "init",
    "key",
    "key_code",
    "key_code_name",
    "line",
    "load_image",
    "load_sound",
    "mouse_x",
    "mouse_y",
    "open_channel",
    "pause_sound",
    "play_sound",
    "polygon",
    "rect",
    "reset_transform",
    "rotate",
    "scale",
    "set_canvas_size",
    "show_mouse_pointer",
    "start",
    "stop_sound",
    "text",
    "translate",
]

_canvas_width = 960
_canvas_height = 520
mouse_x = 0
mouse_y = 0
button = None
key = ""
key_code = ""
key_code_name = ""

_pygame = None
_app = None
_callbacks = {}
_image_paths = {}
_sound_paths = {}
_mouse_visible = True
_channels = {}


class CanvasChannel:
    """A WebSocket connection to a shared message channel."""

    def __init__(self, name, on_message, server):
        try:
            websocket = importlib.import_module("websocket")
        except ImportError as error:
            raise ImportError(
                "WebSocket channels require websocket-client. Install it with "
                "'python -m pip install -r requirements-desktop.txt'."
            ) from error
        self.name = name
        self.server = server
        self._on_message_callback = on_message
        self._pending_messages = []
        self._lock = threading.Lock()
        self._connected = False
        self._closed = False
        self._app = websocket.WebSocketApp(
            server,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._thread = threading.Thread(
            target=self._app.run_forever,
            kwargs={"ping_interval": 30, "ping_timeout": 10},
            daemon=True,
        )
        _channels[id(self)] = self
        self._thread.start()

    def send(self, message):
        """Send a JSON-serializable message to other clients on this channel."""
        try:
            payload = json.dumps(message, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise TypeError("Channel messages must be JSON-serializable.") from error
        with self._lock:
            if self._closed:
                raise RuntimeError("This channel is closed.")
            if not self._connected:
                self._pending_messages.append(message)
                return
            self._send_message(message)

    def _send_message(self, message):
        packet = {"type": "message", "message": message}
        if self.name is not None:
            packet["channel"] = self.name
        self._app.send(json.dumps(packet, allow_nan=False))

    def _on_open(self, _app):
        with self._lock:
            if self._closed:
                return
            if self.name is None:
                self._app.send(json.dumps({"type": "connect"}))
            else:
                self._app.send(json.dumps({"type": "join", "channel": self.name}))
            self._connected = True
            pending_messages, self._pending_messages = self._pending_messages, []
            for message in pending_messages:
                self._send_message(message)

    def _on_message(self, _app, raw_message):
        try:
            packet = json.loads(raw_message)
            if packet.get("type") == "message":
                self._on_message_callback(packet.get("message"))
            elif packet.get("type") == "error":
                print(f"Message server error: {packet.get('error', 'unknown error')}")
        except Exception:
            traceback.print_exc()

    def _on_error(self, _app, error):
        if not self._closed:
            print(
                f"Unable to connect to message server {self.server}: {error}. "
                "Check that the relay is running, the host and port are correct, "
                "and the port is allowed through the firewall."
            )

    def _on_close(self, _app, _status_code, _message):
        with self._lock:
            self._connected = False
            self._closed = True
        _channels.pop(id(self), None)

    def close(self):
        """Close the WebSocket connection."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._connected = False
        self._app.close()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        _channels.pop(id(self), None)


class CanvasConnection:
    """A virtual peer connection routed through the Studio relay."""

    def __init__(self, host, virtual_port, secure):
        try:
            websocket = importlib.import_module("websocket")
        except ImportError as error:
            raise ImportError(
                "Virtual connections require websocket-client. Install it with "
                "'python -m pip install -r requirements-desktop.txt'."
            ) from error
        formatted_host = host.strip()
        if ":" in formatted_host and not formatted_host.startswith("["):
            formatted_host = f"[{formatted_host}]"
        scheme = "wss" if secure else "ws"
        self.server = f"{scheme}://{formatted_host}:{virtual_port}"
        self.virtual_port = virtual_port
        self._connection_id = None
        self._on_message_callback = None
        self._remote_address = None
        self._remote_port = None
        self._pending_messages = []
        self._lock = threading.Lock()
        self._connected = False
        self._closed = False
        self._app = websocket.WebSocketApp(
            self.server,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._thread = threading.Thread(
            target=self._app.run_forever,
            kwargs={"ping_interval": 30, "ping_timeout": 10},
            daemon=True,
        )
        _channels[id(self)] = self
        self._thread.start()

    def on_message(self, callback):
        """Register a callback for messages received from the peer."""
        if not callable(callback):
            raise TypeError("callback must be callable.")
        with self._lock:
            if self._closed:
                raise RuntimeError("This connection is closed.")
            self._on_message_callback = callback

    def get_remote_address(self):
        """Return the peer address as observed by the relay, or None until connected."""
        with self._lock:
            return self._remote_address

    def get_remote_port(self):
        """Return the peer port as observed by the relay, or None until connected."""
        with self._lock:
            return self._remote_port

    def send(self, message):
        """Send a JSON-serializable message to the paired peer."""
        try:
            json.dumps(message, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise TypeError("Connection messages must be JSON-serializable.") from error
        with self._lock:
            if self._closed:
                raise RuntimeError("This connection is closed.")
            if not self._connected:
                self._pending_messages.append(message)
                return
            self._send_message(message)

    def _send_message(self, message):
        self._app.send(json.dumps({
            "type": "data",
            "connection_id": self._connection_id,
            "message": message,
        }, allow_nan=False))

    def _on_open(self, _app):
        self._app.send(json.dumps({"type": "connect", "port": self.virtual_port}))

    def _on_message(self, _app, raw_message):
        try:
            packet = json.loads(raw_message)
            packet_type = packet.get("type")
            if packet_type == "connected":
                with self._lock:
                    if self._closed:
                        return
                    self._connection_id = packet["connection_id"]
                    self._remote_address = packet.get("remote_address")
                    self._remote_port = packet.get("remote_port")
                    self._connected = True
                    pending, self._pending_messages = self._pending_messages, []
                    for message in pending:
                        self._send_message(message)
            elif (
                packet_type == "data"
                and packet.get("connection_id") == self._connection_id
            ):
                with self._lock:
                    callback = self._on_message_callback
                if callback is not None:
                    callback(packet.get("message"))
                else:
                    print(f"Received network message: {packet.get('message')!r}")
            elif packet_type in ("error", "connection_error"):
                print(f"Message server error: {packet.get('error', 'unknown error')}")
                self._mark_closed()
                self._app.close()
            elif packet_type == "disconnected":
                self._mark_closed()
                self._app.close()
        except Exception:
            traceback.print_exc()

    def _on_error(self, _app, error):
        if not self._closed:
            print(f"Unable to connect to virtual server {self.server}: {error}")

    def _on_close(self, _app, _status_code, _message):
        self._mark_closed()

    def _mark_closed(self):
        with self._lock:
            self._connected = False
            self._closed = True
        _channels.pop(id(self), None)

    def close(self):
        """Close this virtual peer connection."""
        with self._lock:
            if self._closed:
                return
            if self._connected:
                self._app.send(json.dumps({
                    "type": "close",
                    "connection_id": self._connection_id,
                }))
            self._closed = True
            self._connected = False
        self._app.close()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        _channels.pop(id(self), None)


def open_channel(name, on_message, server=None):
    """Connect to a WebSocket message server for cross-device communication."""
    if not isinstance(name, str) or not name:
        raise ValueError("Channel name must be a non-empty string.")
    if not callable(on_message):
        raise TypeError("on_message must be callable.")
    if not isinstance(server, str) or not server.startswith(("ws://", "wss://")):
        raise ValueError("Desktop channels require a server ws:// or wss:// URL.")
    return CanvasChannel(name, on_message, server)


def _validate_relay_address(host, port, secure):
    if not isinstance(host, str) or not host.strip():
        raise ValueError("host must be a non-empty hostname or IP address.")
    candidate = host.strip()
    if "://" in candidate or "/" in candidate:
        raise ValueError("host must not include a scheme, path, or port.")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer from 1 to 65535.")
    if not isinstance(secure, bool):
        raise TypeError("secure must be a bool.")
    if ":" in candidate:
        ipv6 = candidate[1:-1] if candidate.startswith("[") and candidate.endswith("]") else candidate
        try:
            ipaddress.IPv6Address(ipv6)
        except ipaddress.AddressValueError as error:
            raise ValueError("host must not include a port; use an IPv6 address if needed.") from error


def connect(host, port, *, secure=False):
    """Connect to the virtual service on the relay host and port."""
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer from 1 to 65535.")
    _validate_relay_address(host, port, secure)
    return CanvasConnection(host, port, secure)


def connect_broadcast(host, port, on_message, secure=False):
    """Connect to the legacy relay broadcast service."""
    if not callable(on_message):
        raise TypeError("on_message must be callable.")
    _validate_relay_address(host, port, secure)
    formatted_host = host.strip()
    if ":" in formatted_host and not formatted_host.startswith("["):
        formatted_host = f"[{formatted_host}]"
    scheme = "wss" if secure else "ws"
    return CanvasChannel(
        None,
        on_message,
        server=f"{scheme}://{formatted_host}:{port}",
    )


class CanvasImage:
    """A local image loaded by :func:`load_image`."""

    def __init__(self, name, surface):
        self.name = str(name)
        self.surface = surface
        self.width, self.height = surface.get_size()


class CanvasSound:
    """A local sound loaded by :func:`load_sound`."""

    def __init__(self, name, sound):
        self.name = str(name)
        self._sound = sound
        self._channel = None
        self._paused = False


class _PygameCanvas:
    def __init__(self, pygame):
        self.pygame = pygame
        self.screen = pygame.display.set_mode((_canvas_width, _canvas_height))
        self.transform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        self.fonts = {}
        self.images = dict(_image_paths)
        self.sounds = dict(_sound_paths)
        pygame.mouse.set_visible(_mouse_visible)

    def color(self, value):
        if isinstance(value, str) and value.startswith("#") and len(value) in (4, 5):
            value = "#" + "".join(character * 2 for character in value[1:])
        try:
            return self.pygame.Color(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid color: {value!r}") from error

    def transform_point(self, x, y):
        a, b, c, d, e, f = self.transform
        return a * x + c * y + e, b * x + d * y + f

    def transform_points(self, points):
        return [self.transform_point(x, y) for x, y in points]

    def compose(self, a, b, c, d, e, f):
        current_a, current_b, current_c, current_d, current_e, current_f = (
            self.transform
        )
        self.transform = (
            current_a * a + current_c * b,
            current_b * a + current_d * b,
            current_a * c + current_c * d,
            current_b * c + current_d * d,
            current_a * e + current_c * f + current_e,
            current_b * e + current_d * f + current_f,
        )

    def scale_factors(self):
        a, b, c, d, _, _ = self.transform
        return math.hypot(a, b), math.hypot(c, d)

    def rotation_degrees(self):
        a, b, _, _, _, _ = self.transform
        return -math.degrees(math.atan2(b, a))


def _load_pygame():
    global _pygame
    if _pygame is None:
        try:
            _pygame = importlib.import_module("pygame")
        except ImportError as error:
            raise ImportError(
                "Pygame is required for the desktop canvas. Install it with "
                "'python -m pip install -r requirements-desktop.txt'."
            ) from error
    return _pygame


def _require_app():
    if _app is None:
        raise RuntimeError("Call start() before using drawing functions.")
    return _app


def _normalized_origin(origin, name):
    pair_error = f"{name} must be a normalized (x, y) pair from 0.0 to 1.0."
    values_error = f"{name} values must be between 0.0 and 1.0."
    try:
        values = tuple(origin)
    except TypeError as error:
        raise ValueError(pair_error) from error
    if len(values) != 2:
        raise ValueError(pair_error)
    try:
        values = tuple(float(value) for value in values)
    except (TypeError, ValueError) as error:
        raise ValueError(values_error) from error
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
        raise ValueError(values_error)
    return values


def _shape_origin(origin, rotate, angle_unit):
    if angle_unit not in ("degrees", "radians"):
        raise ValueError("angle_unit must be 'degrees' or 'radians'.")
    if origin is None:
        return None, None
    origin = _normalized_origin(origin, "origin")
    if rotate is not None and angle_unit == "degrees":
        rotate = math.radians(rotate)
    return origin, rotate


def _shape_rotation(origin, rotate, angle_unit):
    if angle_unit not in ("degrees", "radians"):
        raise ValueError("angle_unit must be 'degrees' or 'radians'.")
    if origin is None or rotate is None:
        return None, None
    return _normalized_origin(origin, "rotation_origin"), (
        math.radians(rotate) if angle_unit == "degrees" else rotate
    )


def _placement(bounds, origin, rotate, anchor=None):
    left, top, width, height = bounds
    if origin is None:
        return (0.0, 0.0), None
    shape_anchor = (left + origin[0] * width, top + origin[1] * height)
    target = shape_anchor if anchor is None else anchor
    offset = (target[0] - shape_anchor[0], target[1] - shape_anchor[1])
    pivot = target if rotate is not None else None
    return offset, pivot


def _map_shape_point(point, offset, pivot, rotation):
    x, y = point
    x += offset[0]
    y += offset[1]
    if pivot is not None:
        dx, dy = x - pivot[0], y - pivot[1]
        cosine, sine = math.cos(rotation), math.sin(rotation)
        x = pivot[0] + dx * cosine - dy * sine
        y = pivot[1] + dx * sine + dy * cosine
    return x, y


def _draw_shape_polygon(
    points,
    fill,
    stroke,
    stroke_width=1,
    offset=(0.0, 0.0),
    pivot=None,
    rotation=None,
):
    app = _require_app()
    transformed = app.transform_points(
        _map_shape_point(point, offset, pivot, rotation) for point in points
    )
    if len(transformed) < 3:
        return

    supersample = 4
    scale_x, scale_y = app.scale_factors()
    pixel_stroke_width = max(0, stroke_width) * (scale_x + scale_y) / 2
    margin = math.ceil(pixel_stroke_width / 2) + 1
    left = max(0, math.floor(min(x for x, _ in transformed)) - margin)
    top = max(0, math.floor(min(y for _, y in transformed)) - margin)
    right = min(
        app.screen.get_width(),
        math.ceil(max(x for x, _ in transformed)) + margin + 1,
    )
    bottom = min(
        app.screen.get_height(),
        math.ceil(max(y for _, y in transformed)) + margin + 1,
    )
    if left >= right or top >= bottom:
        return

    pygame = app.pygame
    layer = pygame.Surface(
        ((right - left) * supersample, (bottom - top) * supersample),
        pygame.SRCALPHA,
    )
    high_res_points = [
        (
            round((x - left) * supersample),
            round((y - top) * supersample),
        )
        for x, y in transformed
    ]
    if fill is not None:
        pygame.draw.polygon(layer, app.color(fill), high_res_points)
    if stroke is not None and pixel_stroke_width > 0:
        pygame.draw.polygon(
            layer,
            app.color(stroke),
            high_res_points,
            width=max(1, round(pixel_stroke_width * supersample)),
        )
    antialiased = pygame.transform.smoothscale(layer, (right - left, bottom - top))
    app.screen.blit(antialiased, (left, top))


def clear(color="#ffffff"):
    """Fill the entire canvas with a color."""
    app = _require_app()
    app.screen.fill(app.color(color))


def background(color):
    """Alias for :func:`clear`."""
    clear(color)


def set_canvas_size(width, height):
    """Set the canvas size in pixels using positive integer dimensions."""
    if (
        isinstance(width, bool)
        or not isinstance(width, int)
        or isinstance(height, bool)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
    ):
        raise ValueError("Canvas width and height must be positive integers.")

    global _canvas_width, _canvas_height
    _canvas_width, _canvas_height = width, height
    if _app is not None:
        _app.screen = _pygame.display.set_mode((width, height))
        _app.transform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        _app.screen.fill(_app.color("#ffffff"))


def get_canvas_width():
    """Return the canvas width in pixels."""
    return _canvas_width


def get_canvas_height():
    """Return the canvas height in pixels."""
    return _canvas_height


def translate(x, y):
    """Move the canvas origin by x and y pixels."""
    _require_app().compose(1, 0, 0, 1, x, y)


def rotate(angle, angle_unit="degrees"):
    """Rotate subsequent drawing clockwise by degrees or radians."""
    if angle_unit not in ("degrees", "radians"):
        raise ValueError("angle_unit must be 'degrees' or 'radians'.")
    radians = math.radians(angle) if angle_unit == "degrees" else angle
    cosine, sine = math.cos(radians), math.sin(radians)
    _require_app().compose(cosine, sine, -sine, cosine, 0, 0)


def scale(x, y=None):
    """Scale subsequent drawing horizontally by x and vertically by y."""
    _require_app().compose(x, 0, 0, x if y is None else y, 0, 0)


def reset_transform():
    """Reset translation, rotation, and scaling."""
    _require_app().transform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def rect(
    x,
    y,
    width,
    height,
    fill="#5b56e8",
    stroke="#000",
    *,
    stroke_width=1,
    origin=(0, 0),
    rotate=None,
    angle_unit="degrees",
):
    """Draw a rectangle; set fill or stroke to None to omit that part."""
    origin, rotation = _shape_origin(origin, rotate, angle_unit)
    bounds = (
        min(x, x + width),
        min(y, y + height),
        abs(width),
        abs(height),
    )
    offset, pivot = _placement(bounds, origin, rotation, (x, y))
    _draw_shape_polygon(
        ((x, y), (x + width, y), (x + width, y + height), (x, y + height)),
        fill,
        stroke,
        stroke_width,
        offset,
        pivot,
        rotation,
    )


def circle(
    x,
    y,
    radius,
    fill="#f6c85f",
    stroke="#000",
    *,
    stroke_width=1,
    rotation_origin=None,
    rotate=None,
    angle_unit="degrees",
):
    """Draw an anti-aliased circle; set fill or stroke to None to omit it."""
    origin, rotation = _shape_rotation(rotation_origin, rotate, angle_unit)
    radius = max(0, radius)
    scale_x, scale_y = _require_app().scale_factors()
    pixel_radius = radius * max(scale_x, scale_y)
    segments = max(32, min(512, math.ceil(math.pi * max(pixel_radius, 1))))
    points = [
        (
            x + radius * math.cos(index * math.tau / segments),
            y + radius * math.sin(index * math.tau / segments),
        )
        for index in range(segments)
    ]
    bounds = (x - radius, y - radius, radius * 2, radius * 2)
    offset, pivot = _placement(bounds, origin, rotation)
    _draw_shape_polygon(points, fill, stroke, stroke_width, offset, pivot, rotation)


def ellipse(
    x,
    y,
    width,
    height,
    fill="#f6c85f",
    stroke="#000",
    *,
    stroke_width=1,
    origin=(0, 0),
    rotate=None,
    angle_unit="degrees",
):
    """Draw an anti-aliased ellipse; set fill or stroke to None to omit it."""
    origin, rotation = _shape_origin(origin, rotate, angle_unit)
    width, height = max(0, width), max(0, height)
    left, top = x, y
    center_x, center_y = left + width / 2, top + height / 2
    scale_x, scale_y = _require_app().scale_factors()
    pixel_diameter = max(width * scale_x, height * scale_y)
    segments = max(32, min(512, math.ceil(math.pi * max(pixel_diameter, 1) / 4)))
    points = [
        (
            center_x + width / 2 * math.cos(index * math.tau / segments),
            center_y + height / 2 * math.sin(index * math.tau / segments),
        )
        for index in range(segments)
    ]
    offset, pivot = _placement((left, top, width, height), origin, rotation, (x, y))
    _draw_shape_polygon(points, fill, stroke, stroke_width, offset, pivot, rotation)


def arc(
    x,
    y,
    radius,
    start_angle,
    end_angle,
    stroke="#000",
    width=2,
    *,
    origin=(0, 0),
    rotate=None,
    angle_unit="degrees",
):
    """Draw a stroked arc in clockwise order, in degrees by default."""
    if stroke is None:
        return
    origin, rotation = _shape_origin(origin, rotate, angle_unit)
    if angle_unit == "degrees":
        start_angle, end_angle = math.radians(start_angle), math.radians(end_angle)
    radius = max(0, radius)
    span = max(-math.tau, min(math.tau, end_angle - start_angle))
    segments = max(2, min(512, math.ceil(abs(span) * max(radius, 1) / 3)))
    points = [
        (
            x + radius + radius * math.cos(start_angle + span * index / segments),
            y + radius + radius * math.sin(start_angle + span * index / segments),
        )
        for index in range(segments + 1)
    ]
    bounds = (x, y, radius * 2, radius * 2)
    offset, pivot = _placement(bounds, origin, rotation, (x, y))
    app = _require_app()
    points = app.transform_points(
        _map_shape_point(point, offset, pivot, rotation) for point in points
    )
    scale_x, scale_y = app.scale_factors()
    app.pygame.draw.lines(
        app.screen,
        app.color(stroke),
        False,
        [(round(px), round(py)) for px, py in points],
        max(1, round(max(0, width or 1) * (scale_x + scale_y) / 2)),
    )


def polygon(
    points,
    fill="#5b56e8",
    stroke="#000",
    *,
    stroke_width=1,
    x=None,
    y=None,
    origin=(0, 0),
    rotate=None,
    angle_unit="degrees",
):
    """Draw a polygon; set fill or stroke to None to omit that part."""
    try:
        vertices = [tuple(point) for point in points]
    except TypeError as error:
        raise ValueError("polygon() expects a sequence of (x, y) points.") from error
    if len(vertices) < 3 or any(len(point) != 2 for point in vertices):
        raise ValueError("polygon() expects at least three (x, y) points.")
    if (x is None) != (y is None):
        raise ValueError("polygon() requires both x and y when positioning it.")

    origin, rotation = _shape_origin(origin, rotate, angle_unit)
    left = min(point[0] for point in vertices)
    top = min(point[1] for point in vertices)
    width = max(point[0] for point in vertices) - left
    height = max(point[1] for point in vertices) - top
    bounds = (left, top, width, height)
    anchor = (x, y) if x is not None else None
    offset, pivot = _placement(bounds, origin, rotation, anchor)
    _draw_shape_polygon(vertices, fill, stroke, stroke_width, offset, pivot, rotation)


def line(x1, y1, x2, y2, stroke="#000", width=2):
    """Draw a line between two points."""
    if stroke is None:
        return
    app = _require_app()
    points = app.transform_points(((x1, y1), (x2, y2)))
    scale_x, scale_y = app.scale_factors()
    x_start, y_start = points[0]
    x_end, y_end = points[1]
    delta_x = x_end - x_start
    delta_y = y_end - y_start
    length = math.hypot(delta_x, delta_y)
    if length == 0:
        return

    half_width = max(1, round(max(0, width or 1) * (scale_x + scale_y) / 2)) / 2
    offset_x = -delta_y * half_width / length
    offset_y = delta_x * half_width / length
    app.pygame.draw.polygon(
        app.screen,
        app.color(stroke),
        [
            (round(x_start + offset_x), round(y_start + offset_y)),
            (round(x_end + offset_x), round(y_end + offset_y)),
            (round(x_end - offset_x), round(y_end - offset_y)),
            (round(x_start - offset_x), round(y_start - offset_y)),
        ],
    )


def _render_text(value, size, color, stroke=None, stroke_width=1):
    app = _require_app()
    scale_x, scale_y = app.scale_factors()
    font_size = max(1, round(size * (scale_x + scale_y) / 2))
    font = app.fonts.get(font_size)
    if font is None:
        font = app.pygame.font.Font(None, font_size)
        app.fonts[font_size] = font
    lines = str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    glyphs = [
        font.render(item, True, app.color(color if color is not None else "#ffffff"))
        for item in lines
    ]
    width = max(1, max(glyph.get_width() for glyph in glyphs))
    height = max(1, font.get_linesize() * len(lines))
    glyph_surface = app.pygame.Surface((width, height), app.pygame.SRCALPHA)
    for index, line_surface in enumerate(glyphs):
        glyph_surface.blit(line_surface, (0, index * font.get_linesize()))
    if color is None:
        surface = app.pygame.Surface((width, height), app.pygame.SRCALPHA)
    else:
        surface = glyph_surface
    pixel_stroke_width = max(0, stroke_width) * (scale_x + scale_y) / 2
    if stroke is None or pixel_stroke_width <= 0:
        return surface, font.get_ascent()

    radius = max(1, math.ceil(pixel_stroke_width / 2))
    kernel_surface = app.pygame.Surface(
        (radius * 2 + 1, radius * 2 + 1), app.pygame.SRCALPHA
    )
    app.pygame.draw.circle(
        kernel_surface,
        (255, 255, 255, 255),
        (radius, radius),
        radius,
    )
    glyph_mask = app.pygame.mask.from_surface(glyph_surface)
    if glyph_mask.count() == 0:
        return surface, font.get_ascent()
    outline_mask = glyph_mask.convolve(
        app.pygame.mask.from_surface(kernel_surface),
        offset=(-radius, -radius),
    )
    outlined = outline_mask.to_surface(
        setcolor=app.color(stroke),
        unsetcolor=(0, 0, 0, 0),
    )
    if color is not None:
        outlined.blit(surface, (radius, radius))
    return outlined, font.get_ascent() + radius


def text(
    value,
    x,
    y,
    size=20,
    color="#253149",
    align="left",
    *,
    stroke=None,
    stroke_width=1,
    origin=(0, 0),
    rotate=None,
    angle_unit="degrees",
):
    """Draw aligned text; set color or stroke to None to omit that part."""
    if align not in ("left", "center", "right"):
        raise ValueError("align must be 'left', 'center', or 'right'.")
    origin, rotation = _shape_origin(origin, rotate, angle_unit)
    app = _require_app()
    surface, ascent = _render_text(value, size or 20, color, stroke, stroke_width)
    scale_x, scale_y = app.scale_factors()
    source_width, source_height = surface.get_size()
    outline_padding = (
        max(1, math.ceil(max(0, stroke_width) * (scale_x + scale_y) / 4))
        if stroke is not None and stroke_width > 0
        else 0
    )
    if align == "left":
        left = x - outline_padding
    elif align == "center":
        left = x - source_width / 2
    else:
        left = x - source_width
    top = y - ascent
    if (scale_x, scale_y) != (1.0, 1.0):
        surface = app.pygame.transform.smoothscale(
            surface,
            (max(1, round(source_width * scale_x)),
             max(1, round(source_height * scale_y))),
        )
    bounds = (left, y, source_width, source_height)
    offset, pivot = _placement(bounds, origin, rotation, (x, y))
    center = _map_shape_point(
        (left + source_width / 2, top + source_height / 2),
        offset,
        pivot,
        rotation,
    )
    center = app.transform_point(*center)
    angle = app.rotation_degrees()
    if rotation is not None:
        angle -= math.degrees(rotation)
    if angle:
        surface = app.pygame.transform.rotate(surface, angle)
    app.screen.blit(surface, surface.get_rect(center=center))


def configure_images(images):
    """Map image names to local file paths for :func:`load_image`."""
    if not hasattr(images, "items"):
        raise TypeError("configure_images() expects a mapping of names to file paths.")
    global _image_paths
    _image_paths = {str(name): Path(path) for name, path in images.items()}
    if _app is not None:
        _app.images = dict(_image_paths)


def _resolve_asset_path(name, configured_paths, asset_folder):
    name = str(name)
    candidates = []
    configured_path = configured_paths.get(name)
    if configured_path is not None:
        candidates.append(Path(configured_path))

    requested_path = Path(name)
    candidates.append(requested_path)
    module_directory = Path(__file__).resolve().parent
    if not requested_path.is_absolute():
        candidates.append(module_directory / requested_path)
        if len(requested_path.parts) == 1:
            candidates.append(module_directory / asset_folder / requested_path)

    checked = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in checked:
            checked.add(key)
            if candidate.is_file():
                return candidate
    return candidates[0]


def load_image(name):
    """Load an image from a local path or a name configured with configure_images()."""
    pygame = _load_pygame()
    image_path = _resolve_asset_path(
        name,
        _app.images if _app is not None else _image_paths,
        "images",
    )
    if not image_path.is_file():
        raise FileNotFoundError(f"No image file found at {str(image_path)!r}.")
    try:
        surface = pygame.image.load(str(image_path))
        if pygame.display.get_surface() is not None:
            surface = surface.convert_alpha()
    except pygame.error as error:
        raise ValueError(f"Unable to load image {str(image_path)!r}: {error}") from error
    return CanvasImage(image_path, surface)


def image(
    image_object,
    x,
    y,
    w,
    h,
    *,
    origin=(0, 0),
    rotate=None,
    angle_unit="degrees",
):
    """Draw a loaded image scaled to w by h pixels."""
    if not isinstance(image_object, CanvasImage):
        raise TypeError("image() expects an image returned by load_image().")
    origin, rotation = _shape_origin(origin, rotate, angle_unit)
    if w == 0 or h == 0:
        return
    app = _require_app()
    scale_x, scale_y = app.scale_factors()
    target_size = (max(1, round(abs(w) * scale_x)), max(1, round(abs(h) * scale_y)))
    surface = app.pygame.transform.smoothscale(image_object.surface, target_size)
    if w < 0 or h < 0:
        surface = app.pygame.transform.flip(surface, w < 0, h < 0)
    bounds = (min(x, x + w), min(y, y + h), abs(w), abs(h))
    offset, pivot = _placement(bounds, origin, rotation, (x, y))
    center = _map_shape_point((x + w / 2, y + h / 2), offset, pivot, rotation)
    center = app.transform_point(*center)
    angle = app.rotation_degrees()
    if rotation is not None:
        angle -= math.degrees(rotation)
    if angle:
        surface = app.pygame.transform.rotate(surface, angle)
    app.screen.blit(surface, surface.get_rect(center=center))


def configure_sounds(sounds):
    """Map sound names to local file paths for :func:`load_sound`."""
    if not hasattr(sounds, "items"):
        raise TypeError("configure_sounds() expects a mapping of names to file paths.")
    global _sound_paths
    _sound_paths = {str(name): Path(path) for name, path in sounds.items()}
    if _app is not None:
        _app.sounds = dict(_sound_paths)


def load_sound(name):
    """Load a local audio file or a name configured with configure_sounds()."""
    pygame = _load_pygame()
    sound_path = _resolve_asset_path(
        name,
        _app.sounds if _app is not None else _sound_paths,
        "sounds",
    )
    if not sound_path.is_file():
        raise FileNotFoundError(f"No sound file found at {str(sound_path)!r}.")
    try:
        if pygame.mixer.get_init() is None:
            pygame.mixer.init()
        sound = pygame.mixer.Sound(str(sound_path))
    except pygame.error as error:
        raise RuntimeError(f"Unable to load sound {str(sound_path)!r}: {error}") from error
    return CanvasSound(sound_path, sound)


def play_sound(sound):
    """Play or resume a sound returned by :func:`load_sound`."""
    if not isinstance(sound, CanvasSound):
        raise TypeError("play_sound() expects a sound returned by load_sound().")
    if sound._paused and sound._channel is not None:
        sound._channel.unpause()
        sound._paused = False
    else:
        if (
            sound._channel is not None
            and sound._channel.get_sound() is sound._sound
        ):
            sound._channel.stop()
        sound._channel = sound._sound.play()
        sound._paused = False


def pause_sound(sound):
    """Pause a sound returned by :func:`load_sound`."""
    if not isinstance(sound, CanvasSound):
        raise TypeError("pause_sound() expects a sound returned by load_sound().")
    if (
        sound._channel is not None
        and sound._channel.get_sound() is sound._sound
        and sound._channel.get_busy()
    ):
        sound._channel.pause()
        sound._paused = True


def stop_sound(sound):
    """Stop a sound and reset it so the next playback starts at the beginning."""
    if not isinstance(sound, CanvasSound):
        raise TypeError("stop_sound() expects a sound returned by load_sound().")
    if (
        sound._channel is not None
        and sound._channel.get_sound() is sound._sound
    ):
        sound._channel.stop()
    sound._channel = None
    sound._paused = False


def hide_mouse_pointer():
    """Hide the mouse pointer while it is over the canvas."""
    global _mouse_visible
    _mouse_visible = False
    if _app is not None:
        _pygame.mouse.set_visible(False)


def show_mouse_pointer():
    """Show the mouse pointer while it is over the canvas."""
    global _mouse_visible
    _mouse_visible = True
    if _app is not None:
        _pygame.mouse.set_visible(True)


def _key_values(event):
    pygame = _pygame
    name = pygame.key.name(event.key)
    unicode_value = getattr(event, "unicode", "")
    key_value = unicode_value if unicode_value and unicode_value.isprintable() else {
        "return": "Enter",
        "backspace": "Backspace",
        "escape": "Escape",
        "space": " ",
        "page up": "PageUp",
        "page down": "PageDown",
        "left": "ArrowLeft",
        "right": "ArrowRight",
        "up": "ArrowUp",
        "down": "ArrowDown",
    }.get(name, name)
    code_map = {
        "backspace": 8, "tab": 9, "return": 13, "escape": 27, "space": 32,
        "page up": 33, "page down": 34, "end": 35, "home": 36,
        "left": 37, "up": 38, "right": 39, "down": 40, "insert": 45,
        "delete": 46, "left shift": 16, "right shift": 16,
        "left ctrl": 17, "right ctrl": 17, "left alt": 18, "right alt": 18,
    }
    numeric_code = code_map.get(name)
    if numeric_code is None:
        if len(name) == 1 and name.isalpha():
            numeric_code = ord(name.upper())
        elif name.startswith("f") and name[1:].isdigit():
            numeric_code = 111 + int(name[1:])
        else:
            numeric_code = event.key
    code_names = {
        "left": "ArrowLeft", "right": "ArrowRight", "up": "ArrowUp",
        "down": "ArrowDown", "left shift": "ShiftLeft",
        "right shift": "ShiftRight", "left ctrl": "ControlLeft",
        "right ctrl": "ControlRight", "left alt": "AltLeft",
        "right alt": "AltRight", "return": "Enter", "backspace": "Backspace",
        "page up": "PageUp", "page down": "PageDown", "space": "Space",
    }
    if name in code_names:
        code_name = code_names[name]
    elif len(name) == 1 and name.isalpha():
        code_name = f"Key{name.upper()}"
    elif len(name) == 1 and name.isdigit():
        code_name = f"Digit{name}"
    elif name.startswith("f") and name[1:].isdigit():
        code_name = f"F{name[1:]}"
    else:
        code_name = name
    return key_value, numeric_code, code_name


def _dispatch_input(name):
    callback = _callbacks.get(name)
    if callback is not None:
        callback()


def _handle_event(event):
    global button, key, key_code, key_code_name
    pygame = _pygame
    if event.type == pygame.QUIT:
        return False
    if event.type == pygame.MOUSEMOTION:
        _set_mouse_position(*event.pos)
    elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        _set_mouse_position(*event.pos)
        button = {1: 0, 2: 1, 3: 2}.get(event.button, event.button - 1)
        _dispatch_input(
            "mousePressed" if event.type == pygame.MOUSEBUTTONDOWN else "mouseReleased"
        )
    elif event.type in (pygame.KEYDOWN, pygame.KEYUP):
        key, key_code, key_code_name = _key_values(event)
        _dispatch_input("keyPressed" if event.type == pygame.KEYDOWN else "keyReleased")
    return True


def _set_mouse_position(x, y):
    global mouse_x, mouse_y
    mouse_x, mouse_y = x, y


def start(
    draw=None,
    *,
    update=None,
    setup=None,
    mousePressed=None,
    mouseReleased=None,
    keyPressed=None,
    keyReleased=None,
):
    """Start the desktop window and run callbacks until it closes.

    The Pygame event loop runs synchronously on desktop; this function returns
    when the user closes the window. In the browser, the host drives that loop.
    """
    global _app, _callbacks
    callbacks = {
        "draw": draw,
        "update": update,
        "setup": setup,
        "mousePressed": mousePressed,
        "mouseReleased": mouseReleased,
        "keyPressed": keyPressed,
        "keyReleased": keyReleased,
    }
    for name, callback in callbacks.items():
        if callback is not None and not callable(callback):
            raise TypeError(f"{name} must be callable or None.")
    if _app is not None:
        raise RuntimeError("The desktop canvas is already running.")

    pygame = _load_pygame()
    pygame.init()
    pygame.font.init()
    _callbacks = callbacks
    try:
        _app = _PygameCanvas(pygame)
        pygame.display.set_caption("Python Canvas Studio")
        _app.screen.fill(_app.color("#ffffff"))
        clock = pygame.time.Clock()
        if setup is not None:
            setup()
        running = True
        while running:
            for event in pygame.event.get():
                running = _handle_event(event)
                if not running:
                    break
            if not running:
                break
            if update is not None:
                update()
            if draw is not None:
                draw()
            pygame.display.flip()
            clock.tick(60)
    finally:
        for channel in tuple(_channels.values()):
            channel.close()
        _app = None
        _callbacks = {}
        pygame.quit()


init = start
