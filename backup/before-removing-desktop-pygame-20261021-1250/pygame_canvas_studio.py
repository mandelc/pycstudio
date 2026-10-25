"""Pygame desktop version of the Python Canvas Studio drawing library.

Install Pygame with ``python -m pip install pygame``, import the helpers,
define any of ``setup``, ``update``, ``draw``, ``mousePressed``,
``mouseReleased``, ``keyPressed`` or ``keyReleased``, then call ``run()``::

    from pygame_canvas_studio import *

    def draw():
        clear("#ffffff")
        circle(mouse_x, mouse_y, 24)

    run()

Images are loaded from local files. Drawing helper signatures and callback
names match ``web_canvas_studio.py``.
"""

import importlib
import math
import sys
import traceback
from pathlib import Path


_canvas_width = 960
_canvas_height = 520
mouse_x = 0
mouse_y = 0
key = ""
key_code = ""
key_code_name = ""

_pygame = None
_app = None
_user_namespace = None
_running = False
_pressed_keys = {}
_configured_images = {}


class CanvasImage:
    """An image loaded from a local file and used by ``image()``."""

    def __init__(self, name, surface):
        self.name = str(name)
        self.surface = surface
        self.width, self.height = surface.get_size()


class _PygameCanvas:
    def __init__(self, pygame):
        self.pygame = pygame
        self.screen = pygame.display.set_mode((_canvas_width, _canvas_height))
        self.transform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        self.images = dict(_configured_images)
        self.fonts = {}

    def transform_point(self, x, y):
        a, b, c, d, e, f = self.transform
        return a * x + c * y + e, b * x + d * y + f

    def transform_shape_point(self, x, y, rotation_origin, rotation):
        if rotation_origin is not None and rotation is not None:
            origin_x, origin_y = rotation_origin
            offset_x, offset_y = x - origin_x, y - origin_y
            cosine, sine = math.cos(rotation), math.sin(rotation)
            x = origin_x + offset_x * cosine - offset_y * sine
            y = origin_y + offset_x * sine + offset_y * cosine
        return self.transform_point(x, y)

    def transform_points(self, points, rotation_origin=None, rotation=None):
        return [
            self.transform_shape_point(x, y, rotation_origin, rotation)
            for x, y in points
        ]

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

    def color(self, value):
        try:
            return self.pygame.Color(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid color: {value!r}") from error


def _require_app():
    if _app is None:
        raise RuntimeError("Call run() before using drawing functions.")
    return _app


def _shape_rotation(rotation_origin, rotate, angle_unit):
    if angle_unit not in ("degrees", "radians"):
        raise ValueError("angle_unit must be 'degrees' or 'radians'.")
    if rotation_origin is None or rotate is None:
        return None, None
    try:
        origin = tuple(rotation_origin)
    except TypeError as error:
        raise ValueError(
            "rotation_origin must be a normalized (x, y) pair from 0.0 to 1.0."
        ) from error
    if len(origin) != 2:
        raise ValueError(
            "rotation_origin must be a normalized (x, y) pair from 0.0 to 1.0."
        )
    try:
        origin = tuple(float(value) for value in origin)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "rotation_origin values must be between 0.0 and 1.0."
        ) from error
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in origin):
        raise ValueError("rotation_origin values must be between 0.0 and 1.0.")
    radians = math.radians(rotate) if angle_unit == "degrees" else rotate
    return origin, radians


def _report_callback_error(error):
    print("Canvas callback failed:", file=sys.stderr)
    traceback.print_exception(type(error), error, error.__traceback__)


def _invoke_input_callback(name):
    callback = _user_namespace.get(name) if _user_namespace is not None else None
    if callable(callback):
        try:
            callback()
        except Exception as error:
            _report_callback_error(error)


def _set_mouse_position(position):
    global mouse_x, mouse_y
    mouse_x, mouse_y = position
    if _user_namespace is not None:
        _user_namespace["mouse_x"] = mouse_x
        _user_namespace["mouse_y"] = mouse_y


