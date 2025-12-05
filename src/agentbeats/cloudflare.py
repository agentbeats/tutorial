import asyncio
import contextlib
import sys

@contextlib.asynccontextmanager
async def quick_tunnel(tunnel_url: str):
    process = await asyncio.create_subprocess_exec(
        "cloudflared", "tunnel",
        "--url", tunnel_url,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    route_future: asyncio.Future[str] = asyncio.Future()
    async def tee_and_find_route(stream: asyncio.StreamReader):
        state = "waiting_for_banner"
        async for line in stream:
            sys.stderr.buffer.write(line)
            # https://github.com/cloudflare/cloudflared/blob/2025.9.1/cmd/cloudflared/tunnel/quick_tunnel.go#L79
            if state == "waiting_for_banner":
                if b"Your quick Tunnel has been created!" in line:
                    state = "waiting_for_route"
            elif state == "waiting_for_route":
                parts = line.split(b"|")
                if len(parts) == 3:
                    route_future.set_result(parts[1].strip().decode())
                    state = "done"
    assert process.stderr
    tee_task = asyncio.create_task(tee_and_find_route(process.stderr))
    route = await route_future
    try:
        yield route
    finally:
        process.terminate()
        await process.wait()
        await tee_task
