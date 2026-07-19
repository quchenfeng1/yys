"""
运行报告生成器（12-日志与监控模块 子模块）

生成每日/每周运行报告（Markdown 格式）。
"""

from datetime import datetime, date, timedelta


class ReportGenerator:
    """运行报告生成器。"""

    def __init__(self, config, metrics_collector):
        self._config = config
        self._metrics = metrics_collector

    def generate_daily(self, report_date=None) -> str:
        """生成每日运行报告。"""
        if report_date is None:
            report_date = date.today()
        metrics = self._metrics.get_all()

        lines = [
            f"# 运行日报 — {report_date.isoformat()}",
            "",
            "## 任务执行统计",
            "",
            "| 任务 | 执行次数 | 成功 | 失败 | 成功率 | 平均耗时 |",
            "|------|----------|------|------|--------|----------|",
        ]

        for name, m in metrics.items():
            lines.append(
                f"| {name} | {m['total_runs']} | {m['success_runs']} | "
                f"{m['fail_runs']} | {m['success_rate']}% | {m['avg_duration']}s |"
            )

        total_runs = sum(m["total_runs"] for m in metrics.values())
        total_success = sum(m["success_runs"] for m in metrics.values())
        lines.append("")
        lines.append(f"- **总执行次数**: {total_runs}")
        lines.append(f"- **总成功**: {total_success}")
        lines.append(f"- **总体成功率**: {round(total_success/total_runs*100,1) if total_runs > 0 else 0}%")
        lines.append("")
        lines.append(f"> 报告生成时间: {datetime.now().isoformat()}")

        return "\n".join(lines)

    def generate_weekly(self, week_end=None) -> str:
        """生成每周运行报告。"""
        if week_end is None:
            week_end = date.today()
        week_start = week_end - timedelta(days=7)

        lines = [
            f"# 运行周报 — {week_start.isoformat()} ~ {week_end.isoformat()}",
            "",
            "（周报功能开发中，当前展示每日指标概要）",
            "",
        ]
        lines.append(self.generate_daily(week_end))
        return "\n".join(lines)
