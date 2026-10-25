"""Processing-style drawing helpers backed by Python Canvas Studio."""

from numbers import Real
import time

import canvas_studio as studio

__all__ = (
    "CENTER",
    "CORNER",
    "CORNERS",
    "RADIUS",
    "background",
    "circle",
    "ellipse",
    "ellipseMode",
    "fill",
    "line",
    "millis",
    "mouseX",
    "mouseY",
    "noFill",
    "noStroke",
    "point",
    "quad",
    "rect",
    "rectMode",
    "size",
    "square",
    "start",
    "stroke",
    "strokeWeight",
    "text",
    "textSize",
    "triangle",
    "width",
    "height",
)

CORNER = "CORNER"
CORNERS = "CORNERS"
CENTER = "CENTER"
RADIUS = "RADIUS"

_fill_color = "#ffffff"
_stroke_color = "#000000"
_stroke_weight = 1
_text_size = 12
_rect_mode = CORNER
_ellipse_mode = CENTER
_started_at = time.monotonic()


class _LiveValue:
    __slots__ = ("_getter",)

    def __init__(self, getter):
        self._getter = getter

    def _value(self):
        return self._getter()

    def __repr__(self):
        return repr(self._value())

    __str__ = __repr__

    def __int__(self):
        return int(self._value())

    def __float__(self):
        return float(self._value())

    def __index__(self):
        return int(self._value())

    def __bool__(self):
        return bool(self._value())

    def __eq__(self, other):
        return self._value() == other

    def __ne__(self, other):
        return self._value() != other

    def __lt__(self, other):
        return self._value() < other

    def __le__(self, other):
        return self._value() <= other

    def __gt__(self, other):
        return self._value() > other

    def __ge__(self, other):
        return self._value() >= other

    def __add__(self, other):
        return self._value() + other

    def __radd__(self, other):
        return other + self._value()

    def __sub__(self, other):
        return self._value() - other

    def __rsub__(self, other):
        return other - self._value()

    def __mul__(self, other):
        return self._value() * other

    def __rmul__(self, other):
        return other * self._value()

    def __truediv__(self, other):
        return self._value() / other

    def __rtruediv__(self, other):
        return other / self._value()

    def __floordiv__(self, other):
        return self._value() // other

    def __rfloordiv__(self, other):
        return other // self._value()

    def __mod__(self, other):
        return self._value() % other

    def __rmod__(self, other):
        return other % self._value()

    def __pow__(self, other):
        return self._value() ** other

    def __rpow__(self, other):
        return other ** self._value()

    def __neg__(self):
        return -self._value()

    def __pos__(self):
        return +self._value()

    def __abs__(self):
        return abs(self._value())

    def __round__(self, ndigits=None):
        return round(self._value(), ndigits) if ndigits is not None else round(self._value())

    def __format__(self, format_spec):
        return format(self._value(), format_spec)


mouseX = _LiveValue(lambda: studio.mouse_x)
mouseY = _LiveValue(lambda: studio.mouse_y)
width = _LiveValue(studio.get_canvas_width)
height = _LiveValue(studio.get_canvas_height)


def _number(value):
    return value._value() if isinstance(value, _LiveValue) else value


def _color(*components):
    if len(components) == 1 and isinstance(components[0], str):
        color = components[0].strip()
        if color.startswith("#") and len(color) in (4, 5):
            return "#" + "".join(character * 2 for character in color[1:])
        return color
    if len(components) not in (1, 2, 3, 4):
        raise TypeError("Expected a grayscale, grayscale-alpha, RGB, or RGBA color.")

    values = components
    if len(values) == 2:
        values = (values[0], values[0], values[0], values[1])
    elif len(values) == 1:
        values = (values[0], values[0], values[0])

    normalized = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError("Color components must be numeric.")
        normalized.append(max(0, min(255, round(value))))

    if len(normalized) == 4:
        return "#{:02x}{:02x}{:02x}{:02x}".format(*normalized)
    return "#{:02x}{:02x}{:02x}".format(*normalized)


def __getattr__(name):
    if name == "mouseX":
        return mouseX
    if name == "mouseY":
        return mouseY
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def size(width, height):
    """Set the canvas dimensions."""
    studio.set_canvas_size(_number(width), _number(height))


def millis():
    """Return elapsed milliseconds since the sketch started."""
    return int((time.monotonic() - _started_at) * 1000)


def background(*components):
    """Clear the canvas using numeric components or a named/hex color."""
    studio.clear(_color(*components))


def fill(*components):
    """Set the fill color for subsequent shapes and text."""
    global _fill_color
    _fill_color = _color(*components)


def noFill():
    """Disable filling for subsequent shapes and text."""
    global _fill_color
    _fill_color = None


def stroke(*components):
    """Set the outline color for subsequent shapes and text."""
    global _stroke_color
    _stroke_color = _color(*components)


def noStroke():
    """Disable outlines for subsequent shapes and text."""
    global _stroke_color
    _stroke_color = None