def _key_values(event):
    pygame = _pygame
    key_name = pygame.key.name(event.key)
    unicode_value = getattr(event, "unicode", "")
    if unicode_value and unicode_value.isprintable():
        key_value = unicode_value
    else:
        key_value = {
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
            "left shift": "Shift",
            "right shift": "Shift",
            "left ctrl": "Control",
            "right ctrl": "Control",
            "left alt": "Alt",
            "right alt": "Alt",
        }.get(key_name, key_name)

    key_code_map = {
        "backspace": 8,
        "tab": 9,
        "return": 13,
        "enter": 13,
        "left shift": 16,
        "right shift": 16,
        "left ctrl": 17,
        "right ctrl": 17,
        "left alt": 18,
        "right alt": 18,
        "-": 189,
        "=": 187,
        "[": 219,
        "]": 221,
        "\\": 220,
        ";": 186,
        "'": 222,
        ",": 188,
        ".": 190,
        "/": 191,
        "`": 192,
        "pause": 19,
        "caps lock": 20,
        "escape": 27,
        "space": 32,
        "page up": 33,
        "page down": 34,
        "end": 35,
        "home": 36,
        "left": 37,
        "up": 38,
        "right": 39,
        "down": 40,
        "insert": 45,
        "delete": 46,
    }
    if key_name in key_code_map:
        numeric_code = key_code_map[key_name]
    elif len(key_name) == 1 and key_name.isalpha():
        numeric_code = ord(key_name.upper())
    elif key_name.startswith("f") and key_name[1:].isdigit():
        numeric_code = 111 + int(key_name[1:])
    else:
        numeric_code = event.key

    key_code_name_map = {
        "left shift": "ShiftLeft",
        "right shift": "ShiftRight",
        "left ctrl": "ControlLeft",
        "right ctrl": "ControlRight",
        "left alt": "AltLeft",
        "right alt": "AltRight",
        "-": "Minus",
        "=": "Equal",
        "[": "BracketLeft",
        "]": "BracketRight",
        "\\": "Backslash",
        ";": "Semicolon",
        "'": "Quote",
        ",": "Comma",
        ".": "Period",
        "/": "Slash",
        "`": "Backquote",
        "return": "Enter",
        "backspace": "Backspace",
        "page up": "PageUp",
        "page down": "PageDown",
        "left": "ArrowLeft",
        "right": "ArrowRight",
        "up": "ArrowUp",
        "down": "ArrowDown",
    }
    if key_name in key_code_name_map:
        code_name = key_code_name_map[key_name]
    elif len(key_name) == 1 and key_name.isalpha():
        code_name = f"Key{key_name.upper()}"
    elif len(key_name) == 1 and key_name.isdigit():
        code_name = f"Digit{key_name}"
    elif key_name.startswith("f") and key_name[1:].isdigit():
        code_name = f"F{key_name[1:]}"
    else:
        code_name = {
            "-": "Minus",
            "=": "Equal",
            "[": "BracketLeft",
            "]": "BracketRight",
            ";": "Semicolon",
            "'": "Quote",
            ",": "Comma",
            ".": "Period",
            "/": "Slash",
            "\\": "Backslash",
            "`": "Backquote",
        }.get(key_name, key_name)
    if key_name == "space":
        code_name = "Space"
    return key_value, numeric_code, code_name


def _set_key(event):
    global key, key_code, key_code_name
    values = _key_values(event)
    if event.type == _pygame.KEYDOWN:
        _pressed_keys[event.key] = values
    elif event.type == _pygame.KEYUP:
        values = _pressed_keys.pop(event.key, values)
    key, key_code, key_code_name = values
    if _user_namespace is not None:
        _user_namespace["key"] = key
        _user_namespace["key_code"] = key_code
        _user_namespace["key_code_name"] = key_code_name


def _point_list(points):
    return [(round(x), round(y)) for x, y in points]


def _draw_polygon(points, color, rotation_origin=None, rotation=None):
    app = _require_app()
    app.pygame.draw.polygon(
        app.screen,
        app.color(color),
        _point_list(app.transform_points(points, rotation_origin, rotation)),
    )


def clear(color="#ffffff"):
    """Fill the canvas with a color."""
    app = _require_app()
    app.screen.fill(app.color(color))


def background(color):
    """Fill the canvas with a color."""
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
    size_changed = (width, height) != (_canvas_width, _canvas_height)
    _canvas_width, _canvas_height = width, height
    if _app is not None and size_changed:
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
    """Move the origin for subsequent drawing calls."""
    _require_app().compose(1, 0, 0, 1, x, y)


