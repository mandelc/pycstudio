"""Drawing helpers and user-code execution for Python Canvas Studio."""

import ast
import io
import json
import math
import traceback
from contextlib import redirect_stderr, redirect_stdout

from js import postMessage

_IMAGE_ASSETS = {}
_canvas_width = 960
_canvas_height = 520
mouse_x = 0
mouse_y = 0
key = ""
key_code = ""
key_code_name = ""


def _send_message(message):
    postMessage(json.dumps(message))


def _draw(action, **values):
    _send_message({"type": "draw", "action": action, **values})


def clear(color="#ffffff"):
    """Fill the canvas with a color."""
    _draw("clear", color=color)


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
    _canvas_width = width
    _canvas_height = height
    _draw("canvas_size", width=width, height=height)


def get_canvas_width():
    """Return the canvas width in pixels."""
    return _canvas_width


def get_canvas_height():
    """Return the canvas height in pixels."""
    return _canvas_height


def translate(x, y):
    """Move the canvas origin by x and y pixels."""
    _draw("translate", x=x, y=y)


def rotate(angle, angle_unit="degrees"):
    """Rotate the canvas clockwise; angle_unit may be 'degrees' or 'radians'."""
    if angle_unit not in ("degrees", "radians"):
        raise ValueError("angle_unit must be 'degrees' or 'radians'.")

    radians = math.radians(angle) if angle_unit == "degrees" else angle
    _draw("rotate", angle=radians)


def scale(x, y=None):
    """Scale the canvas horizontally by x and vertically by y (or x if omitted)."""
    _draw("scale", x=x, y=x if y is None else y)


def reset_transform():
    """Reset translation, rotation, and scaling to their defaults."""
    _draw("reset_transform")


def rect(x, y, width, height, color="#5b56e8"):
    """Draw a filled rectangle."""
    _draw("rect", x=x, y=y, width=width, height=height, color=color)


def circle(x, y, radius, color="#f6c85f"):
    """Draw a filled circle centered at x, y."""
    _draw("circle", x=x, y=y, radius=radius, color=color)


def ellipse(x, y, width, height, color="#f6c85f"):
    """Draw a filled ellipse centered at x, y with the given width and height."""
    _draw("ellipse", x=x, y=y, width=width, height=height, color=color)


def arc(
    x,
    y,
    radius,
    start_angle,
    end_angle,
    color="#39445c",
    width=2,
    *,
    angle_unit="degrees",
):
    """Draw a stroked arc; angles increase clockwise and use degrees by default."""
    if angle_unit not in ("degrees", "radians"):
        raise ValueError("angle_unit must be 'degrees' or 'radians'.")

    if angle_unit == "degrees":
        start_angle = math.radians(start_angle)
        end_angle = math.radians(end_angle)

    _draw(
        "arc",
        x=x,
        y=y,
        radius=radius,
        start_angle=start_angle,
        end_angle=end_angle,
        color=color,
        width=width,
    )


def polygon(points, color="#5b56e8"):
    """Draw a filled polygon from a sequence of (x, y) points."""
    try:
        vertices = [tuple(point) for point in points]
    except TypeError as error:
        raise ValueError("polygon() expects a sequence of (x, y) points.") from error

    if len(vertices) < 3 or any(len(point) != 2 for point in vertices):
        raise ValueError("polygon() expects at least three (x, y) points.")

    _draw("polygon", points=vertices, color=color)


def line(x1, y1, x2, y2, color="#39445c", width=2):
    """Draw a line from x1, y1 to x2, y2."""
    _draw("line", x1=x1, y1=y1, x2=x2, y2=y2, color=color, width=width)


def text(value, x, y, size=20, color="#253149"):
    """Draw text at x, y."""
    _draw("text", value=str(value), x=x, y=y, size=size, color=color)


class CanvasImage:
    """An image from the Added Images gallery that can be drawn on the canvas."""

    def __init__(self, name, width, height):
        self.name = name
        self.width = width
        self.height = height


def configure_images(images_json):
    """Set the images made available to user code for the current run."""
    global _IMAGE_ASSETS
    _IMAGE_ASSETS = {
        asset["name"]: asset
        for asset in json.loads(images_json)
    }


