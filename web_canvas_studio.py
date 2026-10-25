"""Drawing helpers and user-code execution for Python Canvas Studio."""

import ast
import ipaddress
import io
import itertools
import json
import math
import reprlib
import traceback
from contextlib import redirect_stderr, redirect_stdout

from js import BroadcastChannel, WebSocket, postMessage
from pyodide.ffi import create_proxy

__all__ = (
    "CanvasChannel",
    "CanvasConnection",
    "CanvasListener",
    "CanvasSound",
    "arc",
    "background",
    "button",
    "circle",
    "clear",
    "connect",
    "connect_broadcast",
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
    "net_listen",
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
)

_IMAGE_ASSETS = {}
_canvas_width = 960
_canvas_height = 520
_frame_commands = None
mouse_x = 0
mouse_y = 0
button = None
key = ""
key_code = ""
key_code_name = ""
_callbacks = {}
_user_namespace = {}
_channels = {}
_init_called = False
_user_variable_names = set()
_value_repr = reprlib.Repr()
_value_repr.maxstring = 160
_value_repr.maxbytes = 160


def _send_message(message):
    postMessage(json.dumps(message))


def _draw(action, **values):
    command = {"action": action, **values}
    if _frame_commands is not None:
        _frame_commands.append(command)
    else:
        _send_message({"type": "draw", **command})


def clear(color="#ffffff"):
    """Fill the canvas with a color."""
    _draw("clear", color=color)


def background(color):
    """Fill the canvas with a color."""
    clear(color)


def hide_mouse_pointer():
    """Hide the mouse pointer while it is over the canvas."""
    _draw("mouse_pointer", visible=False)


def show_mouse_pointer():
    """Show the mouse pointer while it is over the canvas."""
    _draw("mouse_pointer", visible=True)


class CanvasSound:
    """A sound file from the Added Sounds library."""

    def __init__(self, name):
        self.name = name


_SOUND_ASSETS = {}