def rotate(angle, angle_unit="degrees"):
    """Rotate the canvas clockwise; angle_unit may be degrees or radians."""
    if angle_unit not in ("degrees", "radians"):
        raise ValueError("angle_unit must be 'degrees' or 'radians'.")
    radians = math.radians(angle) if angle_unit == "degrees" else angle
    cosine, sine = math.cos(radians), math.sin(radians)
    _require_app().compose(cosine, sine, -sine, cosine, 0, 0)


def scale(x, y=None):
    """Scale drawing horizontally by x and vertically by y (or x if omitted)."""
    _require_app().compose(x, 0, 0, x if y is None else y, 0, 0)


def reset_transform():
    """Reset translation, rotation, and scaling."""
    _require_app().transform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _shape_rotation_pivot(
    rotation_origin, rotate, left, top, width, height
):
    if rotation_origin is None or rotate is None:
        return None, None
    return (
        left + rotation_origin[0] * width,
        top + rotation_origin[1] * height,
    )


def rect(
    x,
    y,
    width,
    height,
    color="#5b56e8",
    *,
    rotation_origin=None,
    rotate=None,
    angle_unit="degrees",
):
    """Draw a filled rectangle."""
    rotation_origin, rotate = _shape_rotation(
        rotation_origin, rotate, angle_unit
    )
    pivot = _shape_rotation_pivot(
        rotation_origin,
        rotate,
        min(x, x + width),
        min(y, y + height),
        abs(width),
        abs(height),
    )
    _draw_polygon(
        ((x, y), (x + width, y), (x + width, y + height), (x, y + height)),
        color,
        pivot,
        rotate,
    )


def circle(
    x,
    y,
    radius,
    color="#f6c85f",
    *,
    rotation_origin=None,
    rotate=None,
    angle_unit="degrees",
):
    """Draw a filled circle centered at x, y."""
    ellipse(
        x,
        y,
        max(0, radius) * 2,
        max(0, radius) * 2,
        color,
        rotation_origin=rotation_origin,
        rotate=rotate,
        angle_unit=angle_unit,
    )


def ellipse(
    x,
    y,
    width,
    height,
    color="#f6c85f",
    *,
    rotation_origin=None,
    rotate=None,
    angle_unit="degrees",
):
    """Draw a filled ellipse centered at x, y."""
    rotation_origin, rotate = _shape_rotation(
        rotation_origin, rotate, angle_unit
    )
    width = max(0, width)
    height = max(0, height)
    pivot = _shape_rotation_pivot(
        rotation_origin,
        rotate,
        x - width / 2,
        y - height / 2,
        width,
        height,
    )
    segments = max(32, min(256, round(math.pi * max(width, height) / 4)))
    points = [
        (
            x + width / 2 * math.cos(index * math.tau / segments),
            y + height / 2 * math.sin(index * math.tau / segments),
        )
        for index in range(segments)
    ]
    _draw_polygon(points, color, pivot, rotate)


def arc(
    x,
    y,
    radius,
    start_angle,
    end_angle,
    color="#39445c",
    width=2,
    *,
    rotation_origin=None,
    rotate=None,
    angle_unit="degrees",
):
    """Draw a stroked arc; angles increase clockwise, in degrees by default."""
    rotation_origin, rotate = _shape_rotation(
        rotation_origin, rotate, angle_unit
    )
    if angle_unit == "degrees":
        start_angle = math.radians(start_angle)
        end_angle = math.radians(end_angle)
    radius = max(0, radius)
    span = end_angle - start_angle
    if abs(span) > math.tau:
        span = math.copysign(math.tau, span)
    segments = max(2, min(512, math.ceil(abs(span) * max(radius, 1) / 3)))
    points = [
        (
            x + radius * math.cos(start_angle + span * index / segments),
            y + radius * math.sin(start_angle + span * index / segments),
        )
        for index in range(segments + 1)
    ]
    app = _require_app()
    pivot = _shape_rotation_pivot(
        rotation_origin,
        rotate,
        x - radius,
        y - radius,
        radius * 2,
        radius * 2,
    )
    transformed = _point_list(
        app.transform_points(points, pivot, rotate)
    )
    pygame_width = max(
        1,
        round(max(0, width or 1) * sum(app.scale_factors()) / 2),
    )
    app.pygame.draw.lines(
        app.screen,
        app.color(color),
        False,
        transformed,
        pygame_width,
    )


