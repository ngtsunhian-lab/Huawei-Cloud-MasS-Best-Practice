#!/usr/bin/env python3
import json
import os
import sys
from typing import Any

try:
    from openai import OpenAI
except ImportError:
    print("Missing dependency: openai. Install LiteLLM proxy or run `python3 -m pip install openai`.", file=sys.stderr)
    raise SystemExit(2)


BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:8787/v1")
API_KEY = os.environ.get("LITELLM_MASTER_KEY") or os.environ.get("MAAS_API_KEY") or "sk-local-test"
MODEL = os.environ.get("MAAS_CODEX_MODEL", "glm-5.1")


def summarize(value: Any) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return text[:160] if text else "<empty>"


def main() -> int:
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    print(f"base_url={BASE_URL}")
    print(f"model={MODEL}")

    print("checking chat.completions...")
    chat = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Reply with exactly: ok"}],
        temperature=0,
        max_tokens=16,
    )
    print("chat:", summarize(chat.choices[0].message.content))

    print("checking responses...")
    response = client.responses.create(
        model=MODEL,
        input="Reply with exactly: ok",
        temperature=0,
        max_output_tokens=16,
    )
    print("responses:", summarize(getattr(response, "output_text", "")))

    print("checking streaming responses...")
    pieces: list[str] = []
    with client.responses.stream(
        model=MODEL,
        input="Reply with exactly: ok",
        temperature=0,
        max_output_tokens=16,
    ) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                pieces.append(event.delta)
        final = stream.get_final_response()

    print("responses.stream:", summarize("".join(pieces) or getattr(final, "output_text", "")))
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
