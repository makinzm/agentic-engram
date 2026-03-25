# uv Installation Documentation

## Goal
pip がなくても uv だけで agentic-engram をインストール・利用できるようにドキュメントを整備する。

## Tasks
- [ ] README.md: Quick Start の Install セクションに uv の手順を追加
- [ ] README.md: Development セクションに uv の手順を追加
- [ ] README.md: cron/scheduling セクションの .venv パスを uv に合わせた記述を追加
- [ ] README.ja.md: 同様の変更を日本語版にも反映
- [ ] pyproject.toml が uv 互換であることを確認（setuptools ベースなので問題ないはず）

## Notes
- 既存の pip 手順は残し、uv を併記する形にする
- uv は `uv pip install` と `uv venv` + `uv sync` の両方のワークフローに対応