def polygon(
    points,
    color="#5b56e8",
    *,
    rotation_origin=None,
    rotate=None,
    angle_unit="degrees",
):
    """Draw a filled polygon from a sequence of (x, y) points."""
    try:
        vertices = [tuple(point) for point in points]
    except TypeError as error:
        raise ValueError("polygon() expects a sequence of (x, y) points.") from error
    if len(vertices) < 3 or any(len(point) != 2 for point in vertices):
        raise ValueError("polygon() expects at least three (x, y) points.")
    rotation_origin, rotate = _shape_rotation(
        rotation_origin, rotate, angle_unit
    )
    pivot = _shape_rotation_pivot(
        rotation_origin,
        rotate,
        min(point[0] for point in vertices),
        min(point[1] for point in vertices),
        max(point[0] for point in vertices) - min(point[0] for point in vertices),
        max(point[1] for point in vertices) - min(point[1] for point in vertices),
    )
    _draw_polygon(vertices, color, pivot, rotate)


def line(x1, y1, x2, y2, color="#39445c", width=2):
    """Draw a line from x1, y1 to x2, y2."""
    app = _require_app()
    points = _point_list(app.transform_points(((x1, y1), (x2, y2))))
    pygame_width = max(
        1,
        round(max(0, width or 1) * sum(app.scale_factors()) / 2),
    )
    app.pygame.draw.line(app.screen, app.color(color), points[0], points[1], pygame_width)


def text(
    value,
    x,
    y,
    size=20,
    color="#253149",
    *,
    rotation_origin=None,
    rotate=None,
    angle_unit="degrees",
):
    """Draw text at x, y; newline characters start additional lines."""
    rotation_origin, rotate = _shape_rotation(
        rotation_origin, rotate, angle_unit
    )
    app = _require_app()
    scale_x, scale_y = app.scale_factors()
    font_size = max(1, round((size or 20) * (scale_x + scale_y) / 2))
    font = app.fonts.get(font_size)
    if font is None:
        font = app.pygame.font.Font(None, font_size)
        app.fonts[font_size] = font
    lines = str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    line_surfaces = [
        font.render(line, True, app.color(color))
        for line in lines
    ]
    line_height = font.get_linesize()
    unscaled_width = max(
        1,
        max(line_surface.get_width() for line_surface in line_surfaces),
    )
    first_line_height = line_surfaces[0].get_height()
    unscaled_height = first_line_height + line_height * (len(lines) - 1)
    surface = app.pygame.Surface(
        (unscaled_width, max(1, unscaled_height)),
        app.pygame.SRCALPHA,
    )
    for index, line_surface in enumerate(line_surfaces):
        surface.blit(line_surface, (0, index * line_height))
    target_size = (
        max(1, round(surface.get_width() * scale_x)),
        max(1, round(surface.get_height() * scale_y)),
    )
    surface = app.pygame.transform.scale(surface, target_size)
    unrotated_width, unrotated_height = surface.get_size()
    top = y - first_line_height
    pivot = _shape_rotation_pivot(
        rotation_origin,
        rotate,
        x,
        top,
        unrotated_width / scale_x,
        unrotated_height / scale_y,
    )
    angle = app.rotation_degrees()
    if rotate is not None:
        angle -= math.degrees(rotate)
    if angle:
        surface = app.pygame.transform.rotate(surface, angle)
    center_x, center_y = app.transform_shape_point(
        x + unrotated_width / (2 * scale_x),
        top + unrotated_height / (2 * scale_y),
        pivot,
        rotate,
    )
    app.screen.blit(surface, surface.get_rect(center=(center_x, center_y)))


def configure_images(images):
    """Set an optional name-to-local-path mapping for load_image()."""
    if not isinstance(images, dict):
        raise TypeError("configure_images() expects a mapping of names to file paths.")
    global _configured_images
    _configured_images = {str(name): Path(path) for name, path in images.items()}
    if _app is not None:
        _app.images = dict(_configured_images)


def load_image(name):
    """Load a local image file by path or configured name."""
    app = _require_app()
    image_path = app.images.get(str(name), Path(name))
    if not image_path.is_file():
        raise FileNotFoundError(f"No image file found at {str(image_path)!r}.")
    try:
        surface = app.pygame.image.load(str(image_path)).convert_alpha()
    except app.pygame.error as error:
        raise ValueError(f"Unable to load image {str(image_path)!r}: {error}") from error
    return CanvasImage(image_path, surface)