class CanvasChannel:
    """A browser-tab or WebSocket channel for JSON messages."""

    def __init__(self, name, on_message, server=None):
        self.name = name
        self.server = server
        self._on_message_callback = on_message
        self._channel = None
        self._socket = None
        self._proxies = []
        self._pending_messages = []
        self._closed = False
        if server is None:
            self._channel = BroadcastChannel.new(name)
            self._set_handler(self._channel, "onmessage", self._receive)
        else:
            self._socket = WebSocket.new(server)
            self._set_handler(self._socket, "onopen", self._on_open)
            self._set_handler(self._socket, "onmessage", self._receive_socket)
            self._set_handler(self._socket, "onerror", self._on_error)
            self._set_handler(self._socket, "onclose", self._on_close)
        _channels[id(self)] = self

    def _set_handler(self, target, name, callback):
        proxy = create_proxy(callback)
        self._proxies.append(proxy)
        setattr(target, name, proxy)

    def send(self, message):
        """Send a JSON-serializable message to other clients on this channel."""
        try:
            payload = json.dumps(message, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise TypeError("Channel messages must be JSON-serializable.") from error
        if self._closed:
            raise RuntimeError("This channel is closed.")
        if self._channel is not None:
            self._channel.postMessage(payload)
            return
        if self._socket.readyState == 1:
            packet = {"type": "message", "message": message}
            if self.name is not None:
                packet["channel"] = self.name
            self._socket.send(json.dumps(packet, allow_nan=False))
        elif self._socket.readyState == 0:
            self._pending_messages.append(message)
        else:
            raise RuntimeError("The WebSocket channel is not connected.")

    def close(self):
        """Close the channel and release its browser callbacks."""
        if self._closed:
            return
        self._closed = True
        if self._channel is not None:
            self._channel.close()
        if self._socket is not None:
            self._socket.close()
        for proxy in self._proxies:
            proxy.destroy()
        self._proxies.clear()
        _channels.pop(id(self), None)

    def _receive(self, event):
        self._dispatch(json.loads(str(event.data)))

    def _receive_socket(self, event):
        packet = json.loads(str(event.data))
        if packet.get("type") == "message":
            self._dispatch(packet.get("message"))
        elif packet.get("type") == "error":
            _send_message(
                {
                    "type": "failed",
                    "output": "",
                    "error": packet.get("error", "WebSocket server error."),
                }
            )

    def _on_open(self, _event):
        if self.name is None:
            self._socket.send(json.dumps({"type": "connect"}))
        else:
            self._socket.send(json.dumps({"type": "join", "channel": self.name}))
        pending_messages, self._pending_messages = self._pending_messages, []
        for message in pending_messages:
            self.send(message)

    def _on_error(self, _event):
        destination = self.server or f"browser channel {self.name!r}"
        _send_message(
            {
                "type": "failed",
                "output": "",
                "error": (
                    f"Unable to connect to {destination}. Check that the relay "
                    "is running, the host and port are correct, the port is "
                    "allowed through the firewall, and the connection security "
                    "matches the Studio page (ws:// for HTTP, wss:// for HTTPS)."
                ),
            }
        )

    def _on_close(self, _event):
        self._closed = True
        _channels.pop(id(self), None)
        for proxy in self._proxies:
            proxy.destroy()
        self._proxies.clear()

    def _dispatch(self, message):
        output = io.StringIO()
        errors = io.StringIO()
        try:
            with redirect_stdout(output), redirect_stderr(errors):
                self._on_message_callback(message)
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


class CanvasConnection:
    """A virtual peer connection routed through the relay."""

    def __init__(
        self,
        socket,
        connection_id=None,
        owner=None,
        on_message_callback=None,
        client_host=None,
        client_port=None,
        secure=False,
        remote_address=None,
        remote_port=None,
    ):
        self._socket = socket
        self._channel = None
        self._connection_id = connection_id
        self._owner = owner
        self._on_message_callback = on_message_callback
        self._remote_address = remote_address
        self._remote_port = remote_port
        self._pending_messages = []
        self._closed = False
        self._client = client_host is not None
        self._proxies = []
        if self._client:
            formatted_host = client_host.strip()
            if ":" in formatted_host and not formatted_host.startswith("["):
                formatted_host = f"[{formatted_host}]"
            scheme = "wss" if secure else "ws"
            self.server = f"{scheme}://{formatted_host}:{client_port}"
            self._socket = WebSocket.new(self.server)
            self._set_handler(self._socket, "onopen", self._on_open)
            self._set_handler(self._socket, "onmessage", self._on_message)
            self._set_handler(self._socket, "onerror", self._on_error)
            self._set_handler(self._socket, "onclose", self._on_close)
            _channels[id(self)] = self

    def _set_handler(self, target, name, callback):
        proxy = create_proxy(callback)
        self._proxies.append(proxy)
        setattr(target, name, proxy)

    def on_message(self, callback):
        """Register the callback for messages received on this connection."""
        if not callable(callback):
            raise TypeError("callback must be callable.")
        if self._closed:
            raise RuntimeError("This connection is closed.")
        self._on_message_callback = callback

    def get_remote_address(self):
        """Return the peer address as observed by the relay, or None until connected."""
        return self._remote_address

    def get_remote_port(self):
        """Return the peer port as observed by the relay, or None until connected."""
        return self._remote_port

    def send(self, message):
        """Send a JSON-serializable message to the paired peer."""
        try:
            json.dumps(message, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise TypeError("Connection messages must be JSON-serializable.") from error
        if self._closed:
            raise RuntimeError("This connection is closed.")
        if self._connection_id is None or self._socket.readyState != 1:
            self._pending_messages.append(message)
            return
        self._send_packet(message)

    def _send_packet(self, message):
        self._socket.send(json.dumps({
            "type": "data",
            "connection_id": self._connection_id,
            "message": message,
        }, allow_nan=False))

    def _mark_connected(self, connection_id):
        self._connection_id = connection_id
        pending, self._pending_messages = self._pending_messages, []
        for message in pending:
            self._send_packet(message)

    def _receive(self, message):
        if self._on_message_callback is None:
            _send_message({
                "type": "output",
                "output": f"Received network message: {_safe_value_repr(message)}",
            })
            return
        output = io.StringIO()
        errors = io.StringIO()
        try:
            with redirect_stdout(output), redirect_stderr(errors):
                self._on_message_callback(message)
        except Exception as error:
            _send_message({
                "type": "failed",
                "output": output.getvalue() + errors.getvalue(),
                "error": _format_user_error(error),
            })
        else:
            printed_output = output.getvalue() + errors.getvalue()
            if printed_output:
                _send_message({"type": "output", "output": printed_output})

    def _handle_packet(self, packet):
        packet_type = packet.get("type")
        if packet_type == "connected" and self._client:
            self._remote_address = packet.get("remote_address")
            self._remote_port = packet.get("remote_port")
            self._mark_connected(packet["connection_id"])
        elif packet_type == "data" and packet.get("connection_id") == self._connection_id:
            self._receive(packet.get("message"))
        elif packet_type == "disconnected" and packet.get("connection_id") == self._connection_id:
            self._mark_closed()
            if self._client:
                self._socket.close()
        elif packet_type in ("error", "connection_error"):
            _send_message({
                "type": "failed",
                "output": "",
                "error": packet.get("error", "Message relay error."),
            })
            if self._client:
                self._mark_closed()
                self._socket.close()

    def _on_open(self, _event):
        self._socket.send(json.dumps({"type": "connect", "port": self._owner}))

    def _on_message(self, event):
        self._handle_packet(json.loads(str(event.data)))

    def _on_error(self, _event):
        _send_message({
            "type": "failed",
            "output": "",
            "error": f"Unable to connect to virtual server {self.server}.",
        })

    def _on_close(self, _event):
        self._mark_closed()

    def _mark_closed(self):
        if self._closed:
            return
        self._closed = True
        _channels.pop(id(self), None)
        if isinstance(self._owner, CanvasListener):
            self._owner._connections.pop(self._connection_id, None)
        for proxy in self._proxies:
            proxy.destroy()
        self._proxies.clear()

    def close(self):
        """Close this virtual connection."""
        if self._closed:
            return
        if self._connection_id is not None and self._socket.readyState == 1:
            self._socket.send(json.dumps({
                "type": "close",
                "connection_id": self._connection_id,
            }))
        self._mark_closed()
        if self._client:
            self._socket.close()


class CanvasListener:
    """A virtual service port registered with the message relay."""

    def __init__(self, port, on_connected, relay_host, secure):
        formatted_host = relay_host.strip()
        if ":" in formatted_host and not formatted_host.startswith("["):
            formatted_host = f"[{formatted_host}]"
        scheme = "wss" if secure else "ws"
        self.port = port
        self.server = f"{scheme}://{formatted_host}:{port}"
        self._channel = None
        self._on_connected_callback = on_connected
        self._connections = {}
        self._closed = False
        self._proxies = []
        self._socket = WebSocket.new(self.server)
        self._set_handler(self._socket, "onopen", self._on_open)
        self._set_handler(self._socket, "onmessage", self._on_message)
        self._set_handler(self._socket, "onerror", self._on_error)
        self._set_handler(self._socket, "onclose", self._on_close)
        _channels[id(self)] = self

    def _set_handler(self, target, name, callback):
        proxy = create_proxy(callback)
        self._proxies.append(proxy)
        setattr(target, name, proxy)

    def _on_open(self, _event):
        self._socket.send(json.dumps({"type": "listen", "port": self.port}))

    def _on_message(self, event):
        packet = json.loads(str(event.data))
        packet_type = packet.get("type")
        if packet_type == "incoming_connection":
            connection_id = packet["connection_id"]
            connection = CanvasConnection(
                self._socket,
                connection_id,
                owner=self,
                remote_address=packet.get("remote_address"),
                remote_port=packet.get("remote_port"),
            )
            self._connections[connection_id] = connection
            output = io.StringIO()
            errors = io.StringIO()
            try:
                with redirect_stdout(output), redirect_stderr(errors):
                    self._on_connected_callback(connection)
            except Exception as error:
                _send_message({
                    "type": "failed",
                    "output": output.getvalue() + errors.getvalue(),
                    "error": _format_user_error(error),
                })
            else:
                printed_output = output.getvalue() + errors.getvalue()
                if printed_output:
                    _send_message({"type": "output", "output": printed_output})
        elif packet_type in ("data", "disconnected"):
            connection = self._connections.get(packet.get("connection_id"))
            if connection is not None:
                connection._handle_packet(packet)
        elif packet_type == "error":
            _send_message({
                "type": "failed",
                "output": "",
                "error": packet.get("error", "Message relay error."),
            })

    def _on_error(self, _event):
        _send_message({
            "type": "failed",
            "output": "",
            "error": f"Unable to connect to message relay {self.server}.",
        })

    def _on_close(self, _event):
        self._mark_closed()

    def _mark_closed(self):
        if self._closed:
            return
        self._closed = True
        _channels.pop(id(self), None)
        for connection in tuple(self._connections.values()):
            connection._mark_closed()
        self._connections.clear()
        for proxy in self._proxies:
            proxy.destroy()
        self._proxies.clear()

    def close(self):
        """Stop listening and close all virtual peer connections."""
        if self._closed:
            return
        self._socket.close()
        self._mark_closed()


def open_channel(name, on_message, server=None):
    """Open a browser-tab channel or connect to a WebSocket message server.

    With no server, this uses BroadcastChannel between same-origin browser tabs.
    Pass a ``ws://`` or ``wss://`` URL to communicate with desktop clients and
    other browsers through a running ``canvas_studio_server.py`` instance.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("Channel name must be a non-empty string.")
    if not callable(on_message):
        raise TypeError("on_message must be callable.")
    if server is not None and (
        not isinstance(server, str)
        or not server.startswith(("ws://", "wss://"))
    ):
        raise ValueError("server must be a ws:// or wss:// URL, or None.")
    try:
        return CanvasChannel(name, on_message, server)
    except Exception as error:
        raise RuntimeError(f"Unable to open channel {name!r}.") from error


def _validate_relay_address(host, port, secure):
    if not isinstance(host, str) or not host.strip():
        raise ValueError("host must be a non-empty hostname or IP address.")
    candidate = host.strip()
    if "://" in candidate or "/" in candidate:
        raise ValueError("host must not include a scheme, path, or port.")
    if ":" in candidate:
        ipv6 = candidate[1:-1] if candidate.startswith("[") and candidate.endswith("]") else candidate
        try:
            ipaddress.IPv6Address(ipv6)
        except ipaddress.AddressValueError as error:
            raise ValueError("host must not include a port; use an IPv6 address if needed.") from error
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer from 1 to 65535.")
    if not isinstance(secure, bool):
        raise TypeError("secure must be a bool.")


def connect(host, port, *, secure=False):
    """Connect to the virtual service on the relay host and port."""
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer from 1 to 65535.")
    _validate_relay_address(host, port, secure)
    try:
        return CanvasConnection(
            None,
            owner=port,
            client_host=host,
            client_port=port,
            secure=secure,
        )
    except Exception as error:
        raise RuntimeError(f"Unable to connect to virtual server {host}:{port}.") from error


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


def net_listen(port, on_connected, *, relay_host="127.0.0.1", secure=False):
    """Register this virtual service on the relay running at port."""
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer from 1 to 65535.")
    if not callable(on_connected):
        raise TypeError("on_connected must be callable.")
    _validate_relay_address(relay_host, port, secure)
    return CanvasListener(port, on_connected, relay_host, secure)


def configure_sounds(sounds_json):
    """Set the sounds made available to user code for the current run."""
    global _SOUND_ASSETS
    _SOUND_ASSETS = {
        asset["name"]: asset
        for asset in json.loads(sounds_json)
    }


def load_sound(name):
    """Load a sound by filename from the Added Sounds library."""
    if name not in _SOUND_ASSETS:
        raise FileNotFoundError(
            f"No sound named {name!r} is available. Add it with the Add Sound button."
        )
    return CanvasSound(name)


def play_sound(sound):
    """Play or resume a sound returned by load_sound()."""
    if not isinstance(sound, CanvasSound):
        raise TypeError("play_sound() expects a sound returned by load_sound().")
    _send_message({"type": "audio", "action": "play", "name": sound.name})


def pause_sound(sound):
    """Pause a sound returned by load_sound()."""
    if not isinstance(sound, CanvasSound):
        raise TypeError("pause_sound() expects a sound returned by load_sound().")
    _send_message({"type": "audio", "action": "pause", "name": sound.name})


def stop_sound(sound):
    """Stop a sound and reset it to the beginning."""
    if not isinstance(sound, CanvasSound):
        raise TypeError("stop_sound() expects a sound returned by load_sound().")
    _send_message({"type": "audio", "action": "stop", "name": sound.name})


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
    """Register setup, frame, and input callbacks for the current program."""
    global _init_called
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

    _callbacks.clear()
    _callbacks.update(callbacks)
    _init_called = True
    if setup is not None:
        setup()


init = start


def get_canvas_width():
    """Return the canvas width in pixels."""
    return _canvas_width


def get_canvas_height():
    """Return the canvas height in pixels."""
    return _canvas_height


def _set_mouse_position(x, y):
    global mouse_x, mouse_y
    mouse_x = x
    mouse_y = y
    _user_namespace["mouse_x"] = x
    _user_namespace["mouse_y"] = y


def translate(x, y):
    """Move the canvas origin by x and y pixels."""
    _draw("translate", x=x, y=y)


def rotate(angle, angle_unit="degrees"):
    """Rotate the canvas clockwise; angle_unit may be 'degrees' or 'radians'."""
    if angle_unit not in ("degrees", "radians"):
        raise ValueError("angle_unit must be 'degrees' or 'radians'.")

    radians = math.radians(angle) if angle_unit == "degrees" else angle
    _draw("rotate", angle=radians)


def _normalized_shape_origin(origin, argument_name):
    pair_error = (
        f"{argument_name} must be a normalized (x, y) pair from 0.0 to 1.0."
    )
    values_error = f"{argument_name} values must be between 0.0 and 1.0."
    try:
        values = tuple(origin)
    except TypeError as error:
        raise ValueError(pair_error) from error
    if len(values) != 2:
        raise ValueError(pair_error)
    try:
        normalized_origin = tuple(float(value) for value in values)
    except (TypeError, ValueError) as error:
        raise ValueError(values_error) from error
    if any(
        not math.isfinite(value) or not 0 <= value <= 1
        for value in normalized_origin
    ):
        raise ValueError(values_error)
    return normalized_origin


def _shape_rotation(rotation_origin, rotate, angle_unit):
    if angle_unit not in ("degrees", "radians"):
        raise ValueError("angle_unit must be 'degrees' or 'radians'.")
    if rotation_origin is None or rotate is None:
        return None, None
    origin = _normalized_shape_origin(rotation_origin, "rotation_origin")
    radians = math.radians(rotate) if angle_unit == "degrees" else rotate
    return origin, radians


def _shape_origin(origin, rotate, angle_unit):
    if angle_unit not in ("degrees", "radians"):
        raise ValueError("angle_unit must be 'degrees' or 'radians'.")
    if origin is None:
        return None, None
    normalized_origin = _normalized_shape_origin(origin, "origin")
    radians = (
        math.radians(rotate)
        if rotate is not None and angle_unit == "degrees"
        else rotate
    )
    return normalized_origin, radians


def scale(x, y=None):
    """Scale the canvas horizontally by x and vertically by y (or x if omitted)."""
    _draw("scale", x=x, y=x if y is None else y)


def reset_transform():
    """Reset translation, rotation, and scaling to their defaults."""
    _draw("reset_transform")


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
    origin, rotate = _shape_origin(origin, rotate, angle_unit)
    _draw(
        "rect",
        x=x,
        y=y,
        width=width,
        height=height,
        fill=fill,
        stroke=stroke,
        stroke_width=stroke_width,
        origin=origin,
        rotate=rotate,
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
    rotation_origin, rotate = _shape_rotation(
        rotation_origin, rotate, angle_unit
    )
    _draw(
        "circle",
        x=x,
        y=y,
        radius=radius,
        fill=fill,
        stroke=stroke,
        stroke_width=stroke_width,
        rotation_origin=rotation_origin,
        rotate=rotate,
    )


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
    origin, rotate = _shape_origin(origin, rotate, angle_unit)
    _draw(
        "ellipse",
        x=x,
        y=y,
        width=width,
        height=height,
        fill=fill,
        stroke=stroke,
        stroke_width=stroke_width,
        origin=origin,
        rotate=rotate,
    )


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
    """Draw a stroked arc, anchoring its diameter bounds at x, y by default."""
    origin, rotate = _shape_origin(origin, rotate, angle_unit)

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
        stroke=stroke,
        width=width,
        origin=origin,
        rotate=rotate,
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

    origin, rotate = _shape_origin(origin, rotate, angle_unit)
    _draw(
        "polygon",
        points=vertices,
        fill=fill,
        stroke=stroke,
        stroke_width=stroke_width,
        x=x,
        y=y,
        origin=origin,
        rotate=rotate,
    )


def line(x1, y1, x2, y2, stroke="#000", width=2):
    """Draw a line from x1, y1 to x2, y2."""
    _draw("line", x1=x1, y1=y1, x2=x2, y2=y2, stroke=stroke, width=width)


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
    origin, rotate = _shape_origin(origin, rotate, angle_unit)
    _draw(
        "text",
        value=str(value),
        x=x,
        y=y,
        size=size,
        color=color,
        align=align,
        stroke=stroke,
        stroke_width=stroke_width,
        origin=origin,
        rotate=rotate,
    )


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
    """Draw a loaded image, anchoring its top-left at x, y by default."""
    if not isinstance(image_object, CanvasImage):
        raise TypeError("image() expects an image returned by load_image().")

    origin, rotate = _shape_origin(origin, rotate, angle_unit)
    _draw(
        "image",
        name=image_object.name,
        x=x,
        y=y,
        width=w,
        height=h,
        origin=origin,
        rotate=rotate,
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
    global _frame_commands
    update_function = _callbacks.get("update")
    draw_function = _callbacks.get("draw")
    if not callable(update_function) and not callable(draw_function):
        return False

    _frame_commands = []
    output = io.StringIO()
    errors = io.StringIO()
    try:
        with redirect_stdout(output), redirect_stderr(errors):
            if callable(update_function):
                update_function()
            if callable(draw_function):
                draw_function()
    except Exception as error:
        _frame_commands = None
        _send_message(
            {
                "type": "failed",
                "output": output.getvalue() + errors.getvalue(),
                "error": _format_user_error(error),
            }
        )
        return False
    commands = _frame_commands
    _frame_commands = None
    if commands:
        _send_message({"type": "draw_batch", "commands": commands})
    printed_output = output.getvalue() + errors.getvalue()
    if printed_output:
        _send_message({"type": "output", "output": printed_output})
    return True


def run_user_input_callback(
    name,
    key_value=None,
    key_code_value=None,
    key_code_name_value=None,
    button_value=None,
):
    """Invoke a mouse or keyboard callback without failing when it is absent."""
    global button, key, key_code, key_code_name
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
        _user_namespace["key"] = key
        _user_namespace["key_code"] = key_code
        _user_namespace["key_code_name"] = key_code_name
    elif name in ("mousePressed", "mouseReleased"):
        button = button_value
        _user_namespace["button"] = button

    callback = _callbacks.get(name)
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


class _UserVariableCollector(ast.NodeVisitor):
    def __init__(self):
        self.names = set()

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            self.names.add(node.id)

    def visit_Import(self, node):
        self.names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node):
        self.names.update(
            alias.asname or alias.name
            for alias in node.names
            if alias.name != "*"
        )

    def visit_FunctionDef(self, node):
        self._collect_global_declarations(node)

    def visit_AsyncFunctionDef(self, node):
        self._collect_global_declarations(node)

    def visit_ClassDef(self, node):
        pass

    def _collect_global_declarations(self, node):
        for child in ast.walk(node):
            if isinstance(child, ast.Global):
                self.names.update(child.names)


def _safe_value_repr(value, depth=0, seen=None):
    value_type = type(value)
    if value is None or value_type in (bool, float):
        return repr(value)
    if value_type is int:
        return repr(value) if value.bit_length() <= 2048 else f"<int: {value.bit_length()} bits>"
    if value_type in (str, bytes):
        return _value_repr.repr(value)
    if value_type not in (list, tuple, set, frozenset, dict):
        return f"<{value_type.__name__}>"
    if depth >= 3:
        return f"<{value_type.__name__}: max display depth>"

    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return "<recursive>"
    seen.add(identity)
    try:
        if value_type is dict:
            items = list(itertools.islice(value.items(), 8))
            displayed = [
                f"{_safe_value_repr(key, depth + 1, seen)}: "
                f"{_safe_value_repr(item, depth + 1, seen)}"
                for key, item in items
            ]
            if len(value) > 8:
                displayed.append(f"… {len(value) - 8} more")
            result = "{" + ", ".join(displayed) + "}"
        else:
            items = (
                list(value[:8])
                if value_type in (list, tuple)
                else list(itertools.islice(value, 8))
            )
            displayed = [
                _safe_value_repr(item, depth + 1, seen)
                for item in items
            ]
            if len(value) > 8:
                displayed.append(f"… {len(value) - 8} more")
            if value_type is list:
                result = "[" + ", ".join(displayed) + "]"
            elif value_type is tuple:
                result = "(" + ", ".join(displayed)
                result += "," if len(value) == 1 else ""
                result += ")"
            elif value_type is set:
                result = "{" + ", ".join(displayed) + "}" if value else "set()"
            else:
                result = (
                    "frozenset({" + ", ".join(displayed) + "})"
                    if value
                    else "frozenset()"
                )
        return result[:500] + ("…" if len(result) > 500 else "")
    finally:
        seen.remove(identity)


def get_user_memory_snapshot():
    variables = []
    names = sorted(_user_variable_names)
    for name in names[:100]:
        if name not in _user_namespace:
            continue
        value = _user_namespace[name]
        if callable(value):
            continue
        variables.append(
            {
                "name": name,
                "type": type(value).__name__,
                "value": _safe_value_repr(value),
            }
        )
    return json.dumps(
        {
            "variables": variables,
            "omitted": max(0, len(names) - 100),
        }
    )


def run_user_code(code):
    """Execute editor code and send its output or error to the page."""
    global _callbacks, _init_called, _user_namespace, _user_variable_names
    output = io.StringIO()
    errors = io.StringIO()

    try:
        for channel in tuple(_channels.values()):
            channel.close()
        _callbacks = {}
        _init_called = False
        _user_namespace = {"__name__": "__main__"}
        for name in __all__:
            _user_namespace[name] = globals()[name]
        syntax_tree = ast.parse(code)
        collector = _UserVariableCollector()
        collector.visit(syntax_tree)
        _user_variable_names = collector.names
        _reject_unconditional_loops(code)
        with redirect_stdout(output), redirect_stderr(errors):
            exec(compile(code, "<user_code>", "exec"), _user_namespace)
            imports_library = any(
                (
                    isinstance(node, ast.Import)
                    and any(alias.name == "canvas_studio" for alias in node.names)
                )
                or (
                    isinstance(node, ast.ImportFrom)
                    and node.module == "canvas_studio"
                )
                for node in ast.walk(syntax_tree)
            )
            if not imports_library and not _init_called:
                for name in (
                    "draw",
                    "update",
                    "setup",
                    "mousePressed",
                    "mouseReleased",
                    "keyPressed",
                    "keyReleased",
                ):
                    _callbacks[name] = _user_namespace.get(name)
                setup_function = _callbacks.get("setup")
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
            callable(_callbacks.get(name))
            for name in ("update", "draw")
        )
        has_mouse_callbacks = any(
            callable(_callbacks.get(name))
            for name in (
                "mousePressed",
                "mouseReleased",
                "keyPressed",
                "keyReleased",
            )
        )
        has_channel_callbacks = bool(_channels)
        has_network_channels = any(
            channel._socket is not None for channel in _channels.values()
        )
        has_tab_channels = any(
            channel._channel is not None for channel in _channels.values()
        )
        if has_frame_callback:
            features |= 1
        if has_mouse_callbacks:
            features |= 2
        if has_channel_callbacks:
            features |= 4
        if has_network_channels:
            features |= 8
        if has_tab_channels:
            features |= 16

        if features:
            _send_message(
                {
                    "type": "animation" if has_frame_callback else "interactive",
                    "output": printed_output,
                    "interval": 16,
                    "features": features,
                }
            )
            return features
        _send_message(
            {
                "type": "finished",
                "output": printed_output,
                "memory": get_user_memory_snapshot(),
            }
        )
        return 0
