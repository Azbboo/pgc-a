"""Generate prototype images with a GPT Image compatible API.

This script is intentionally dependency-free so it can be used from Open Design
or simple shell workflows. Secrets are read from environment variables or a
local .env file and are never printed.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
from datetime import datetime
from pathlib import Path
from urllib import request
from urllib.error import HTTPError, URLError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = PROJECT_ROOT / "reports" / "prototypes" / "images"

RETRYABLE_HTTP_CODES = {408, 409, 429, 500, 502, 503, 504, 524}


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE lines without overriding the process environment."""

    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_value(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    *,
    retries: int,
    retry_delay: float,
) -> dict[str, object]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        req = request.Request(url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=240) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"HTTP {exc.code}: {detail}")
            if exc.code in RETRYABLE_HTTP_CODES and attempt < retries:
                print(f"retrying_after_http={exc.code} attempt={attempt}/{retries}")
                time.sleep(retry_delay)
                continue
            raise last_error from exc
        except URLError as exc:
            last_error = RuntimeError(f"Request failed: {exc}")
            if attempt < retries:
                print(f"retrying_after_network_error attempt={attempt}/{retries}")
                time.sleep(retry_delay)
                continue
            raise last_error from exc

    if last_error:
        raise last_error
    raise RuntimeError("Request failed for unknown reason")


def download_file(url: str) -> bytes:
    with request.urlopen(url, timeout=240) as resp:
        return resp.read()


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8").strip()
    if args.prompt:
        return args.prompt.strip()
    raise SystemExit("prompt or --prompt-file is required.")


def default_output_path(output_format: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = output_format if output_format in {"png", "jpeg", "webp"} else "png"
    if suffix == "jpeg":
        suffix = "jpg"
    return DEFAULT_OUT_DIR / f"pgc_prototype_{timestamp}.{suffix}"


def build_payload(args: argparse.Namespace, prompt: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": args.model,
        "prompt": prompt,
        "size": args.size,
        "n": args.n,
    }
    if args.quality:
        payload["quality"] = args.quality
    if args.output_format:
        payload["output_format"] = args.output_format
    if args.output_compression is not None:
        payload["output_compression"] = args.output_compression
    if args.background:
        payload["background"] = args.background
    if args.moderation:
        payload["moderation"] = args.moderation
    return payload


def save_image(data: dict[str, object], out_path: Path) -> Path:
    images = data.get("data")
    if not isinstance(images, list) or not images:
        raise RuntimeError(f"No image data returned: {json.dumps(data, ensure_ascii=False)}")

    item = images[0]
    if not isinstance(item, dict):
        raise RuntimeError(f"Unsupported image item: {json.dumps(item, ensure_ascii=False)}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    b64_json = item.get("b64_json") or item.get("image_base64")
    if isinstance(b64_json, str) and b64_json:
        out_path.write_bytes(base64.b64decode(b64_json))
        return out_path

    image_url = item.get("url")
    if isinstance(image_url, str) and image_url:
        out_path.write_bytes(download_file(image_url))
        return out_path

    raise RuntimeError(f"Unsupported response format: {json.dumps(data, ensure_ascii=False)}")


def parse_args() -> argparse.Namespace:
    load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(
        description="Generate a PGC prototype image with gpt-image-2 via an OpenAI-compatible API."
    )
    parser.add_argument("prompt", nargs="?", help="Image prompt. Chinese is supported.")
    parser.add_argument("--prompt-file", help="Read the prompt from a UTF-8 text or markdown file.")
    parser.add_argument(
        "--api-key",
        default=env_value("PGC_IMAGE_API_KEY") or env_value("OPENAI_API_KEY"),
        help="API key. Defaults to PGC_IMAGE_API_KEY, then OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--base-url",
        default=env_value("PGC_IMAGE_BASE_URL", "https://tokenx24.com/v1"),
        help="OpenAI-compatible base URL.",
    )
    parser.add_argument(
        "--model",
        default=env_value("PGC_IMAGE_MODEL", "gpt-image-2"),
        help="Image model id.",
    )
    parser.add_argument(
        "--size",
        default=env_value("PGC_IMAGE_SIZE", "1536x1024"),
        help="Image size, e.g. 1024x1024, 1536x1024, 1024x1536, or auto.",
    )
    parser.add_argument(
        "--quality",
        default=env_value("PGC_IMAGE_QUALITY", "high"),
        help="Rendering quality, e.g. low, medium, high, or auto.",
    )
    parser.add_argument(
        "--output-format",
        default=env_value("PGC_IMAGE_OUTPUT_FORMAT", "png"),
        choices=("png", "jpeg", "webp"),
        help="Returned file format.",
    )
    parser.add_argument(
        "--output-compression",
        type=int,
        default=(
            int(env_value("PGC_IMAGE_OUTPUT_COMPRESSION"))
            if env_value("PGC_IMAGE_OUTPUT_COMPRESSION")
            else None
        ),
        help="Compression 0-100 for jpeg/webp.",
    )
    parser.add_argument(
        "--background",
        default=env_value("PGC_IMAGE_BACKGROUND", "opaque"),
        help="Background mode, e.g. opaque, transparent, or auto.",
    )
    parser.add_argument(
        "--moderation",
        default=env_value("PGC_IMAGE_MODERATION", "auto"),
        help="Moderation mode for GPT Image models.",
    )
    parser.add_argument("--n", type=int, default=int(env_value("PGC_IMAGE_N", "1")), help="Number of images.")
    parser.add_argument("--out", help="Output image path. Defaults to reports/prototypes/images.")
    parser.add_argument("--retries", type=int, default=int(env_value("PGC_IMAGE_RETRIES", "3")))
    parser.add_argument("--retry-delay", type=float, default=float(env_value("PGC_IMAGE_RETRY_DELAY", "8")))
    parser.add_argument("--dry-run", action="store_true", help="Print redacted request metadata without calling the API.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prompt = read_prompt(args)

    if not args.api_key:
        raise SystemExit("PGC_IMAGE_API_KEY or OPENAI_API_KEY is required.")

    url = args.base_url.rstrip("/") + "/images/generations"
    payload = build_payload(args, prompt)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "url": url,
                    "model": args.model,
                    "size": args.size,
                    "quality": args.quality,
                    "output_format": args.output_format,
                    "background": args.background,
                    "prompt_chars": len(prompt),
                    "has_api_key": bool(args.api_key),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    headers = {
        "Authorization": f"Bearer {args.api_key}",
        "Content-Type": "application/json; charset=utf-8",
    }
    data = post_json(url, headers, payload, retries=args.retries, retry_delay=args.retry_delay)
    out_path = Path(args.out) if args.out else default_output_path(args.output_format)
    saved = save_image(data, out_path)
    print(f"saved_image={saved.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