def image(
    image_object,
    x,
    y,
    w,
    h,
    *,
    rotation_origin=None,
    rotate=None,
    angle_unit="degrees",
):
    """Draw a loaded image at x, y, scaled to width w and height h."""
    if not isinstance(image_object, CanvasImage):
        raise TypeError("image() expects an image returned by load_image().")
    rotation_origin, rotate = _shape_rotation(
        rotation_origin, rotate, angle_unit
    )
    if w == 0 or h == 0:
        return
    app = _require_app()
    scale_x, scale_y = app.scale_factors()
    target_size = (
        max(1, round(abs(w) * scale_x)),
        max(1, round(abs(h) * scale_y)),
    )
    surface = app.pygame.transform.smoothscale(image_object.surface, target_size)
    if w < 0 or h < 0:
        surface = app.pygame.transform.flip(surface, w < 0, h < 0)
    pivot = _shape_rotation_pivot(
        rotation_origin,
        rotate,
        min(x, x + w),
        min(y, y + h),
        abs(w),
        abs(h),
    )
    angle = app.rotation_degrees()
    if rotate is not None:
        angle -= math.degrees(rotate)
    if angle:
        surface = app.pygame.transform.rotate(surface, angle)
    center = app.transform_shape_point(
        x + w / 2,
        y + h / 2,
        pivot,
        rotate,
    )
    app.screen.blit(surface, surface.get_rect(center=center))


def _handle_event(event):
    pygame = _pygame
    if event.type == pygame.QUIT:
        return False
    if event.type == pygame.MOUSEMOTION:
        _set_mouse_position(event.pos)
    elif event.type == pygame.MOUSEBUTTONDOWN:
        _set_mouse_position(event.pos)
        _invoke_input_callback("mousePressed")
    elif event.type == pygame.MOUSEBUTTONUP:
        _set_mouse_position(event.pos)
        _invoke_input_callback("mouseReleased")
    elif event.type in (pygame.KEYDOWN, pygame.KEYUP):
        _set_key(event)
        _invoke_input_callback(
            "keyPressed" if event.type == pygame.KEYDOWN else "keyReleased"
        )
    return True


def run():
    """Open the desktop canvas and run callbacks until the window closes."""
    global _pygame, _app, _user_namespace, _running, _pressed_keys
    if _app is not None:
        raise RuntimeError("The desktop canvas is already running.")
    try:
        pygame = importlib.import_module("pygame")
    except ImportError as error:
        raise ImportError(
            "Pygame is required for this library. Install it with "
            "'python -m pip install pygame'."
        ) from error

    pygame.init()
    pygame.font.init()
    _pygame = pygame
    _user_namespace = sys.modules["__main__"].__dict__
    _app = _PygameCanvas(pygame)
    _pressed_keys = {}
    _app.screen.fill(_app.color("#ffffff"))
    pygame.display.set_caption("Python Canvas Studio")
    _running = True

    setup_callback = _user_namespace.get("setup")
    if callable(setup_callback):
        try:
            setup_callback()
        except Exception as error:
            _report_callback_error(error)
            _running = False

    clock = pygame.time.Clock()
    has_frame_callback = callable(_user_namespace.get("update")) or callable(
        _user_namespace.get("draw")
    )
    try:
        while _running:
            for event in pygame.event.get():
                _running = _handle_event(event)
                if not _running:
                    break
            if not _running:
                break
            if has_frame_callback:
                try:
                    update_callback = _user_namespace.get("update")
                    draw_callback = _user_namespace.get("draw")
                    if callable(update_callback):
                        update_callback()
                    if callable(draw_callback):
                        draw_callback()
                except Exception as error:
                    _report_callback_error(error)
                    _running = False
            pygame.display.flip()
            clock.tick(60)
    finally:
        _running = False
        _app = None
        _user_namespace = None
        _pressed_keys = {}
        pygame.quit()
        _pygame = None


__all__ = [
    "CanvasImage",
    "arc",
    "background",
    "circle",
    "clear",
    "configure_images",
    "ellipse",
    "get_canvas_height",
    "get_canvas_width",
    "image",
    "key",
    "key_code",
    "key_code_name",
    "line",
    "load_image",
    "mouse_x",
    "mouse_y",
    "polygon",
    "rect",
    "reset_transform",
    "rotate",
    "run",
    "scale",
    "set_canvas_size",
    "text",
    "translate",
]
