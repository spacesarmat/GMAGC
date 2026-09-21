"""Имитация телефона: отправляет фото на сервер GMAGC и печатает результаты.

  phone_sim.py --link "gmagc://connect?host=192.168.1.5&port=8765&code=ABCD2345" photo.jpg
  phone_sim.py --host 192.168.1.5 --port 8765 --code ABCD-2345 photo.jpg --top 5

Как телефон, уменьшает фото до 1280 px по длинной стороне и отправляет JPEG.
Коды выхода: 0 успех, 1 сервер ответил ошибкой, 2 нет соединения, 3 неверные аргументы или нечитаемое фото.
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))

from gmagc_common.protocol import (  # noqa: E402
    DEFAULT_PORT,
    Connection,
    MatchResponse,
    ProtocolError,
    is_valid_code,
    normalize_code,
    parse_address,
    parse_link,
)

MAX_SIDE = 1280
JPEG_QUALITY = 85


def prepare_jpeg(path: str | Path, max_side: int = MAX_SIDE, quality: int = JPEG_QUALITY) -> bytes:
    """Читает фото (в том числе с не-ASCII именем), уменьшает до max_side по длинной стороне, кодирует в JPEG."""
    image = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"не изображение: {path}")
    height, width = image.shape[:2]
    scale = max_side / max(height, width)
    if scale < 1:
        image = cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("не удалось закодировать JPEG")
    return buffer.tobytes()


def send_match(connection: Connection, jpeg: bytes, top: int | None = None, timeout: float = 30.0) -> tuple[int, dict]:
    path = "/api/match" + (f"?top={top}" if top else "")
    client = http.client.HTTPConnection(connection.host, connection.port, timeout=timeout)
    try:
        client.request(
            "POST", path, body=jpeg, headers={"Authorization": f"Bearer {connection.code}", "Content-Type": "image/jpeg"}
        )
        response = client.getresponse()
        return response.status, json.loads(response.read() or b"{}")
    finally:
        client.close()


def resolve_connection(args: argparse.Namespace) -> Connection | None:
    if args.link:
        return parse_link(args.link)
    if not args.host or not args.code or not is_valid_code(args.code):
        return None
    address = parse_address(f"{args.host}:{args.port}")
    return Connection(address[0], address[1], normalize_code(args.code)) if address else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Отправляет фото на сервер GMAGC как телефон.")
    parser.add_argument("photo", help="файл с фото проекции")
    parser.add_argument("--link", help="ссылка из QR: gmagc://connect?host=…&port=…&code=…")
    parser.add_argument("--host", help="адрес ПК (вместо --link)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--code", help="код доступа (вместе с --host)")
    parser.add_argument("--top", type=int, help="сколько результатов вернуть")
    parser.add_argument("--max-side", type=int, default=MAX_SIDE, help="длинная сторона фото, px")
    args = parser.parse_args(argv)

    connection = resolve_connection(args)
    if connection is None:
        print("нужны верная --link или --host с --code (8 символов)", file=sys.stderr)
        return 3
    try:
        jpeg = prepare_jpeg(args.photo, args.max_side)
    except (OSError, ValueError) as error:
        print(f"не удалось прочитать фото: {error}", file=sys.stderr)
        return 3

    started = time.perf_counter()
    try:
        status, body = send_match(connection, jpeg, args.top)
    except (OSError, http.client.HTTPException) as error:
        print(f"нет соединения с {connection.host}:{connection.port}: {error}", file=sys.stderr)
        return 2
    except ValueError as error:  # ответ не JSON: это не сервер GMAGC
        print(f"сервер ответил не по протоколу: {error}", file=sys.stderr)
        return 1
    elapsed_ms = (time.perf_counter() - started) * 1000

    if status != 200:
        print(f"ошибка {status}: {body.get('error')}: {body.get('message')}", file=sys.stderr)
        return 1
    try:
        response = MatchResponse.from_dict(body)
    except ProtocolError as error:
        print(f"сервер ответил не по протоколу: {error}", file=sys.stderr)
        return 1
    print(
        f"исход: {response.outcome}, на ПК {response.took_ms:.0f} мс, всего {elapsed_ms:.0f} мс, "
        f"запрос {response.request_id}, отправлено {len(jpeg) // 1024} КБ"
    )
    for item in response.results:
        copies = f"  (+{len(item.copies)} копий)" if item.copies else ""
        print(f"{item.rank:>2}. {item.score * 100:5.1f}%  {item.path}{copies}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