def load_image(name):
    """Load an image from the Added Images gallery by its filename."""
    try:
        asset = _IMAGE_ASSETS[name]
    except KeyError as error:
        raise FileNotFoundError(
            f"No image named {name!r} is available. Add it with the Add Image button."
        ) from error
    return CanvasImage(name, asset["width"], asset["height"])


def image(image_object, x, y, w, h):
    """Draw a loaded image at x, y, scaled to width w and height h."""
    if not isinstance(image_object, CanvasImage):
        raise TypeError("image() expects an image returned by load_image().")

    _draw(
        "image",
        name=image_object.name,
        x=x,
        y=y,
        width=w,
        height=h,
    )


def _format_user_error(error):
    """Include the editor line where a user-code error occurred."""
    line_number = getattr(error, "lineno", None)
    if line_number is None:
        user_frames = [
            frame
            for frame in traceback.extract_tb(error.__traceback__)
            if frame.filename == "<user_code>"
        ]
        if user_frames:
            line_number = user_frames[-1].lineno

    message = error.msg if isinstance(error, SyntaxError) else str(error)
    if isinstance(error, SyntaxError) and line_number is not None:
        detected_line = f" (detected at line {line_number})"
        if message.endswith(detected_line):
            message = message[: -len(detected_line)]
    if line_number is not None:
        return f"{message}, line {line_number}"
    return message


def _reject_unconditional_loops(code):
    syntax_tree = ast.parse(code)
    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.While):
            try:
                condition = ast.literal_eval(node.test)
            except (ValueError, TypeError):
                continue
            if bool(condition):
                raise ValueError(
                    f"Unconditional while loop detected on line {node.lineno}. "
                    "Use a condition that can become false."
                )


def run_user_frame():
    """Run update and draw callbacks once, in frame order."""
    update_function = globals().get("update")
    draw_function = globals().get("draw")
    if not callable(update_function) and not callable(draw_function):
        return False

    try:
        if callable(update_function):
            update_function()
        if callable(draw_function):
            draw_function()
    except Exception as error:
        _send_message(
            {"type": "failed", "output": "", "error": _format_user_error(error)}
        )
        return False
    return True


def run_user_input_callback(
    name, key_value=None, key_code_value=None, key_code_name_value=None
):
    """Invoke a mouse or keyboard callback without failing when it is absent."""
    global key, key_code, key_code_name
    if name not in (
        "mousePressed",
        "mouseReleased",
        "keyPressed",
        "keyReleased",
    ):
        return

    if name in ("keyPressed", "keyReleased"):
        key = key_value
        key_code = key_code_value
        key_code_name = key_code_name_value

    callback = globals().get(name)
    if callable(callback):
        output = io.StringIO()
        errors = io.StringIO()
        try:
            with redirect_stdout(output), redirect_stderr(errors):
                callback()
        except Exception as error:
            _send_message(
                {
                    "type": "failed",
                    "output": output.getvalue() + errors.getvalue(),
                    "error": _format_user_error(error),
                }
            )
        else:
            printed_output = output.getvalue() + errors.getvalue()
            if printed_output:
                _send_message({"type": "output", "output": printed_output})


def run_user_code(code):
    """Execute editor code and send its output or error to the page."""
    output = io.StringIO()
    errors = io.StringIO()

    try:
        _reject_unconditional_loops(code)
        with redirect_stdout(output), redirect_stderr(errors):
            exec(compile(code, "<user_code>", "exec"), globals())
            setup_function = globals().get("setup")
            if callable(setup_function):
                setup_function()
    except Exception as error:
        _send_message(
            {
                "type": "failed",
                "output": output.getvalue() + errors.getvalue(),
                "error": _format_user_error(error),
            }
        )
        return False
    else:
        printed_output = output.getvalue() + errors.getvalue()
        features = 0
        has_frame_callback = any(
            callable(globals().get(name))
            for name in ("update", "draw")
        )
        has_mouse_callbacks = any(
            callable(globals().get(name))
            for name in (
                "mousePressed",
                "mouseReleased",
                "keyPressed",
                "keyReleased",
            )
        )
        if has_frame_callback:
            features |= 1
        if has_mouse_callbacks:
            features |= 2

        if features:
            _send_message(
                {
                    "type": "animation" if has_frame_callback else "interactive",
                    "output": printed_output,
                    "interval": 16,
                }
            )
            return features
        _send_message(
            {
                "type": "finished",
                "output": printed_output,
            }
        )
        return 0
