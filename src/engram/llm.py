"""共有LLMユーティリティ: CLI LLMバックエンドのファクトリと出力パーサー."""

from __future__ import annotations

import os
import subprocess


LLM_CHOICES = ["claude-code", "codex", "gemini"]


def extract_json_array(text: str) -> str:
    """LLMレスポンスからJSON配列部分を抽出する。

    CLIツールの出力にはmarkdownフェンスや説明文が含まれることがあるため、
    最初の [...] ブロックを探して返す。見つからなければ元テキストをそのまま返す。
    """
    start = text.find("[")
    if start == -1:
        return text
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text


def make_cli_llm(cli_name: str, model: str = None):
    """CLI名に応じた llm_fn を返すファクトリ。"""

    cmd = {
        "claude-code": ["claude", "-p", "--output-format", "text", "--no-session-persistence"],
        "codex": ["codex", "exec", "--ephemeral"],
        "gemini": ["gemini"],
    }[cli_name]

    # --model 指定があれば追加
    if model:
        if cli_name == "claude-code":
            cmd = cmd + ["--model", model]
        elif cli_name == "codex":
            cmd = cmd + ["-c", f"model={model}"]

    config = {"cmd": cmd}

    def llm_fn(messages: list) -> str:
        prompt = messages[0]["content"] + "\n\n" + messages[1]["content"]

        env = dict(os.environ)
        # Claude Code はネスト起動を禁止するため、環境変数を除去して回避
        if cli_name == "claude-code":
            env.pop("CLAUDECODE", None)

        result = subprocess.run(
            config["cmd"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"{cli_name} exited with code {result.returncode}: "
                f"{result.stderr[:500]}"
            )
        return extract_json_array(result.stdout)

    return llm_fn
