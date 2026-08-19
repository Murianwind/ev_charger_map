#!/usr/bin/env python3
"""gov_charger_api.DAY_ZCODE_GROUPS를 기준으로 update-chargers.yml의
region_day 드롭다운 옵션 목록을 다시 생성한다.

GitHub Actions는 워크플로를 "실행하기 전에" 이미 YAML을 정적으로 파싱해서
드롭다운을 그리기 때문에, 실행 시점에 Python 코드로 옵션을 동적으로 만들
방법은 없다. 대신 "DAY_ZCODE_GROUPS나 ZCODE_NAMES를 바꾼 뒤 이 스크립트를
한 번 돌리면 워크플로 파일도 같이 최신 상태로 맞춰지는" 방식으로 둘이
어긋나지 않게 한다.

사용법:
  python scripts/sync_region_day_options.py            # 파일에 바로 반영
  python scripts/sync_region_day_options.py --check     # 반영은 안 하고 어긋나는지만
                                                          # 확인 (어긋나면 종료코드 1 —
                                                          # CI 체크로 쓰기 좋음)
"""
import sys
from pathlib import Path

from gov_charger_api import DAY_ZCODE_GROUPS, ZCODE_NAMES

WEEKDAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]
WORKFLOW_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "update-chargers.yml"

OPTIONS_START_MARKER = "        options:\n"
INDENT = "          - "


def build_options_block():
    lines = [OPTIONS_START_MARKER, f'{INDENT}"오늘"\n']
    for label, group in zip(WEEKDAY_LABELS, DAY_ZCODE_GROUPS):
        names = "·".join(ZCODE_NAMES.get(z, z) for z in group)
        lines.append(f'{INDENT}"{label}({names})"\n')
    return "".join(lines)


def find_options_block(content):
    """options: 줄부터, 그 다음에 나오는 "- "로 시작 안 하는 줄 직전까지를
    기존 옵션 블록으로 본다."""
    start = content.find(OPTIONS_START_MARKER)
    if start == -1:
        raise RuntimeError("워크플로 파일에서 'options:' 줄을 못 찾았습니다.")
    after = content[start + len(OPTIONS_START_MARKER):]
    lines = after.splitlines(keepends=True)
    block_lines = []
    for line in lines:
        if line.strip().startswith("- "):
            block_lines.append(line)
        else:
            break
    return start, OPTIONS_START_MARKER + "".join(block_lines)


def main():
    check_only = "--check" in sys.argv

    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    _, old_block = find_options_block(content)
    new_block = build_options_block()

    if old_block == new_block:
        print("이미 최신 상태입니다 — 변경 없음.")
        return

    if check_only:
        print("어긋남 발견! DAY_ZCODE_GROUPS/ZCODE_NAMES가 바뀌었는데")
        print("워크플로 파일은 아직 예전 상태입니다.")
        print("scripts/sync_region_day_options.py 를 (--check 없이) 실행해서 반영해주세요.")
        sys.exit(1)

    new_content = content.replace(old_block, new_block, 1)
    WORKFLOW_PATH.write_text(new_content, encoding="utf-8")
    print(f"반영 완료: {WORKFLOW_PATH}")
    print(new_block)


if __name__ == "__main__":
    main()