def strokeWeight(weight):
    """Set the outline width in pixels."""
    global _stroke_weight
    if isinstance(weight, bool) or not isinstance(weight, Real) or weight < 0:
        raise ValueError("strokeWeight() expects a non-negative number.")
    _stroke_weight = weight


def rect(x, y, width, height):
    """Draw a rectangle using the active rectMode()."""
    x, y, width, height = map(_number, (x, y, width, height))
    if _rect_mode == CENTER:
        x, y = x - width / 2, y - height / 2
    elif _rect_mode == RADIUS:
        x, y = x - width, y - height
        width, height = width * 2, height * 2
    elif _rect_mode == CORNERS:
        x2, y2 = width, height
        width, height = abs(x2 - x), abs(y2 - y)
        x, y = min(x, x2), min(y, y2)
    studio.rect(
        x,
        y,
        width,
        height,
        fill=_fill_color,
        stroke=_stroke_color,
        stroke_width=_stroke_weight,
    )


def square(x, y, extent):
    """Draw a square from its top-left corner."""
    rect(x, y, extent, extent)


def rectMode(mode):
    """Set rectangle positioning to CORNER, CORNERS, CENTER, or RADIUS."""
    global _rect_mode
    if mode not in (CORNER, CORNERS, CENTER, RADIUS):
        raise ValueError("rectMode() expects CORNER, CORNERS, CENTER, or RADIUS.")
    _rect_mode = mode


def ellipse(x, y, width, height):
    """Draw an ellipse centered at x, y."""
    x, y, width, height = map(_number, (x, y, width, height))
    if _ellipse_mode == CORNER:
        left, top = x, y
    elif _ellipse_mode == CORNERS:
        x2, y2 = width, height
        width, height = abs(x2 - x), abs(y2 - y)
        left, top = min(x, x2), min(y, y2)
    elif _ellipse_mode == RADIUS:
        left, top = x - width, y - height
        width, height = width * 2, height * 2
    else:
        left, top = x - width / 2, y - height / 2
    studio.ellipse(
        left,
        top,
        width,
        height,
        fill=_fill_color,
        stroke=_stroke_color,
        stroke_width=_stroke_weight,
    )


def ellipseMode(mode):
    """Set ellipse positioning to CORNER, CORNERS, CENTER, or RADIUS."""
    global _ellipse_mode
    if mode not in (CORNER, CORNERS, CENTER, RADIUS):
        raise ValueError(
            "ellipseMode() expects CORNER, CORNERS, CENTER, or RADIUS."
        )
    _ellipse_mode = mode


def circle(x, y, diameter):
    """Draw a circle centered at x, y."""
    studio.circle(
        _number(x),
        _number(y),
        _number(diameter) / 2,
        fill=_fill_color,
        stroke=_stroke_color,
        stroke_width=_stroke_weight,
    )


def line(x1, y1, x2, y2):
    """Draw a line between two points."""
    studio.line(
        _number(x1),
        _number(y1),
        _number(x2),
        _number(y2),
        stroke=_stroke_color,
        width=_stroke_weight,
    )


def point(x, y):
    """Draw a point using the current stroke color and width."""
    if _stroke_color is not None:
        studio.circle(
            _number(x),
            _number(y),
            max(_stroke_weight / 2, 0.5),
            fill=_stroke_color,
            stroke=None,
        )


def triangle(x1, y1, x2, y2, x3, y3):
    """Draw a triangle from three vertex pairs."""
    studio.polygon(
        tuple(
            zip(
                map(_number, (x1, x2, x3)),
                map(_number, (y1, y2, y3)),
            )
        ),
        fill=_fill_color,
        stroke=_stroke_color,
        stroke_width=_stroke_weight,
    )


def quad(x1, y1, x2, y2, x3, y3, x4, y4):
    """Draw a quadrilateral from four vertex pairs."""
    studio.polygon(
        tuple(
            zip(
                map(_number, (x1, x2, x3, x4)),
                map(_number, (y1, y2, y3, y4)),
            )
        ),
        fill=_fill_color,
        stroke=_stroke_color,
        stroke_width=_stroke_weight,
    )


def text(value, x, y):
    """Draw text using the current fill, outline, and text size."""
    studio.text(
        value,
        _number(x),
        _number(y),
        size=_text_size,
        color=_fill_color,
        stroke=_stroke_color,
        stroke_width=_stroke_weight,
    )


def textSize(size):
    """Set the text size in pixels."""
    global _text_size
    if isinstance(size, bool) or not isinstance(size, Real) or size <= 0:
        raise ValueError("textSize() expects a positive number.")
    _text_size = size


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
    """Start the canvas and register Processing-style callbacks."""
    global _started_at
    _started_at = time.monotonic()
    studio.start(
        draw,
        update=update,
        setup=setup,
        mousePressed=mousePressed,
        mouseReleased=mouseReleased,
        keyPressed=keyPressed,
        keyReleased=keyReleased,
    )
