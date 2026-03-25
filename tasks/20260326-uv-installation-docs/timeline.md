# Timeline

## 2026-03-26

- プロジェクト調査: README.md, README.ja.md, pyproject.toml を確認
- 現状: `pip install -e ".[dev]"` のみの記載。uv ユーザーへの導線がない
- pyproject.toml は setuptools ベースで uv 互換。変更不要
- ブランチ `docs/uv-installation-guide` を作成
- TODO.md を作成し、タスクを整理
- README.md を更新: Requirements に uv 追加、Install に uv セクション追加、Development に uv 手順追加、cron セクションに uv run 手順追加、launchd の ProgramArguments を ae-miner エントリーポイントに修正
- README.ja.md を同様に更新
