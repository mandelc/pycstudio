"""WebSocket relay for browser and desktop Python Canvas Studio programs."""

import argparse
import asyncio
import json
import logging
import secrets

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_channels = {}
_clients = set()
_listeners = {}
_connections = {}
_client_connections = {}


async def _send_error(connection, message):
    await connection.send(json.dumps({"type": "error", "error": message}))


def _remote_endpoint(connection):
    address = connection.remote_address
    if not isinstance(address, tuple) or len(address) < 2:
        return None, None
    return str(address[0]), address[1]


async def _handle_client(connection):
    channel_name = None
    is_broadcast_client = False
    listener_port = None
    role = None
    try:
        first_packet = json.loads(await connection.recv())
        if not isinstance(first_packet, dict):
            await _send_error(connection, "First packet must connect, listen, or join a channel.")
            await connection.close(code=1008, reason="Invalid channel join")
            return

        if first_packet.get("type") == "connect":
            if "port" in first_packet:
                port = first_packet["port"]
                if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                    await _send_error(connection, "Virtual port must be an integer from 1 to 65535.")
                    await connection.close(code=1008, reason="Invalid virtual port")
                    return
                listener = _listeners.get(port)
                request_id = first_packet.get("request_id")
                if listener is None:
                    await connection.send(json.dumps({
                        "type": "connection_error",
                        "request_id": request_id,
                        "error": f"No virtual listener is registered on port {port}.",
                    }))
                    await connection.close(code=1008, reason="Virtual port unavailable")
                    return
                connection_id = secrets.token_urlsafe(18)
                client_address, client_port = _remote_endpoint(connection)
                listener_address, listener_client_port = _remote_endpoint(listener)
                _connections[connection_id] = {
                    "listener": listener,
                    "client": connection,
                    "client_address": client_address,
                    "client_port": client_port,
                    "listener_address": listener_address,
                    "listener_client_port": listener_client_port,
                }
                _client_connections.setdefault(connection, set()).add(connection_id)
                role = "virtual_client"
                await connection.send(json.dumps({
                    "type": "connected",
                    "connection_id": connection_id,
                    "remote_address": listener_address,
                    "remote_port": listener_client_port,
                }))
                await listener.send(json.dumps({
                    "type": "incoming_connection",
                    "connection_id": connection_id,
                    "remote_address": client_address,
                    "remote_port": client_port,
                }))
                logging.info("Virtual connection opened on port %d", port)
            else:
                role = "broadcast"
                is_broadcast_client = True
                _clients.add(connection)
                await connection.send(json.dumps({"type": "ready"}))
                logging.info("Client connected to broadcast server")
        elif first_packet.get("type") == "listen":
            listener_port = first_packet.get("port")
            if (
                isinstance(listener_port, bool)
                or not isinstance(listener_port, int)
                or not 1 <= listener_port <= 65535
            ):
                await _send_error(connection, "Virtual port must be an integer from 1 to 65535.")
                await connection.close(code=1008, reason="Invalid virtual port")
                return
            if listener_port in _listeners:
                await connection.send(json.dumps({
                    "type": "error",
                    "error": f"Virtual port {listener_port} is already in use.",
                }))
                await connection.close(code=1008, reason="Virtual port already in use")
                return
            role = "listener"
            _listeners[listener_port] = connection
            await connection.send(json.dumps({"type": "listening", "port": listener_port}))
            logging.info("Virtual listener registered on port %d", listener_port)
        elif (
            first_packet.get("type") == "join"
            and isinstance(first_packet.get("channel"), str)
            and first_packet["channel"]
        ):
            role = "channel"
            channel_name = first_packet["channel"]
            _channels.setdefault(channel_name, set()).add(connection)
            await connection.send(json.dumps({"type": "ready", "channel": channel_name}))
            logging.info("Client joined channel %r", channel_name)
        else:
            await _send_error(connection, "First packet must connect, listen, or join a named channel.")
            await connection.close(code=1008, reason="Invalid channel join")
            return

        async for raw_packet in connection:
            try:
                packet = json.loads(raw_packet)
            except json.JSONDecodeError:
                await _send_error(connection, "Message must contain valid JSON.")
                continue
            if not isinstance(packet, dict):
                await _send_error(connection, "Message packet must be a JSON object.")
                continue
            if role == "virtual_client":
                connection_id = packet.get("connection_id")
                pair = _connections.get(connection_id)
                if pair is None or pair["client"] is not connection:
                    await _send_error(connection, "Virtual connection is no longer active.")
                    continue
                if packet.get("type") == "data":
                    outgoing = {
                        "type": "data",
                        "connection_id": connection_id,
                        "message": packet.get("message"),
                    }
                    await pair["listener"].send(json.dumps(outgoing, allow_nan=False))
                elif packet.get("type") == "close":
                    await pair["listener"].send(json.dumps({
                        "type": "disconnected",
                        "connection_id": connection_id,
                    }))
                    _connections.pop(connection_id, None)
                    _client_connections.get(connection, set()).discard(connection_id)
                else:
                    await _send_error(connection, "Expected data or close packet for virtual connection.")
            elif role == "listener":
                connection_id = packet.get("connection_id")
                pair = _connections.get(connection_id)
                if pair is None or pair["listener"] is not connection:
                    await _send_error(connection, "Virtual connection is no longer active.")
                    continue
                if packet.get("type") == "data":
                    outgoing = {
                        "type": "data",
                        "connection_id": connection_id,
                        "message": packet.get("message"),
                    }
                    await pair["client"].send(json.dumps(outgoing, allow_nan=False))
                elif packet.get("type") == "close":
                    await pair["client"].send(json.dumps({
                        "type": "disconnected",
                        "connection_id": connection_id,
                    }))
                    _connections.pop(connection_id, None)
                    _client_connections.get(pair["client"], set()).discard(connection_id)
                else:
                    await _send_error(connection, "Expected data or close packet for virtual connection.")
            elif role in ("broadcast", "channel"):
                valid_packet = (
                    packet.get("type") == "message"
                    and "message" in packet
                    and (
                        packet.get("channel") == channel_name
                        if channel_name is not None
                        else "channel" not in packet
                    )
                )
                if not valid_packet:
                    await _send_error(connection, "Invalid message packet for this connection.")
                    continue
                outgoing_packet = {"type": "message", "message": packet["message"]}
                if channel_name is not None:
                    outgoing_packet["channel"] = channel_name
                outgoing = json.dumps(outgoing_packet, allow_nan=False)
                recipients = tuple(
                    _clients if is_broadcast_client else _channels.get(channel_name, ())
                )
                results = await asyncio.gather(
                    *(
                        client.send(outgoing)
                        for client in recipients
                        if client is not connection
                    ),
                    return_exceptions=True,
                )
                if any(isinstance(result, Exception) for result in results):
                    logging.debug("A recipient disconnected during message delivery.")
    except ConnectionClosed:
        pass
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        try:
            await _send_error(connection, f"Invalid JSON packet: {error}")
        except ConnectionClosed:
            pass
    finally:
        if role == "virtual_client":
            for connection_id in tuple(_client_connections.pop(connection, ())):
                pair = _connections.pop(connection_id, None)
                if pair is not None:
                    try:
                        await pair["listener"].send(json.dumps({
                            "type": "disconnected",
                            "connection_id": connection_id,
                        }))
                    except ConnectionClosed:
                        pass
        elif role == "listener":
            if _listeners.get(listener_port) is connection:
                _listeners.pop(listener_port, None)
            for connection_id, pair in tuple(_connections.items()):
                if pair["listener"] is connection:
                    _connections.pop(connection_id, None)
                    _client_connections.get(pair["client"], set()).discard(connection_id)
                    try:
                        await pair["client"].send(json.dumps({
                            "type": "disconnected",
                            "connection_id": connection_id,
                        }))
                    except ConnectionClosed:
                        pass
            logging.info("Virtual listener removed from port %s", listener_port)
        elif is_broadcast_client:
            _clients.discard(connection)
            logging.info("Client disconnected from broadcast server")
        elif channel_name is not None:
            members = _channels.get(channel_name)
            if members is not None:
                members.discard(connection)
                if not members:
                    _channels.pop(channel_name, None)
            logging.info("Client left channel %r", channel_name)


async def serve_forever(host, port):
    async with serve(
        _handle_client,
        host,
        port,
        max_size=1_048_576,
        ping_interval=20,
        ping_timeout=20,
    ) as server:
        logging.info("Canvas Studio message server listening on ws://%s:%d", host, port)
        await server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="network interface to listen on (default: all interfaces)",
    )
    parser.add_argument("--port", type=int, default=8765)
    arguments = parser.parse_args()
    try:
        asyncio.run(serve_forever(arguments.host, arguments.port))
    except KeyboardInterrupt:
        logging.info("Canvas Studio message server stopped.")


if __name__ == "__main__":
    main()
