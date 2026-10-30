import asyncio

import uvicorn

from app.main import create_app


def main() -> None:
    server = uvicorn.Server(uvicorn.Config(create_app(), host="0.0.0.0", port=8000))
    # psycopg's async mode can't use the Windows default (proactor) loop.
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(server.serve())


if __name__ == "__main__":
    main()
