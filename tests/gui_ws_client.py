#!/usr/bin/env python3
"""Exercise the GUI WebSocket command channel for mock integration tests."""

import argparse
import asyncio
import json

import websockets


async def main(url, token):
    async with websockets.connect(f"{url}?token={token}") as socket:
        hello = json.loads(await socket.recv())
        assert hello["type"] == "hello"
        sequence = (
            {"type": "field_write", "axis": 1, "field": ".VELO", "value": 0.25},
            {"type": "move", "axis": 1, "mode": "absolute", "value": 0},
            {"type": "move", "axis": 1, "mode": "absolute", "value": 0.1},
            {"type": "set_home_method", "axis": 1, "method": 10},
            {"type": "home", "axis": 1},
            {"type": "jog_start", "axis": 1, "direction": "cw"},
            {"type": "jog_stop", "axis": 1},
        )
        results = []
        for request_id, command in enumerate(sequence, 1):
            await socket.send(json.dumps({"id": request_id, **command}))
            while True:
                message = json.loads(await socket.recv())
                if message.get("id") != request_id:
                    continue
                assert message["type"] == "command_result", message
                results.append(message["result"])
                break
        assert results[0]["requested"] == 0.25
        assert results[2]["target"] == 0.1 and results[2]["done"] is True
        assert results[3]["home_method"] == 10
        assert results[4]["home_method"] == 10 and results[4]["final"] == 0
        assert results[5]["forward"] is True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("token")
    args = parser.parse_args()
    asyncio.run(main(args.url, args.token))
