"""Tkinter desktop version of the Python Canvas Studio drawing library.

Import the helpers, define any of ``setup``, ``update``, ``draw``,
``mousePressed``, ``mouseReleased``, ``keyPressed`` or ``keyReleased``, and
call ``run()`` to open the desktop canvas. For example::

    from desktop_canvas_studio import *

    def draw():
        clear("#ffffff")
        circle(mouse_x, mouse_y, 24)

    run()

Images are loaded from local files. Tkinter's PhotoImage format support varies
by Python/Tk installation; PNG and GIF are commonly supported. Tk Canvas
rotates text directly; rotating images requires Pillow.
"""

import importlib
import math
import sys
import tkinter as tk
import tkinter.font as tkfont
import traceback
from fractions import Fraction
from pathlib import Path


_canvas_width = 960
_canvas_height = 520
mouse_x = 0
mouse_y = 0
key = ""
key_code = ""
key_code_name = ""

_app = None
_user_namespace = None
_frame_after_id = None
_running = False


class CanvasImage:
    """An image loaded from a local file and used by ``image()``."""

    def __init__(self, name, photo):
        self.name = str(name)
        self.photo = photo
        self.width = photo.width()
        self.height = photo.height()


class _DesktopCanvas:
    def __init__(self, root):
        self.root = root
        self.canvas = tk.Canvas(
            root,
            width=_canvas_width,
            height=_canvas_height,
            background="#ffffff",
            highlightthickness=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.transform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        self.images = {}
        self._bind_input()

    def _bind_input(self):
        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<ButtonPress>", self._on_mouse_press)
        self.canvas.bind("<ButtonRelease>", self._on_mouse_release)
        self.canvas.bind("<KeyPress>", self._on_key_press)
        self.canvas.bind("<KeyRelease>", self._on_key_release)
        self.canvas.focus_set()

    def _on_mouse_move(self, event):
        _set_mouse_position(event.x, event.y)

    def _on_mouse_press(self, event):
        _set_mouse_position(event.x, event.y)
        _invoke_input_callback("mousePressed")

    def _on_mouse_release(self, event):
        _set_mouse_position(event.x, event.y)
        _invoke_input_callback("mouseReleased")

    def _on_key_press(self, event):
        _set_key(event)
        _invoke_input_callback("keyPressed")

    def _on_key_release(self, event):
        _set_key(event)
        _invoke_input_callback("keyReleased")

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
            coordinate
            for point in points
            for coordinate in self.transform_shape_point(
                *point, rotation_origin, rotation
            )
        ]

    def transform_width(self, width):
        a, b, c, d, _, _ = self.transform
        return width * (math.hypot(a, b) + math.hypot(c, d)) / 2

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

    def circle_points(self, x, y, radius_x, radius_y=None):
        if radius_y is None:
            radius_y = radius_x
        return [
            self.transform_point(
                x + radius_x * math.cos(index * math.tau / 64),
                y + radius_y * math.sin(index * math.tau / 64),
            )
            for index in range(64)
        ]


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


def _set_mouse_position(x, y):
    global mouse_x, mouse_y
    mouse_x, mouse_y = x, y
    if _user_namespace is not None:
        _user_namespace["mouse_x"] = mouse_x
        _user_namespace["mouse_y"] = mouse_y


def _set_key(event):
    global key, key_code, key_code_name
    keysym = event.keysym
    key = event.char if len(event.char or "") == 1 and event.char.isprintable() else {
        "Return": "Enter",
        "BackSpace": "Backspace",
        "Escape": "Escape",
        "space": " ",
        "Prior": "PageUp",
        "Next": "PageDown",
        "Left": "ArrowLeft",
        "Right": "ArrowRight",
        "Up": "ArrowUp",
        "Down": "ArrowDown",
        "Shift_L": "Shift",
        "Shift_R": "Shift",
        "Control_L": "Control",
        "Control_R": "Control",
        "Alt_L": "Alt",
        "Alt_R": "Alt",
    }.get(keysym, keysym)
    key_code = {
        "BackSpace": 8,
        "Tab": 9,
        "Return": 13,
        "Shift_L": 16,
        "Shift_R": 16,
        "Control_L": 17,
        "Control_R": 17,
        "Alt_L": 18,
        "Alt_R": 18,
        "Pause": 19,
        "Caps_Lock": 20,
        "Escape": 27,
        "space": 32,
        "Prior": 33,
        "Next": 34,
        "End": 35,
        "Home": 36,
        "Left": 37,
        "Up": 38,
        "Right": 39,
        "Down": 40,
        "Insert": 45,
        "Delete": 46,
    }.get(keysym)
    if key_code is None:
        if len(keysym) == 1 and keysym.isalpha():
            key_code = ord(keysym.upper())
        elif keysym.startswith("F") and keysym[1:].isdigit():
            key_code = 111 + int(keysym[1:])
        else:
            key_code = event.keycode
    key_code_name = {
        "Shift_L": "ShiftLeft",
        "Shift_R": "ShiftRight",
        "Control_L": "ControlLeft",
        "Control_R": "ControlRight",
        "Alt_L": "AltLeft",
        "Alt_R": "AltRight",
        "Return": "Enter",
        "BackSpace": "Backspace",
        "space": "Space",
        "Prior": "PageUp",
        "Next": "PageDown",
        "Left": "ArrowLeft",
        "Right": "ArrowRight",
        "Up": "ArrowUp",
        "Down": "ArrowDown",
    }.get(keysym, keysym)
    if _user_namespace is not None:
        _user_namespace["key"] = key
        _user_namespace["key_code"] = key_code
        _user_namespace["key_code_name"] = key_code_name


