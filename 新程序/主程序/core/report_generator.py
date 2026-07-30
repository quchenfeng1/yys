"""
12-日志监控中心

运行报告生成器。
职责:
- 根据执行记录生成运行报告
- 支持 HTML / Markdown / JSON 格式
- 报告包含统计摘要、错误列表、时间线
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.metrics_collector import MetricsCollector
from core.task_state import TaskState


class ReportGenerator:
    """运行报告生成器"""

    def __init__(
        self,
        task_state: TaskState | None = None,
        metrics: MetricsCollector | None = None,
    ):
        self._task_state = task_state or TaskState()
        self._metrics = metrics or MetricsCollector()

    def generate(
        self,
        title: str = "运行报告",
        format: str = "markdown",  # markdown | html | json
        output_path: str | None = None,
    ) -> str:
        """生成运行报告"""
        if format == "json":
            content = self._generate_json()
        elif format == "html":
            content = self._generate_html(title)
        else:
            content = self._generate_markdown(title)

        if output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

        return content

    def _generate_markdown(self, title: str) -> str:
        """生成 Markdown 格式报告"""
        lines = [f"# {title}", "", f"**生成时间**: {datetime.now().isoformat()}", ""]

        # 统计摘要
        stats = self._task_state.get_total_stats()
        lines.append("## 统计摘要")
        lines.append("")
        lines.append(f"- 总执行次数: {stats['total']}")
        lines.append(f"- 成功: {stats['success']}")
        lines.append(f"- 失败: {stats['failed']}")
        lines.append(f"- 跳过: {stats['skipped']}")
        lines.append(f"- 成功率: {stats['success_rate']:.1%}")
        lines.append("")

        # 指标
        summary = self._metrics.get_summary()
        lines.append("## 性能指标")
        lines.append("")
        lines.append(f"- 运行时长: {summary['uptime']:.0f}秒")
        lines.append(f"- 操作总数: {summary['total_actions']}")
        lines.append(f"- 平均耗时: {summary['avg_duration']:.2f}秒")
        lines.append(f"- 操作频率: {summary['action_rate']:.1f}次/分钟")
        lines.append("")

        return "\n".join(lines)

    def _generate_html(self, title: str) -> str:
        """生成 HTML 格式报告"""
        md = self._generate_markdown(title)
        # 简单的 Markdown -> HTML 转换
        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{title}</title></head>
<body>
<pre>{md}</pre>
</body>
</html>"""
        return html

    def _generate_json(self) -> str:
        """生成 JSON 格式报告"""
        stats = self._task_state.get_total_stats()
        summary = self._metrics.get_summary()

        data = {
            "generated_at": datetime.now().isoformat(),
            "statistics": stats,
            "metrics": summary,
            "recent_history": [
                {
                    "task_id": r.task_id,
                    "status": r.status,
                    "duration": r.duration,
                    "error": r.error,
                }
                for r in self._task_state.get_history(limit=20)
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)

    def generate_daily_report(self, output_dir: str | Path = "logs/reports") -> str:
        """生成日报"""
        today = datetime.now().strftime("%Y-%m-%d")
        path = Path(output_dir) / f"report_{today}.md"
        return self.generate(
            title=f"运行日报 {today}",
            format="markdown",
            output_path=str(path),
        )
