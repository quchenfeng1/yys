"""
06-配置管理中心

ConfigManager 主入口（数据中心模式）。
对应设计书 §5.1/§5.2/§5.3/§5.4。

职责:
- 统一加载/管理/持久化所有 YAML/JSON 配置
- 点分路径读写接口（含三级分层覆盖）
- 原子持久化（先写盘 → 后更新缓存）
- 热重载（watchdog polling）
- 配置版本迁移
- 配置校验（validate() 返回错误列表）
- 导入导出（zip 备份/恢复）
- 配置变更审计

设计原则：
- 纯数据，不判断
- 单一数据源
- 写盘优先：先写盘、后更新缓存，写盘失败时缓存不变
- 线程安全：_lock 保护 _cache/_index_cache/_paths
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Any, Optional

import yaml

from core.config_schema import (
    AccountsConfig,
    GlobalConfig,
    MIGRATIONS,
    TasksConfig,
    validate_accounts_config,
    validate_global_config,
    validate_tasks_config,
)
from core.event_bus import EventBus, get_global_bus
from core.events import Events
from core.exceptions import ConfigError, ConfigNotFoundError, ConfigValidationError


# ── 版本迁移常量 ───────────────────────────────────────────
CURRENT_VERSION: int = 1


def _yaml_load(path: Path) -> dict[str, Any]:
    """加载 YAML 文件"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _yaml_dump(path: Path, data: dict[str, Any]) -> None:
    """写入 YAML 文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


class ConfigManager:
    """配置管理器（数据中心模式，§5.2 方法定义）"""

    def __init__(
        self,
        config_dir: str | Path = "config",
        event_bus: EventBus | None = None,
        enable_hot_reload: bool = True,
        monitor: Any = None,
    ):
        self._config_dir = Path(config_dir)
        self._bus = event_bus or get_global_bus()
        self._monitor = monitor  # §2.1 日志监控中心（可选）
        self._lock = threading.Lock()
        self._hot_reload_enabled = enable_hot_reload
        self._watcher: Any = None          # watchdog PollingObserver

        # §2.3 _paths：各配置文件在磁盘上的路径映射
        self._paths: dict[str, str] = {
            "global": str(self._config_dir / "global.yaml"),
            "tasks": str(self._config_dir / "tasks.yaml"),
            "accounts": str(self._config_dir / "accounts.yaml"),
            "coords": str(self._config_dir / "coords"),
        }

        # §2.3 _cache：内存中的完整配置数据副本（嵌套 dict）
        self._raw_global: dict[str, Any] = {}
        self._raw_accounts: dict[str, Any] = {}
        self._raw_tasks: dict[str, Any] = {}
        self._coords_cache: dict[str, dict[str, Any]] = {}

        # 类型化配置对象
        self._global: GlobalConfig | None = None
        self._accounts: AccountsConfig | None = None
        self._tasks: TasksConfig | None = None

        # §2.3 点分路径索引缓存（含账号 ID，惰性填充）
        self._index_cache: dict[str, Any] = {}

        # §2.2 配置版本号（对外暴露）
        self._version: int = 0
        self._current_account: str = ""  # 当前账号 ID，用于索引缓存键

    # ═══════════════════════════════════════════════════════════
    #  属性（§2.2）
    # ═══════════════════════════════════════════════════════════

    @property
    def config_version(self) -> int:
        """当前配置版本号（§2.2）"""
        return self._version

    @property
    def config_dir(self) -> Path:
        return self._config_dir

    @property
    def global_config(self) -> GlobalConfig:
        if self._global is None:
            raise ConfigError("Global config not loaded")
        return self._global

    @property
    def accounts_config(self) -> AccountsConfig:
        if self._accounts is None:
            raise ConfigError("Accounts config not loaded")
        return self._accounts

    @property
    def tasks_config(self) -> TasksConfig:
        if self._tasks is None:
            raise ConfigError("Tasks config not loaded")
        return self._tasks

    @property
    def raw_global(self) -> dict[str, Any]:
        return self._raw_global

    # ═══════════════════════════════════════════════════════════
    #  加载（§5.3 load + §4.4 版本迁移）
    # ═══════════════════════════════════════════════════════════

    def load(self) -> None:
        """
        按固定顺序加载所有配置文件（§5.3）。

        流程：
        ① global.yaml → ② tasks.yaml → ③ accounts.yaml
        ④ 检查版本号，执行自动迁移
        ⑤ validate() 校验合法性（不阻断）
        ⑥ 重建 _index_cache
        ⑦ 启动 _watcher 热重载线程
        """
        with self._lock:
            self._load_global_internal()
            self._load_tasks_internal()
            self._load_accounts_internal()

            # §4.4 版本迁移
            self._run_migrations()

            # 校验（不阻断）
            errors = self._validate_internal()
            if errors and self._monitor:
                self._monitor.log("config", f"配置校验告警: {'; '.join(errors)}")

            # 重建索引
            self._rebuild_index()

        self._start_watcher()

    def _load_global_internal(self) -> None:
        path = self._config_dir / "global.yaml"
        if not path.exists():
            raise ConfigNotFoundError(f"全局配置文件不存在: {path}")
        raw = _yaml_load(path)
        try:
            validated = validate_global_config(raw)
        except Exception as e:
            raise ConfigValidationError(f"global.yaml 校验异常: {e}") from e
        self._raw_global = raw
        self._global = validated

    def _load_tasks_internal(self) -> None:
        path = self._config_dir / "tasks.yaml"
        if not path.exists():
            raise ConfigNotFoundError(f"任务配置文件不存在: {path}")
        raw = _yaml_load(path)
        try:
            validated = validate_tasks_config(raw)
        except Exception as e:
            raise ConfigValidationError(f"tasks.yaml 校验异常: {e}") from e
        self._raw_tasks = raw
        self._tasks = validated

    def _load_accounts_internal(self) -> None:
        path = self._config_dir / "accounts.yaml"
        if not path.exists():
            raise ConfigNotFoundError(f"账号配置文件不存在: {path}")
        raw = _yaml_load(path)
        try:
            validated = validate_accounts_config(raw)
        except Exception as e:
            raise ConfigValidationError(f"accounts.yaml 校验异常: {e}") from e
        self._raw_accounts = raw
        self._accounts = validated

    # ── 逐文件加载（兼容旧调用的公开方法）─────────────────────

    def load_global(self) -> GlobalConfig:
        with self._lock:
            self._load_global_internal()
        return self._global

    def load_tasks(self) -> TasksConfig:
        with self._lock:
            self._load_tasks_internal()
        return self._tasks

    def load_accounts(self) -> AccountsConfig:
        with self._lock:
            self._load_accounts_internal()
        return self._accounts

    def load_coords(self, name: str) -> dict[str, Any]:
        """加载坐标文件 config/coords/{name}.json"""
        path = self._config_dir / "coords" / f"{name}.json"
        if not path.exists():
            raise ConfigNotFoundError(f"坐标文件不存在: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._coords_cache[name] = data
        return data

    # ── 版本迁移（§4.4）────────────────────────────────────

    def _run_migrations(self) -> None:
        """检查版本号并执行增量迁移"""
        file_version = self._raw_global.get("_version", 0)
        if file_version >= CURRENT_VERSION:
            self._version = file_version
            return

        # 按顺序执行 v_n → v_{n+1}
        for v in range(file_version, CURRENT_VERSION):
            migrate_fn = MIGRATIONS.get(v)
            if migrate_fn:
                # 迁移函数接收 (_raw_global, _raw_tasks, _raw_accounts) 并返回更新后的 dict
                result = migrate_fn(self._raw_global, self._raw_tasks, self._raw_accounts)
                if result:
                    self._raw_global, self._raw_tasks, self._raw_accounts = result

        # 更新版本号
        self._raw_global["_version"] = CURRENT_VERSION
        self._version = CURRENT_VERSION

        # 保存迁移后的配置
        for section, raw in [("global", self._raw_global),
                              ("tasks", self._raw_tasks),
                              ("accounts", self._raw_accounts)]:
            self._atomic_save(section, raw)

        if self._monitor:
            self._monitor.log("config",
                              f"配置版本迁移: v{file_version} → v{CURRENT_VERSION}")

    # ── 保存（§5.3 set 内部调用）────────────────────────────

    def save_global(self, data: dict[str, Any] | None = None) -> None:
        path = self._config_dir / "global.yaml"
        _yaml_dump(path, data or self._raw_global)
        self._bus.publish(Events.CONFIG_CHANGED, source="global")

    def save_accounts(self, data: dict[str, Any] | None = None) -> None:
        path = self._config_dir / "accounts.yaml"
        _yaml_dump(path, data or self._raw_accounts)
        self._bus.publish(Events.CONFIG_CHANGED, source="accounts")

    def save_tasks(self, data: dict[str, Any] | None = None) -> None:
        path = self._config_dir / "tasks.yaml"
        _yaml_dump(path, data or self._raw_tasks)
        self._bus.publish(Events.CONFIG_CHANGED, source="tasks")

    # ═══════════════════════════════════════════════════════════
    #  校验（§4 + §5.3 validate）
    # ═══════════════════════════════════════════════════════════

    def validate(self) -> list[str]:
        """
        校验所有配置（§5.3 validate）。

        Returns:
            错误描述列表（空列表表示全部通过）
        """
        with self._lock:
            return self._validate_internal()

    def _validate_internal(self) -> list[str]:
        """内部校验（已持锁）"""
        errors: list[str] = []

        # 校验 global
        if self._raw_global:
            try:
                validate_global_config(self._raw_global)
            except ConfigValidationError as e:
                errors.append(f"global.yaml: {e}")
            except Exception as e:
                errors.append(f"global.yaml 异常: {e}")

        # 校验 accounts
        if self._raw_accounts:
            try:
                validate_accounts_config(self._raw_accounts)
            except ConfigValidationError as e:
                errors.append(f"accounts.yaml: {e}")
            except Exception as e:
                errors.append(f"accounts.yaml 异常: {e}")

        # 校验 tasks
        if self._raw_tasks:
            try:
                validate_tasks_config(self._raw_tasks)
            except ConfigValidationError as e:
                errors.append(f"tasks.yaml: {e}")
            except Exception as e:
                errors.append(f"tasks.yaml 异常: {e}")

        return errors

    # ═══════════════════════════════════════════════════════════
    #  热重载（§4.3）
    # ═══════════════════════════════════════════════════════════

    def reload(self) -> None:
        """
        手动热重载所有配置（§5.3 reload）。

        获取 _lock → 重读所有文件 → 重建 _cache → 清空 _index_cache
        → validate() → 发布 config_changed → 释放锁
        """
        with self._lock:
            self._load_global_internal()
            self._load_tasks_internal()
            self._load_accounts_internal()
            self._rebuild_index()
            errors = self._validate_internal()
            if errors and self._monitor:
                self._monitor.log("config", f"热重载校验告警: {'; '.join(errors)}")

        self._bus.publish(Events.CONFIG_RELOADED)

    # 兼容旧名
    reload_all = reload

    def _start_watcher(self) -> None:
        """启动 watchdog 文件监控（§4.3），优先 PollingObserver，降级 Observer"""
        if not self._hot_reload_enabled:
            return
        try:
            from watchdog.events import FileSystemEventHandler

            # 优先使用 PollingObserver（跨平台轮询，每 3s 检查 mtime）
            try:
                from watchdog.observers.polling import PollingObserver as _ObserverCls
            except ImportError:
                from watchdog.observers import Observer as _ObserverCls

            class _ConfigHandler(FileSystemEventHandler):
                def __init__(self, mgr: ConfigManager):
                    self.mgr = mgr

                def on_modified(self, event):
                    if not event.is_directory and event.src_path.endswith(".yaml"):
                        self.mgr._bus.publish(Events.CONFIG_HOT_RELOAD, path=event.src_path)
                        try:
                            self.mgr.reload()
                        except Exception:
                            self.mgr._bus.publish(
                                Events.CONFIG_ERROR,
                                error=traceback.format_exc(),
                            )

            self._watcher = _ObserverCls()
            self._watcher.schedule(
                _ConfigHandler(self),
                str(self._config_dir),
                recursive=False,
            )
            self._watcher.start()
        except ImportError:
            pass  # watchdog 未安装

    def stop_watcher(self) -> None:
        """停止热重载文件监听（§5.3 + §5.4 资源管理）"""
        if self._watcher:
            self._watcher.stop()
            self._watcher.join(timeout=3)
            self._watcher = None

    # ═══════════════════════════════════════════════════════════
    #  导入导出（§4.5）
    # ═══════════════════════════════════════════════════════════

    def export_config(self, target_path: str) -> None:
        """
        导出全套配置为 zip 备份（§5.3 + §4.5）。

        Args:
            target_path: 输出 .zip 文件路径
        """
        import shutil
        import tempfile
        import zipfile

        with self._lock:
            tmp_dir = Path(tempfile.mkdtemp(prefix="config_export_"))
            try:
                for fname in ["global.yaml", "accounts.yaml", "tasks.yaml"]:
                    src = self._config_dir / fname
                    if src.exists():
                        shutil.copy2(str(src), str(tmp_dir / fname))
                # coords 目录
                coords_dir = self._config_dir / "coords"
                if coords_dir.exists():
                    shutil.copytree(str(coords_dir), str(tmp_dir / "coords"),
                                    dirs_exist_ok=True)

                # 打包 zip
                target = Path(target_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(str(target), "w", zipfile.ZIP_DEFLATED) as zf:
                    for f in tmp_dir.rglob("*"):
                        if f.is_file():
                            arcname = str(f.relative_to(tmp_dir))
                            zf.write(str(f), arcname)
            finally:
                shutil.rmtree(str(tmp_dir), ignore_errors=True)

    def import_config(self, source_path: str, mode: str = "overwrite") -> None:
        """
        从 zip 备份恢复配置（§5.3 + §4.5）。

        Args:
            source_path: .zip 文件路径
            mode: "overwrite"（覆盖）/ "supplement"（仅补充缺失）
        """
        import shutil
        import tempfile
        import zipfile

        src = Path(source_path)
        if not src.exists():
            raise ConfigNotFoundError(f"备份文件不存在: {source_path}")
        if mode not in ("overwrite", "supplement"):
            raise ConfigValidationError(f"不支持的导入模式: {mode}, 可选: overwrite / supplement")

        tmp_dir = Path(tempfile.mkdtemp(prefix="config_import_"))
        try:
            with zipfile.ZipFile(str(src), "r") as zf:
                zf.extractall(str(tmp_dir))

            with self._lock:
                for item in tmp_dir.rglob("*"):
                    if not item.is_file():
                        continue
                    rel = item.relative_to(tmp_dir)
                    target = self._config_dir / rel
                    if mode == "supplement" and target.exists():
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(item), str(target))

            self.reload()
        finally:
            shutil.rmtree(str(tmp_dir), ignore_errors=True)

    # ═══════════════════════════════════════════════════════════
    #  点分路径读写（§5.3 get / set + §3.2/§3.3）
    # ═══════════════════════════════════════════════════════════

    def _rebuild_index(self) -> None:
        """重建点分路径索引缓存（§2.3 + §5.3）"""
        self._index_cache.clear()
        # 注册顶层段引用（惰性填充：子路径在 get() 时按需添加）
        self._index_cache["global"] = self._raw_global
        self._index_cache["accounts"] = self._raw_accounts
        self._index_cache["tasks"] = self._raw_tasks
        if self._coords_cache:
            for name, data in self._coords_cache.items():
                self._index_cache[f"coords.{name}"] = data

    def _invalidate_index_prefix(self, key_path: str) -> None:
        """
        删除 _index_cache 中所有以 key_path 开头的条目（§3.3）。

        例如 set("tasks.yuhun.priority") → 删 "tasks.yuhun.priority"
        及所有 "tasks.yuhun.*" 条目。下次 get() 重新计算。
        """
        prefix = key_path.rstrip(".")
        keys_to_delete = [k for k in self._index_cache if k == prefix or k.startswith(prefix + ".")]
        for k in keys_to_delete:
            self._index_cache.pop(k, None)

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        点分路径读取配置值（§3.2 + §5.3）。

        三级覆盖优先级：task级 > account级 > global级
        索引缓存键含当前账号 ID（如 "my_account.tasks.yuhun.priority"）。
        持锁保护 _index_cache 和 _raw_* 的一致性。
        """
        with self._lock:
            # 1. 检查索引缓存（含账号限定键）
            account_prefix = f"{self._current_account}." if self._current_account else ""
            cache_key = account_prefix + key_path
            if cache_key in self._index_cache:
                return self._index_cache[cache_key]

            parts = key_path.split(".")
            section = parts[0]

            if section == "tasks":
                # 三级覆盖查找
                value = self._three_level_get(parts[1:])
                if value is not None:
                    self._index_cache[cache_key] = value
                    return value
                return default

            elif section == "accounts":
                value = self._deep_get(self._raw_accounts, parts[1:])
                if value is not None:
                    self._index_cache[cache_key] = value
                    return value
                return default

            elif section == "global":
                value = self._deep_get(self._raw_global, parts[1:])
                if value is not None:
                    self._index_cache[cache_key] = value
                    return value
                return default

            else:
                # 非标准段 → 三级覆盖查找所有
                for candidate in [self._raw_tasks, self._raw_accounts, self._raw_global]:
                    val = self._deep_get(candidate, parts)
                    if val is not None:
                        self._index_cache[cache_key] = val
                        return val
                return default

    def _three_level_get(self, parts: list[str]) -> Any:
        """
        三级覆盖查找（§3.4）：
        ① task级: tasks.{category}.{task}.{key}
        ② account级: accounts.{current_account}.{key}
        ③ global级: global.{key}
        """
        # ① task级：从 _raw_tasks 查找
        task_val = self._deep_get(self._raw_tasks, parts)
        if task_val is not None:
            return task_val

        # ② account级
        if self._current_account and self._raw_accounts:
            acct_val = self._deep_get(self._raw_accounts, [self._current_account] + parts)
            if acct_val is not None:
                return acct_val

        # ③ global级
        global_val = self._deep_get(self._raw_global, parts)
        if global_val is not None:
            return global_val

        return None

    def set(self, key_path: str, value: Any, source: str = "UI") -> None:
        """
        设置配置值并原子持久化（§3.3 + §5.3 + §4.6 审计）。

        流程：
        持锁→按前缀定位文件→记录旧值→写临时文件→os.replace
        → 成功：更新 _cache → 失效 _index_cache 前缀 → 发布事件
        → 失败：不修改缓存 → 抛异常
        """
        with self._lock:
            parts = key_path.split(".")
            section = parts[0]

            if section == "global":
                target = self._raw_global
                save_fn = self.save_global
            elif section == "tasks":
                target = self._raw_tasks
                save_fn = self.save_tasks
            elif section == "accounts":
                target = self._raw_accounts
                save_fn = self.save_accounts
            else:
                raise ConfigError(f"无法定位配置段: {section}（设计书§3.3）")

            old_value = self._deep_get(target, parts[1:])

            # 写盘（先写盘、后更新缓存，§3.3 写盘优先原则）
            self._deep_set(target, parts[1:], value)
            try:
                self._atomic_save(section, target)
            except Exception:
                # 写盘失败 → 恢复 _cache 到旧值
                if old_value is not None:
                    self._deep_set(target, parts[1:], old_value)
                else:
                    self._deep_delete(target, parts[1:])
                raise

            # 写盘成功 → 失效索引缓存（而非直接设置，保证下次 get() 走三级覆盖）
            self._invalidate_index_prefix(key_path)

        # 持锁外发布事件
        self._bus.publish(
            Events.CONFIG_CHANGED,
            source=source,
            section=section,
            key_path=key_path,
            old_value=old_value,
            new_value=value,
            timestamp=datetime.now().isoformat(),
        )

        # §4.6 审计日志
        if self._monitor and hasattr(self._monitor, 'log'):
            self._monitor.log("config.audit", {
                "action": "set",
                "key_path": key_path,
                "old_value": old_value,
                "new_value": value,
                "source": source,
                "timestamp": datetime.now().isoformat(),
            })

    def get_section(self, section: str) -> dict[str, Any]:
        """读取整个配置段（§5.3），返回深拷贝"""
        import copy
        with self._lock:
            if section == "global":
                return copy.deepcopy(self._raw_global)
            elif section == "accounts":
                return copy.deepcopy(self._raw_accounts)
            elif section == "tasks":
                return copy.deepcopy(self._raw_tasks)
            raise ConfigError(f"未知配置段: {section}")

    def get_task_config(self, name: str) -> dict[str, Any] | None:
        """
        读取完整任务配置（§4.2 + §5.3）。

        合并策略：浅合并（第一层 key 合并）。
        tasks.yaml 和 coords/{name}.json 处于同一层级，
        同名 key 以 tasks.yaml 完整替换 coords 的同名 key。
        """
        import copy
        with self._lock:
            # 从 tasks 段中查找该任务
            tasks_section: dict = self._raw_tasks or {}
            tasks_list = tasks_section.get("tasks", []) if isinstance(tasks_section, dict) else []
            task_config = None
            for t in tasks_list:
                if isinstance(t, dict) and t.get("name") == name:
                    task_config = copy.deepcopy(t)
                    break
                if isinstance(t, dict) and t.get("id") == name:
                    task_config = copy.deepcopy(t)
                    break

            if task_config is None:
                return None

            # 浅合并 coords/{name}.json（§4.2）
            coords = self._coords_cache.get(name, {})
            if coords:
                # coords 与 task_config 同层合并，tasks.yaml 优先
                merged = {}
                merged.update(coords)       # coords 先写入
                merged.update(task_config)  # tasks 覆盖同名 key（浅合并）
                return merged

            return task_config

    def get_coords(self, scene: str) -> dict[str, Any]:
        """读取场景坐标（§5.3）"""
        with self._lock:
            # 从 _coords_cache 中查找（设计书要求从 _cache["coords"] 查找）
            for name, data in self._coords_cache.items():
                if name == scene:
                    return copy.deepcopy(data) if data else {}
                points = data.get("points", {}) if isinstance(data, dict) else {}
                if scene in points:
                    return copy.deepcopy(points[scene])
            return {}

    # ── 账号切换（§3.2 + §5.4 索引缓存）─────────────────────

    def switch_account(self, account_id: str) -> None:
        """
        切换当前账号（清空 _index_cache 防止返回旧值）。

        订阅者：通过 EventBus 的 account_switched 事件触发。
        """
        with self._lock:
            self._current_account = account_id
            self._index_cache.clear()

    # ── 工具方法 ────────────────────────────────────────────

    @staticmethod
    def _deep_get(d: dict[str, Any], parts: list[str]) -> Any:
        """递归取嵌套 dict 值"""
        current = d
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    @staticmethod
    def _deep_set(d: dict[str, Any], parts: list[str], value: Any) -> None:
        """递归设置嵌套 dict 值"""
        current = d
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    @staticmethod
    def _deep_delete(d: dict[str, Any], parts: list[str]) -> None:
        """递归删除嵌套 dict 键"""
        current = d
        for part in parts[:-1]:
            if not isinstance(current, dict):
                return
            current = current.get(part, {})
        if isinstance(current, dict) and parts:
            current.pop(parts[-1], None)

    def _atomic_save(self, section: str, data: dict[str, Any]) -> None:
        """原子写入（§3.3 + §4.3：临时文件 + os.replace）"""
        import tempfile

        fname = f"{section}.yaml"
        path = self._config_dir / fname
        path.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            suffix=".yaml",
            prefix=f".{fname}.",
            dir=str(self._config_dir),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise

    # ═══════════════════════════════════════════════════════════
    #  生命周期
    # ═══════════════════════════════════════════════════════════

    def close(self) -> None:
        """清理资源（§5.3 + §5.4）"""
        self.stop_watcher()
