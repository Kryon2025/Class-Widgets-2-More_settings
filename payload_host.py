"""功能 payload 的宿主接口。

payload 不是插件 —— 它没有 CW2Plugin 的生命周期，只能通过这个宿主对象
拿到「主程序目录 / 自身目录 / 主程序能力 / 补丁工具」。

两条硬约束：

1. payload 要改主程序文件，必须走这里的 write_host / replace_host_qml / apply_ops。
   它们用与内置补丁**同一个备份命名空间**（<主程序根>/.cwplugin_backups/more_settings），
   于是补丁幂等、卸载时由 integrations.restore_all() 统一还原，两边不会互相打架。

2. 所有路径都做越界检查：payload 只能写自己目录内和主程序目录内的文件。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from loguru import logger

_BACKUP_ROOT = ".cwplugin_backups"
_BACKUP_SUB = "more_settings"

# 主程序里允许改的文件，按名字引用。
# 值是对 integrations.py 里常量的**属性名**，这样目标路径只有一份定义，不会写歪。
_HOST_FILES = {
    "container": "_CONTAINER_REL",
    "wloader": "_WLOADER_REL",
    "dialog": "_DIALOG_REL",
    "countdown": "_COUNTDOWN_REL",
    "time": "_TIME_REL",
}


def host_file(name: str) -> Path:
    """主程序内目标文件的相对路径（单一真相在 integrations.py）。"""
    import integrations

    attr = _HOST_FILES.get(str(name))
    if not attr:
        raise KeyError(f"未知的主程序文件: {name}（可选: {list(_HOST_FILES)}）")
    return getattr(integrations, attr)


class PayloadHost:
    """传给 payload 的 on_load / on_unload。"""

    def __init__(self, plugin, feature_id: str, feature_dir):
        self.plugin = plugin
        self.feature_id = str(feature_id)
        self.dir = Path(feature_dir).resolve()
        self.meta = self._read_meta()
        self.app_root = self._detect_root()
        # 事务快照；begin() 之后所有对主程序的写入都可整体回滚
        self._tx = None

    # ── 元数据与定位 ─────────────────────────────────────────
    def _read_meta(self) -> dict:
        p = self.dir / "payload.json"
        if not p.is_file():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("[payload:{}] payload.json 解析失败: {}", self.feature_id, e)
            return {}

    def _detect_root(self):
        try:
            from integrations import find_app_root

            r = find_app_root()
            return Path(r) if r else None
        except Exception:
            return None

    @property
    def version(self) -> str:
        return str(self.meta.get("version") or "")

    # ── payload 自己的文件 ───────────────────────────────────
    def own(self, rel: str) -> Path:
        """payload 自己目录内的文件；越界即报错。"""
        p = (self.dir / rel).resolve()
        if p != self.dir and self.dir not in p.parents:
            raise ValueError(f"payload 内路径越界: {rel}")
        return p

    def read_own(self, rel: str, encoding: str = "utf-8") -> str:
        return self.own(rel).read_text(encoding=encoding)

    def read_own_bytes(self, rel: str) -> bytes:
        return self.own(rel).read_bytes()

    def import_own(self, rel: str):
        """把 payload 里的 .py 当模块导入，别名带功能 id，避免与插件自身撞名。"""
        p = self.own(rel)
        if not p.is_file():
            raise FileNotFoundError(f"payload 缺少模块: {rel}")
        alias = f"cw_payload_{self.feature_id.replace('.', '_').replace('-', '_')}_{p.stem}"
        spec = importlib.util.spec_from_file_location(alias, p)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载 payload 模块: {rel}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    # ── 日志 ────────────────────────────────────────────────
    def log(self, msg: str):
        logger.info("[payload:{}] {}", self.feature_id, msg)

    def warn(self, msg: str):
        logger.warning("[payload:{}] {}", self.feature_id, msg)

    # ── 主程序文件读写（共享备份，幂等）──────────────────────
    def host_path(self, name: str) -> Path:
        if self.app_root is None:
            raise RuntimeError("未找到主程序目录")
        rel = host_file(name)
        p = (self.app_root / rel).resolve()
        root = self.app_root.resolve()
        if p != root and root not in p.parents:
            raise ValueError(f"主程序路径越界: {rel}")
        return p

    def _backup_dir(self) -> Path:
        d = self.app_root / _BACKUP_ROOT / _BACKUP_SUB
        d.mkdir(parents=True, exist_ok=True)
        return d

    def read_host(self, name: str):
        """读主程序文件，返回 (文本, 是否 CRLF)。"""
        from integrations import _read

        return _read(self.host_path(name))

    def write_host(self, name: str, text: str, crlf: bool = False):
        """写回主程序文件；首次写之前先备份官方原版（与内置补丁共用同一份备份）。"""
        from integrations import _write

        p = self.host_path(name)
        b = self._backup_dir() / f"{p.name}.orig"
        self._tx_remember(p, "files")
        self._tx_remember(b, "backups")
        if not b.is_file() and p.is_file():
            b.write_bytes(p.read_bytes())
        _write(p, text, crlf)

    def install_host_file(self, name: str, content: bytes, tag: str) -> bool:
        """把 payload 自带的资源装进主程序（如堆叠的成员选择窗口）。

        官方原本**没有**这个文件时必须留一个 _NO_DIALOG_MARK 标记 ——
        否则卸载时 restore_all 无从判断「该删掉」还是「该还原」，
        会把注入进去的文件当成官方文件留在主程序里。
        """
        from integrations import _NO_DIALOG_MARK

        p = self.host_path(name)
        b = self._backup_dir()
        orig = b / f"{p.name}.orig"
        self._tx_remember(p, "files")
        self._tx_remember(orig, "backups")
        self._tx_remember(b / _NO_DIALOG_MARK, "backups")
        if p.is_file():
            if not orig.is_file():
                orig.write_bytes(p.read_bytes())
        else:
            (b / _NO_DIALOG_MARK).write_text(
                f"official ClassWidgets has no {p.name}\n", encoding="utf-8")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        self.log(f"{tag}: 已装入 {p.name}")
        return True

    # ── 事务：跨文件原子注入 ─────────────────────────────────
    def begin(self):
        """开始事务：之后对主程序文件（含备份）的写入都可整体回滚。

        存在的理由：一个功能往往要同时改好几个文件，而且文件之间互相引用
        （容器补丁注入的 `AddOverlayMemberDialog` 必须真的有这个组件）。
        只写成功一半，主程序重启时会因找不到组件而加载失败。
        """
        self._tx = {"files": {}, "backups": {}}
        return self

    def _tx_remember(self, p: Path, store: str):
        if self._tx is None:
            return
        d = self._tx[store]
        key = str(p)
        if key not in d:
            try:
                d[key] = p.read_bytes() if p.is_file() else None
            except OSError as e:
                self.warn(f"记录回滚快照失败 {p.name}: {e}")

    def rollback(self) -> int:
        """把改动过的文件和备份都恢复成事务开始前的样子。返回恢复的文件数。"""
        tx = self._tx
        self._tx = None
        if not tx:
            return 0
        n = 0
        for store in ("files", "backups"):
            for key, blob in tx[store].items():
                p = Path(key)
                try:
                    if blob is None:
                        if p.is_file():
                            p.unlink()
                            n += 1
                    else:
                        if not p.is_file() or p.read_bytes() != blob:
                            p.parent.mkdir(parents=True, exist_ok=True)
                            p.write_bytes(blob)
                            n += 1
                except OSError as e:
                    self.warn(f"回滚 {p.name} 失败: {e}")
        return n

    def _check_component_refs(self, text: str):
        """补丁引用了某个组件，就必须保证这个组件的文件真的在主程序里。

        这正是「半注入让主程序重启后崩掉」的典型形态：容器补丁落盘了，
        但它引用的对话框没装上。
        """
        if "AddOverlayMemberDialog" in text:
            if not self.host_path("dialog").is_file():
                raise RuntimeError("补丁引用了 AddOverlayMemberDialog，但该组件不在主程序里")

    def commit(self) -> bool:
        """自检这个功能改过的每个 QML；只要有一个不自洽就整体回滚。"""
        tx = self._tx
        if not tx:
            return True
        from integrations import _assert_qml_consistent, _read

        bad = []
        for key in tx["files"]:
            p = Path(key)
            if not p.is_file() or p.suffix != ".qml":
                continue
            try:
                text, _ = _read(p)
                _assert_qml_consistent(text, p.name)
                self._check_component_refs(text)
            except Exception as e:
                bad.append(f"{p.name}: {e}")
        if bad:
            self.rollback()
            self.warn("补丁自检没通过，已整体回滚 —— " + "；".join(bad))
            return False
        self._tx = None
        return True

    def replace_host_qml(self, name: str, patch_text: str, tag: str) -> bool:
        """整体替换主程序内的一个 QML（内容相同则跳过）。返回是否真的写了。"""
        from integrations import _assert_qml_consistent, _read

        p = self.host_path(name)
        if not p.is_file():
            self.warn(f"{tag}: 目标文件不存在，跳过")
            return False
        text, crlf = _read(p)
        if text.strip() == patch_text.strip():
            return False
        # 先自检补丁本身完整（花括号配平、引用成套），坏文件绝不写进主程序
        _assert_qml_consistent(patch_text, f"{tag} payload 补丁")
        self.write_host(name, patch_text, crlf)
        return True

    def apply_ops(self, name: str, ops, tag: str, atomic: bool = False) -> bool:
        """按锚点做替换式补丁。

        atomic=True 时任一关键锚点缺失就整组放弃 —— 用于「引用与定义必须成套」
        的补丁（如 overlay 入口），避免部分注入让主程序 QML 加载失败。
        """
        from integrations import _apply, _apply_group, _assert_qml_consistent, _read

        p = self.host_path(name)
        if not p.is_file():
            self.warn(f"{tag}: 目标文件不存在，跳过")
            return False
        text, crlf = _read(p)
        before = text
        text = _apply_group(text, ops, tag, logger) if atomic else _apply(text, ops, tag, logger)
        if text == before:
            return False
        _assert_qml_consistent(text, tag)
        self.write_host(name, text, crlf)
        return True

    def ops(self, group: str):
        """取 integrations.py 里预置的补丁锚点组（同一份真相，不复制到 payload）。"""
        from integrations import PUBLIC_GROUPS

        try:
            return PUBLIC_GROUPS[str(group)]
        except KeyError:
            raise KeyError(f"未知的补丁组: {group}（可选: {list(PUBLIC_GROUPS)}）") from None

    # ── 主程序能力（转发给插件 API）──────────────────────────
    def register_widget(self, widget_id, name, qml_path, backend_obj=None,
                        settings_qml=None, default_settings=None):
        """注册一个组件，qml 用 payload 自带的资源。"""
        kw = {}
        if settings_qml:
            kw["settings_qml"] = str(self.own(settings_qml))
        if default_settings is not None:
            kw["default_settings"] = default_settings
        return self.plugin.api.widgets.register(
            widget_id=widget_id,
            name=name,
            qml_path=str(self.own(qml_path)),
            backend_obj=backend_obj,
            **kw,
        )

    def register_settings_page(self, qml_path, title, icon=""):
        return self.plugin.api.ui.register_settings_page(
            qml_path=str(self.own(qml_path)), title=title, icon=icon,
        )

    def read_config(self, key, default=None):
        """读插件自身的配置（payload 与插件共享同一份配置模型）。"""
        cfg = getattr(self.plugin, "_config", None)
        return getattr(cfg, key, default) if cfg is not None else default


def load_payload(plugin, feature_id: str, feature_dir):
    """加载一个 payload，返回 (host, module)。入口默认 feature.py。"""
    d = Path(feature_dir).resolve()
    host = PayloadHost(plugin, feature_id, d)
    entry = str(host.meta.get("entry") or "feature.py")
    # 临时把自己目录放进 sys.path，容忍 payload 内部 import 同级模块
    sys.path.insert(0, str(d))
    try:
        mod = host.import_own(entry)
    finally:
        try:
            sys.path.remove(str(d))
        except ValueError:
            pass
    return host, mod


def activate_payload(plugin, feature_id: str, feature_dir):
    """加载并激活一个 payload —— 它的所有补丁作为一个整体成败。

    返回 (host, module, 说明)。失败时前面两项是 None，且**已经写下去的文件
    全部还原**。宁可这个功能不生效，也不能留下半个补丁让主程序重启后崩掉。
    """
    host, mod = load_payload(plugin, feature_id, feature_dir)
    host.begin()
    try:
        fn = getattr(mod, "on_load", None)
        if callable(fn):
            fn(host)
    except Exception as e:
        host.rollback()
        return None, None, f"注入异常，已整体回滚：{e}"
    # 落盘自检通过还不够：功能要求的补丁必须**真的都到位**。
    # 注意 payload 内部会吞掉异常只返回 False（它要尽量不中断加载流程），
    # 所以这里不能靠「有没有抛异常」判断成功，必须按声明核对。
    # 少任何一项都整体回滚 —— 半个补丁会让主程序重启后加载失败。
    try:
        from integrations import patch_status
        st = patch_status(host.app_root, feature_id) if host.app_root else []
        missing = [x["file"] for x in st if not x["applied"]]
    except Exception as e:
        missing = []
        host.warn(f"补丁落地自检异常: {e}")
    if missing:
        n = host.rollback()
        return None, None, ("补丁未全部落地（" + "、".join(missing)
                            + f"），已回滚 {n} 个文件")
    if not host.commit():
        return None, None, "补丁自检未通过，已整体回滚"
    return host, mod, "已激活"