def clear(color="#ffffff"):
    """Fill the canvas with a color and remove prior drawing."""
    app = _require_app()
    app.canvas.delete("all")
    app.canvas.configure(background=color)


def background(color):
    """Fill the canvas with a color and remove prior drawing."""
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
    if _app is not None:
        _app.canvas.configure(width=width, height=height)
        _app.root.geometry(f"{width}x{height}")
        if size_changed:
            _app.canvas.delete("all")
            _app.canvas.configure(background="#ffffff")
            _app.transform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


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
    """Rotate subsequent drawing clockwise; angles are degrees by default."""
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
    app = _require_app()
    pivot = _shape_rotation_pivot(
        rotation_origin,
        rotate,
        min(x, x + width),
        min(y, y + height),
        abs(width),
        abs(height),
    )
    points = app.transform_points(
        (
            (x, y),
            (x + width, y),
            (x + width, y + height),
            (x, y + height),
        ),
        pivot,
        rotate,
    )
    app.canvas.create_polygon(
        *points,
        fill=color,
        outline="",
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
    radius = max(0, radius)
    ellipse(
        x,
        y,
        radius * 2,
        radius * 2,
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
    app = _require_app()
    pivot = _shape_rotation_pivot(
        rotation_origin,
        rotate,
        x - max(0, width / 2),
        y - max(0, height / 2),
        max(0, width),
        max(0, height),
    )
    points = [
        (
            x + max(0, width / 2) * math.cos(index * math.tau / 64),
            y + max(0, height / 2) * math.sin(index * math.tau / 64),
        )
        for index in range(64)
    ]
    app.canvas.create_polygon(
        *app.transform_points(points, pivot, rotate),
        fill=color,
        outline="",
        smooth=True,
    )


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
    """Draw a stroked arc; angles increase clockwise and use degrees by default."""
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
    segments = max(2, math.ceil(abs(span) * max(abs(radius), 1) / 4))
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
    app.canvas.create_line(
        *app.transform_points(points, pivot, rotate),
        fill=color,
        width=app.transform_width(max(0, width or 1)),
        capstyle=tk.ROUND,
        joinstyle=tk.ROUND,
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
    app = _require_app()
    pivot = _shape_rotation_pivot(
        rotation_origin,
        rotate,
        min(point[0] for point in vertices),
        min(point[1] for point in vertices),
        max(point[0] for point in vertices) - min(point[0] for point in vertices),
        max(point[1] for point in vertices) - min(point[1] for point in vertices),
    )
    app.canvas.create_polygon(
        *app.transform_points(vertices, pivot, rotate),
        fill=color,
        outline="",
    )


def line(x1, y1, x2, y2, color="#39445c", width=2):
    """Draw a line from x1, y1 to x2, y2."""
    app = _require_app()
    app.canvas.create_line(
        *app.transform_points(((x1, y1), (x2, y2))),
        fill=color,
        width=app.transform_width(max(0, width or 1)),
        capstyle=tk.ROUND,
    )


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
    a, b, c, d, _, _ = app.transform
    scale_factor = (math.hypot(a, b) + math.hypot(c, d)) / 2
    font_size = max(
        1,
        round((size or 20) * scale_factor),
    )
    text_value = str(value)
    lines = text_value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    font = tkfont.Font(root=app.root, font=("TkDefaultFont", font_size))
    line_height = font.metrics("linespace")
    pivot = _shape_rotation_pivot(
        rotation_origin,
        rotate,
        x,
        y - line_height / max(scale_factor, 1e-9),
        max(font.measure(line) for line in lines) / max(scale_factor, 1e-9),
        line_height * len(lines) / max(scale_factor, 1e-9),
    )
    options = {}
    if rotation_origin is not None and rotate is not None:
        options["angle"] = -math.degrees(rotate)
    for index, line in enumerate(lines):
        transformed_x, transformed_y = app.transform_shape_point(
            x,
            y + index * line_height / max(scale_factor, 1e-9),
            pivot,
            rotate,
        )
        app.canvas.create_text(
            transformed_x,
            transformed_y,
            text=line,
            anchor=tk.SW,
            fill=color,
            font=("TkDefaultFont", font_size),
            **options,
        )


def configure_images(images):
    """Set an optional name-to-local-path mapping for load_image()."""
    if not isinstance(images, dict):
        raise TypeError("configure_images() expects a mapping of names to file paths.")
    app = _require_app()
    app.images = {str(name): Path(path) for name, path in images.items()}


def load_image(name):
    """Load a local PNG or GIF image by path or configured name."""
    app = _require_app()
    image_path = app.images.get(str(name), Path(name))
    if not image_path.is_file():
        raise FileNotFoundError(f"No image file found at {str(image_path)!r}.")
    try:
        photo = tk.PhotoImage(master=app.root, file=str(image_path))
    except tk.TclError as error:
        raise ValueError(
            f"Unable to load image {str(image_path)!r}; "
            "this Tk installation may not support its format."
        ) from error
    image_object = CanvasImage(image_path, photo)
    app.images[str(name)] = image_path
    app.images[f"__photo__:{image_path}"] = photo
    return image_object


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
    """Draw a loaded image at x, y with the requested width and height."""
    if not isinstance(image_object, CanvasImage):
        raise TypeError("image() expects an image returned by load_image().")
    rotation_origin, rotate = _shape_rotation(
        rotation_origin, rotate, angle_unit
    )
    if w == 0 or h == 0:
        return
    app = _require_app()
    transformed_x, transformed_y = app.transform_point(x, y)
    a, b, c, d, _, _ = app.transform
    scale_x = math.hypot(a, b) * w / image_object.width
    scale_y = math.hypot(c, d) * h / image_object.height

    def resize_axis(photo, factor, axis):
        ratio = Fraction(abs(factor)).limit_denominator(16)
        if ratio.numerator > 1:
            photo = photo.zoom(
                ratio.numerator if axis == "x" else 1,
                ratio.numerator if axis == "y" else 1,
            )
        if ratio.denominator > 1:
            photo = photo.subsample(
                ratio.denominator if axis == "x" else 1,
                ratio.denominator if axis == "y" else 1,
            )
        return photo

    photo = resize_axis(image_object.photo, scale_x, "x")
    photo = resize_axis(photo, scale_y, "y")
    if rotation_origin is not None and rotate is not None and rotate:
        try:
            image_module = importlib.import_module("PIL.Image")
            image_tk_module = importlib.import_module("PIL.ImageTk")
        except ImportError as error:
            raise ImportError(
                "Rotating Tkinter images requires Pillow. "
                "Install it with 'python -m pip install pillow'."
            ) from error
        image_data = image_module.new("RGBA", (photo.width(), photo.height()))
        image_data.putdata(
            [
                (
                    *photo.get(x_index, y_index),
                    0 if photo.transparency_get(x_index, y_index) else 255,
                )
                for y_index in range(photo.height())
                for x_index in range(photo.width())
            ]
        )
        image_data = image_data.rotate(-math.degrees(rotate), expand=True)
        photo = image_tk_module.PhotoImage(image_data, master=app.root)
        pivot = _shape_rotation_pivot(
            rotation_origin,
            rotate,
            min(x, x + w),
            min(y, y + h),
            abs(w),
            abs(h),
        )
        center_x, center_y = app.transform_shape_point(
            x + w / 2, y + h / 2, pivot, rotate
        )
        app.canvas.create_image(center_x, center_y, image=photo, anchor=tk.CENTER)
    else:
        app.canvas.create_image(
            transformed_x,
            transformed_y,
            image=photo,
            anchor=tk.NW,
        )
    app.images[f"__display__:{id(photo)}"] = photo
    app.images[f"__display__:{id(photo)}"] = photo


def run():
    """Open the desktop canvas and run user callbacks until its window closes."""
    global _app, _user_namespace, _running
    if _app is not None:
        raise RuntimeError("The desktop canvas is already running.")
    root = tk.Tk()
    root.title("Python Canvas Studio")
    _user_namespace = sys.modules["__main__"].__dict__
    _app = _DesktopCanvas(root)
    _running = True

    setup_callback = _user_namespace.get("setup")
    if callable(setup_callback):
        try:
            setup_callback()
        except Exception as error:
            _report_callback_error(error)

    def run_frame():
        global _frame_after_id, _running
        if not _running or _app is None:
            return
        update_callback = _user_namespace.get("update")
        draw_callback = _user_namespace.get("draw")
        try:
            if callable(update_callback):
                update_callback()
            if callable(draw_callback):
                draw_callback()
        except Exception as error:
            _report_callback_error(error)
            _running = False
            return
        if callable(update_callback) or callable(draw_callback):
            _frame_after_id = root.after(16, run_frame)

    def close_window():
        global _app, _running, _frame_after_id, _user_namespace
        _running = False
        if _frame_after_id is not None:
            root.after_cancel(_frame_after_id)
            _frame_after_id = None
        _app = None
        _user_namespace = None
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close_window)
    run_frame()
    root.mainloop()


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
