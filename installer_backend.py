"""扩展设置的安装器后端：从清单拉取 / 手动导入功能 payload。

职责边界（重要）：
    只做「拉清单 → 匹配版本 → 下载 / 读本地文件 → sha256 校验 →
    解压落盘 → 记录状态」。
    **不做注入**。注入由被安装的功能自己在 on_load 时执行（见 payload_host.py）。

落盘位置：
    功能以 payload（普通压缩包，**不含 cwplugin.json**）的形式分发，解压到
    本插件自己的数据目录：
        <主程序根>/configs/plugins/com.kryon.more_settings/features/<功能 id>/
    主程序的插件扫描只认带 cwplugin.json 的目录，所以这些内容不会出现在
    插件列表里 —— 这是「不显示」的实现机制，不是靠藏。

安全：
    - 网络来源一律要求 https，且限制响应大小；
    - 每个包都要过 zip-slip 检查（拒绝绝对路径、`..`、盘符）与解压体积上限；
    - sha256 不匹配一律丢弃；
    - 功能 id 做白名单过滤后才会拼进路径，杜绝路径穿越。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import threading
import urllib.request
import zipfile
from pathlib import Path

# 本插件目录。**不要用 self._plugin.PATH** —— 主程序要到 on_load 之后才给它
# 赋值（日志里的 _persist_plugin_paths 在 on_load 之后），构造阶段它是空串，
# Path("") 会被解析成当前目录，路径全错、主程序版本永远读不到。
_PLUGIN_DIR = Path(__file__).resolve().parent

from loguru import logger
from PySide6.QtCore import Property, QObject, Signal, Slot

# 功能（payload）与适配清单所在的仓库。
# 与插件本体分开：插件只带宿主接口，功能按需从这里下载。
# 换仓库、或仓库默认分支不叫 main 时，只改下面两行。
_FEATURE_REPO = "Kryon2025/More_Settings-Features"
_FEATURE_BRANCH = "main"
_MANIFEST_URL = (f"https://raw.githubusercontent.com/{_FEATURE_REPO}/"
                 f"{_FEATURE_BRANCH}/manifest.json")
_UA = "ClassWidgets2-ExtendedSettings-Installer"
_TIMEOUT = 20
_MAX_MANIFEST = 2 << 20        # 2 MB，清单不该比这更大
_MAX_PKG = 64 << 20            # 64 MB，单个包上限
_MAX_ENTRIES = 4096            # 单个 payload 最多多少个文件
_MAX_UNPACKED = 256 << 20      # 解压后总体积上限 256 MB（防解压炸弹）


# ── 版本比较 ──────────────────────────────────────────────────
# 主程序有两种写法，实测**都可能出现**：
#     正式版  2.0.1.0
#     测试版  2.0.0.dev20260923
# 两者都是合法 PEP 440，所以优先按 PEP 440 比较。
#
# 早先那套「取 8 位日期」在这里是**错的**：正式版 `2.0.1.0` 里根本没有 8 位
# 数字串，会掉进字符串兜底，于是正式版和测试版落进不同的比较桶，
# 两者之间的比较完全失真 —— 例如 `3.0.0.dev20270101`（更新的测试版）
# 会被判成比 `2.0.2.0`（更旧的正式版）还旧。
#
# 日期键只作为「PEP 440 解析不了」时的兜底。
# 注意：同一次比较里两边必须落在同一个桶，否则结果没有意义 ——
# 所以适配清单里的 cw2_min / cw2_max 要和主程序用同一种写法。

def cw_key(v):
    """把版本串转成可排序的键。"""
    s = str(v or "").strip()
    if s:
        try:
            from packaging.version import Version
            return (0, Version(s))
        except Exception:
            pass
    m = re.search(r"(\d{8})", s)
    if m:
        return (2, int(m.group(1)))
    return (3, s)


def cw_in_range(ver, lo, hi):
    """ver 是否落在 [lo, hi] 内。lo/hi 为 None 表示不限该侧。

    拿不到主程序版本时（ver 为空）一律返回 False，
    由调用方决定怎么处理 —— 见 _classify() 里的兜底。
    """
    if not ver:
        return False
    k = cw_key(ver)
    if lo and k < cw_key(lo):
        return False
    if hi and k > cw_key(hi):
        return False
    return True


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class InstallerBackend(QObject):
    """供 QML 使用的安装器后端。"""

    stateChanged = Signal()      # 任何状态变化，QML 重新拉一遍属性
    logChanged = Signal(str)     # 进度文字

    # 功能包已下载落盘，等主线程注入（注入碰组件注册，不能在子线程做）
    staged = Signal(str, str)
    # 功能包已移除，等主线程撤除补丁
    uninstalled = Signal(str)

    def __init__(self, plugin, config_dir: Path, parent=None):
        super().__init__(parent)
        self._plugin = plugin
        self._cfg_dir = Path(config_dir)
        self._cfg_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._cfg_dir / "installer_state.json"

        self._manifest = None
        self._state = "idle"          # idle / loading / ok / installing / error
        self._error = ""
        self._log = ""
        self._busy = False
        self._last_check = ""

        self._installer_version = self._read_own_version()
        self._cw2_version = self._detect_cw2_version()
        self._installed = self._load_state()

        # logText 属性读的是 _log，但到处只 emit 没赋值 —— 界面那行进度文字
        # 因此永远是空的。这里把信号转存回字段，一次修掉。
        self.logChanged.connect(self._remember_log)

    def _remember_log(self, msg: str):
        self._log = str(msg or "")

    # ── 路径与版本 ────────────────────────────────────────────
    def _read_own_version(self) -> str:
        try:
            mf = _PLUGIN_DIR / "cwplugin.json"
            return str(json.loads(mf.read_text(encoding="utf-8")).get("version", ""))
        except Exception:
            return ""

    def _plugins_dir(self) -> Path:
        """插件目录 = 本插件根目录的上一级。"""
        return _PLUGIN_DIR.parent

    def _features_dir(self) -> Path:
        """功能 payload 的存放根目录（本插件的数据目录内，不进主程序插件扫描）。"""
        d = self._cfg_dir / "features"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _feature_dir(self, feature_id: str) -> Path:
        """单个功能的目录。对 id 做白名单过滤，杜绝路径穿越。"""
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(feature_id))
        if not safe or safe in (".", ".."):
            raise ValueError(f"非法的功能 id: {feature_id}")
        return self._features_dir() / safe

    def _safe_extract(self, blob: bytes, dest: Path):
        """把 payload 解压到 dest。

        逐条校验后再逐个写出，不用 extractall：
        - 拒绝绝对路径、含 ".." 的条目、盘符（zip-slip 防护）
        - 解析后仍必须落在 dest 内，否则中止
        - 不跟随符号链接（只写普通文件）
        - 限制条目数与解压后总体积，防解压炸弹
        """
        dest.mkdir(parents=True, exist_ok=True)
        dest_r = dest.resolve()
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            infos = z.infolist()
            if len(infos) > _MAX_ENTRIES:
                raise ValueError(f"压缩包条目过多（{len(infos)}），拒绝解压")
            total = sum(i.file_size for i in infos)
            if total > _MAX_UNPACKED:
                raise ValueError(f"解压后体积过大（{total} 字节），拒绝解压")

            for info in infos:
                name = info.filename
                if (name.startswith("/") or name.startswith("\\")
                        or ":" in name or ".." in Path(name).parts):
                    raise ValueError(f"压缩包含非法路径条目：{name}")
                target = (dest_r / name).resolve()
                if target != dest_r and dest_r not in target.parents:
                    raise ValueError(f"压缩包含越界路径：{name}")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)

    # 主程序版本号的形状：devYYYYMMDD，或 0.7.0 / 0.7.0.1 这类分段式。
    # 分段式放宽到 1-4 位，否则 0.7.0 这种单数字段认不出来。
    _VER_RE = re.compile(r"\b(dev\d{8}|\d{1,4}\.\d{1,4}\.\d{1,4}(?:\.\d{1,8})?)\b")

    def _detect_cw2_version(self) -> str:
        """读取主程序版本。

        SDK 没有暴露这个字段（关于界面能显示版本，但那是主程序内部读的），
        所以这里按几条路找，都失败就返回 ""。拿不到版本时上层不会拒绝安装，
        只会限制成「仅可装已测试版本」—— 宁可保守，也不因为读不到版本就把用户卡死。
        """
        root = self._plugins_dir().parent

        # 路线 0：确知的位置。主程序把版本存在自己的 configs.json 里，
        # 实测 app.version = "2.0.0.dev20260916"（关于界面显示的就是它）。
        try:
            p = root / "configs" / "configs.json"
            if p.is_file():
                v = (json.loads(p.read_text(encoding="utf-8")).get("app") or {}) \
                    .get("version")
                if v:
                    return str(v)
        except Exception:
            pass

        candidates = (
            "version.json", "package.json", "cw2.json", "pyproject.toml",
            "configs/version.json", "configs/settings.json", "configs/app.json",
        )

        # 路线 1：明确字段
        for rel in candidates:
            p = root / rel
            try:
                if p.is_file():
                    data = json.loads(p.read_text(encoding="utf-8"))
                    for key in ("version", "app_version", "cw2_version",
                                "application_version"):
                        if isinstance(data, dict) and data.get(key):
                            return str(data[key])
            except Exception:
                continue

        # 路线 2：按形状扫（不依赖字段名，也不依赖 JSON 格式）
        for rel in candidates:
            p = root / rel
            try:
                if p.is_file():
                    txt = p.read_text(encoding="utf-8", errors="ignore")
                    m = self._VER_RE.search(txt)
                    if m:
                        return m.group(1)
            except Exception:
                continue

        # 路线 3：环境变量（某些发行版会设）
        try:
            for env in ("CW2_VERSION", "CLASSWIDGETS_VERSION"):
                if os.environ.get(env):
                    return str(os.environ[env])
        except Exception:
            pass
        return ""

    # ── 已安装状态（落盘，跨重启保留）──────────────────────────
    def _load_state(self) -> dict:
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_state(self):
        try:
            self._state_file.write_text(
                json.dumps(self._installed, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            logger.warning("[extended_settings] 安装状态写入失败: {}", e)

    # ── 网络 ──────────────────────────────────────────────────
    def _http_get(self, url: str, limit: int) -> bytes:
        if not url.startswith("https://"):
            raise ValueError(f"只允许 https 地址: {url}")
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = resp.read(limit + 1)
        if len(data) > limit:
            raise ValueError(f"响应超过 {limit} 字节上限，拒绝处理")
        return data

    def _fetch_manifest(self) -> dict:
        raw = self._http_get(_MANIFEST_URL, _MAX_MANIFEST)
        m = json.loads(raw.decode("utf-8"))
        if not isinstance(m.get("features"), list):
            raise ValueError("清单里没有 features 数组")
        return m

    # ── 供 QML ────────────────────────────────────────────────
    @Slot()
    def refresh(self):
        """后台拉取清单并在内存里做版本匹配，不写盘。"""
        if self._busy:
            return
        self._busy = True
        self._state = "loading"
        self._error = ""
        self.logChanged.emit("正在获取适配清单…")
        self.stateChanged.emit()
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            self._manifest = self._fetch_manifest()
            self._state = "ok"
            self._last_check = str(self._manifest.get("updated", ""))
            self.logChanged.emit("适配清单获取成功")
        except Exception as e:
            self._state = "error"
            self._error = str(e)
            self.logChanged.emit(f"获取清单失败：{e}")
            logger.warning("[extended_settings] 拉取适配清单失败: {}", e)
        finally:
            self._busy = False
            self.stateChanged.emit()

    def _classify(self, feat: dict) -> dict:
        """给一个功能算出：当前状态 + 该装哪个版本。"""
        installed = self._installed.get(feat["id"]) or {}
        cur_ver = installed.get("version", "")

        def pick(only_tested: bool):
            """挑出符合当前主程序版本的版本号，优先最新。"""
            best, best_key = None, None
            for v in feat.get("versions", []):
                if only_tested and not v.get("tested"):
                    continue
                if self._cw2_version:
                    # 用【这个版本自己的】适配区间判定；没写才回退到功能级。
                    # 这样一个功能的历史版本才能各自适配不同的主程序版本。
                    if not cw_in_range(self._cw2_version,
                                       v.get("cw2_min") or feat.get("cw2_min"),
                                       v.get("cw2_max") or feat.get("cw2_max")):
                        continue
                else:
                    # 拿不到主程序版本：不拒绝，但只认"已测试"的
                    if not v.get("tested"):
                        continue
                k = cw_key(v.get("version"))
                if best is None or k > best_key:
                    best, best_key = v, k
            return best

        target = pick(True)
        any_ver = pick(False) or target

        if not cur_ver:
            status = "not_installed"
        elif target and cw_key(target["version"]) > cw_key(cur_ver):
            status = "upgradable"
        elif any_ver and cw_key(cur_ver) > cw_key(any_ver["version"]):
            status = "ahead"
        else:
            status = "installed"

        matched = True
        if self._cw2_version and not cw_in_range(self._cw2_version,
                                                 feat.get("cw2_min"), feat.get("cw2_max")):
            matched = False

        return {
            "id": feat["id"],
            "name": feat.get("name", feat["id"]),
            "summary": feat.get("summary", ""),
            "patches": feat.get("patches", []),
            "cw2_min": feat.get("cw2_min") or "",
            "cw2_max": feat.get("cw2_max") or "",
            "versions": feat.get("versions", []),
            "installed": cur_ver,
            "tested": bool(installed.get("tested", True)),
            "enabled": bool(installed.get("enabled", True)),
            "imported": bool(installed.get("imported", False)),
            "status": status,
            "matched": matched,
            # 可安装的目标版本：已适配且已测试的最新版；没有就退回任意最新版
            "target": (target or any_ver or {}).get("version", ""),
            "target_tested": bool((target or {}).get("tested", False)),
        }

    def _read_local_meta(self, feature_id: str) -> dict:
        """读一个已落盘功能自带的 payload.json。"""
        try:
            p = self._feature_dir(feature_id) / "payload.json"
            if p.is_file():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("[extended_settings] 读 {} 的 payload.json 失败: {}",
                           feature_id, e)
        return {}

    def _local_only_entry(self, fid: str, rec: dict) -> dict:
        """清单里没有、但本地导入过的功能，也要在界面上显示出来。

        否则手动导入完，列表里一片空白，用户会以为导入失败。
        """
        meta = self._read_local_meta(fid)
        return {
            "id": fid,
            "name": str(meta.get("name") or fid),
            "summary": str(meta.get("summary") or "手动导入的功能，不在在线清单里。"),
            "patches": meta.get("patches", []) or [],
            "cw2_min": "",
            "cw2_max": "",
            "versions": [],
            "installed": str(rec.get("version", "")),
            "tested": bool(rec.get("tested", False)),
            "enabled": bool(rec.get("enabled", True)),
            "imported": True,
            "status": "installed",
            "matched": True,
            "target": "",
            "target_tested": False,
        }

    def _features(self) -> list:
        out = []
        seen = set()
        for f in (self._manifest or {}).get("features", []):
            try:
                info = self._classify(f)
            except Exception as e:
                logger.warning("[extended_settings] 功能 {} 解析失败: {}", f.get("id"), e)
                continue
            out.append(info)
            seen.add(info["id"])
        # 本地手动导入、清单里没有的功能
        for fid, rec in self._installed.items():
            if fid in seen:
                continue
            try:
                out.append(self._local_only_entry(fid, rec))
            except Exception as e:
                logger.warning("[extended_settings] 本地功能 {} 解析失败: {}", fid, e)
        return out

    # ── 安装 ──────────────────────────────────────────────────
    @Slot(str, str)
    def install(self, feature_id: str, version: str = ""):
        """下载并安装指定功能。version 留空则用适配且已测试的最新版。"""
        if self._busy:
            return
        feat = None
        for f in (self._manifest or {}).get("features", []):
            if f.get("id") == feature_id:
                feat = f
                break
        if not feat:
            self._fail("清单里找不到该功能")
            return

        entry = None
        if version:
            for v in feat.get("versions", []):
                if v.get("version") == version:
                    entry = v
                    break
        else:
            info = self._classify(feat)
            for v in feat.get("versions", []):
                if v.get("version") == info["target"]:
                    entry = v
                    break
        if not entry:
            self._fail("找不到要安装的版本")
            return

        self._busy = True
        self._state = "installing"
        self.stateChanged.emit()
        threading.Thread(target=self._install_worker, args=(feat, entry),
                         daemon=True).start()

    def _fail(self, msg: str):
        self._state = "error"
        self._error = msg
        self._busy = False
        self.logChanged.emit(msg)
        self.stateChanged.emit()

    def _install_worker(self, feat: dict, entry: dict):
        name = feat.get("name", feat["id"])
        url = str(entry.get("asset", ""))
        want = str(entry.get("sha256", ""))
        try:
            self.logChanged.emit(f"正在下载 {name} {entry.get('version')}…")
            blob = self._http_get(url, _MAX_PKG)

            got = hashlib.sha256(blob).hexdigest()
            if want and got.lower() != want.lower():
                raise ValueError(f"sha256 校验不通过（期望 {want[:12]}…，"
                                 f"实际 {got[:12]}…），已丢弃")

            self._place_payload(feat["id"], blob, name)
            self._installed[feat["id"]] = {
                "version": entry.get("version"),
                "dir": self._feature_dir(feat["id"]).name,
                "tested": bool(entry.get("tested", False)),
                "enabled": True,
                "imported": False,
                "installed_at": _now(),
                # 未测试的包要提示一次，由主程序下次启动时消费
                "pending_warning": not entry.get("tested", False),
            }
            self._save_state()
            self._state = "activating"
            self.logChanged.emit(f"{name} 下载完成，正在注入补丁…")
            self.staged.emit(feat["id"], str(entry.get("version") or ""))
        except Exception as e:
            self._state = "error"
            self._error = str(e)
            self.logChanged.emit(f"{name} 安装失败：{e}")
            logger.warning("[extended_settings] 安装 {} 失败: {}", name, e)
        finally:
            self._busy = False
            self.stateChanged.emit()

    def _place_payload(self, feature_id: str, blob: bytes, name: str, meta: dict = None):
        """把 payload 落盘到 features/<id>/。

        先解压到 .staging_<id>，全部成功后再整体换名过去 ——
        解压中途失败不会留下半个功能目录。
        """
        staging = self._features_dir() / f".staging_{feature_id}"
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        try:
            self._safe_extract(blob, staging)
            entry = str((meta or {}).get("entry") or "feature.py")
            if not (staging / entry).is_file():
                raise ValueError(f"包里没有入口文件 {entry}，不是有效的 payload")
            dest = self._feature_dir(feature_id)
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            os.replace(staging, dest)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    # ── 手动导入 ──────────────────────────────────────────────
    @Slot(str)
    def importPayload(self, source: str):
        """手动导入一个 payload 文件。

        source 可以是本地路径、QML FileDialog 给的 file:// URL，或 https 地址。
        为的是在清单拉不到 / 用户拿到了别人分享的包时，还能离线装上。
        """
        if self._busy:
            return
        self._busy = True
        self._state = "installing"
        self._error = ""
        self.stateChanged.emit()
        threading.Thread(target=self._import_worker, args=(str(source or ""),),
                         daemon=True).start()

    @staticmethod
    def _file_url_to_path(s: str) -> Path:
        """把来源还原成本地路径。

        三个坑：
        - QML 的 FileDialog 给的是 file:///F:/x/y.cwpayload，含百分号编码；
        - **Windows 盘符路径 F:\\x\\y 会被 urlparse 解析成 scheme="f"**，
          所以必须先把盘符路径和 UNC 认出来，不能一上来就 urlparse，
          否则「直接粘本地路径」这条路会报「不支持的来源: f」；
        - Windows 上 str(Path) 会把 / 归一成 \\，比较时要用 Path 对象而非字符串。
        """
        from urllib.parse import unquote, urlparse

        s = str(s or "").strip().strip('"')
        if not s:
            raise ValueError("没有选择文件")

        # 盘符路径与 UNC：先于 URL 解析处理
        if re.match(r"^[A-Za-z]:[\\/]", s) or s.startswith("\\\\"):
            return Path(s)

        u = urlparse(s)
        if not u.scheme:
            return Path(unquote(s))
        if u.scheme != "file":
            raise ValueError(f"不支持的来源：{u.scheme}")
        p = unquote(u.path or "")
        if re.match(r"^/[A-Za-z]:", p):
            p = p[1:]          # /F:/x -> F:/x
        return Path(p)

    @staticmethod
    def _read_payload_meta(blob: bytes, suggested: str):
        """从 payload 里读出它自带的 payload.json。

        没有 payload.json 时退回「按文件名推 id」—— 早期手工打的包也能导入，
        但会被标成未测试。返回 (meta, feature_id)。
        """
        meta = {}
        with zipfile.ZipFile(io.BytesIO(blob)) as z:      # BadZipFile 由调用方接住
            for nm in z.namelist():
                if nm.count("/") == 0 and nm.endswith("payload.json"):
                    meta = json.loads(z.read(nm).decode("utf-8"))
                    break
                if nm.count("/") == 1 and nm.endswith("/payload.json"):
                    meta = json.loads(z.read(nm).decode("utf-8"))
                    break

        fid = str(meta.get("id") or "").strip()
        if not fid:
            stem = re.sub(r"\.(cwpayload|zip|payload)$", "", str(suggested), flags=re.I)
            stem = re.sub(r"-\d+(\.\d+)*$", "", stem) or stem   # <id>-<版本> -> <id>
            fid = stem.strip()
            if not fid:
                raise ValueError("无法确定功能 id：包里没有 payload.json，文件名也推不出来")
            meta.setdefault("id", fid)
            meta.setdefault("name", fid)
        return meta, fid

    def _import_worker(self, source: str):
        try:
            src = source.strip().strip('"')
            if not src:
                raise ValueError("没有选择文件")

            if src.lower().startswith(("http://", "https://")):
                if not src.lower().startswith("https://"):
                    raise ValueError("只允许 https 地址")
                self.logChanged.emit(f"正在下载 {src.rsplit('/', 1)[-1]}…")
                blob = self._http_get(src, _MAX_PKG)
                suggested = src.split("?")[0].rsplit("/", 1)[-1]
            else:
                p = self._file_url_to_path(src)
                if not p.is_file():
                    raise ValueError(f"文件不存在：{p}")
                if p.stat().st_size > _MAX_PKG:
                    raise ValueError("文件超过大小上限，已拒绝")
                blob = p.read_bytes()
                suggested = p.name

            try:
                meta, fid = self._read_payload_meta(blob, suggested)
            except zipfile.BadZipFile:
                raise ValueError("不是有效的 zip / payload 文件") from None

            name = str(meta.get("name") or fid)
            version = str(meta.get("version") or "imported")
            self.logChanged.emit(f"正在校验并安装 {name}…")

            self._place_payload(fid, blob, name, meta)
            self._installed[fid] = {
                "version": version,
                "dir": self._feature_dir(fid).name,
                "tested": bool(meta.get("tested", False)),
                "enabled": True,
                "imported": True,
                "installed_at": _now(),
                # 手动导入的来源不明，启动后提示一次
                "pending_warning": True,
            }
            self._save_state()
            self._state = "ok"
            self.logChanged.emit(f"{name} 已导入，重启主程序后生效")
            logger.info("[extended_settings] 手动导入 {} ({}) 成功", fid, version)
        except Exception as e:
            self._state = "error"
            self._error = str(e)
            self.logChanged.emit(f"导入失败：{e}")
            logger.warning("[extended_settings] 导入 payload 失败: {}", e)
        finally:
            self._busy = False
            self.stateChanged.emit()

    @Slot(str)
    def uninstall(self, feature_id: str):
        """移除已安装的功能目录并清掉记录。"""
        rec = self._installed.get(feature_id)
        if not rec:
            return
        try:
            d = self._feature_dir(feature_id)
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
        except Exception as e:
            logger.warning("[extended_settings] 删除功能目录失败: {}", e)
        self._installed.pop(feature_id, None)
        self._save_state()
        self.logChanged.emit("已移除，正在撤除补丁…")
        self.uninstalled.emit(feature_id)
        self.stateChanged.emit()

    @Slot(str, bool)
    @Slot(str)
    def discardInstalled(self, feature_id: str):
        """撤回一次安装：删目录 + 清记录。

        由主线程在「补丁验收没通过」时调用 —— 装上了但注入不了，
        就当没装过，绝不留下一个「装了却半注入」的状态。
        """
        try:
            d = self._feature_dir(feature_id)
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
        except Exception as e:
            logger.warning("[extended_settings] 撤回时删目录失败: {}", e)
        self._installed.pop(feature_id, None)
        self._save_state()

    def finishActivation(self, feature_id: str, ok: bool, message: str):
        """主线程注入结束后的收尾：回到空闲，把最终结果告诉界面。"""
        if not ok:
            self._installed.pop(feature_id, None)
            self._save_state()
        self._state = "ok" if ok else "error"
        self._error = "" if ok else message
        self._busy = False
        self.logChanged.emit(message)
        self.stateChanged.emit()

    def setEnabled(self, feature_id: str, on: bool):
        """启用 / 禁用某个功能。

        只改状态。真正的组件注册与主程序补丁在下次加载插件时按此状态执行，
        所以界面上要说清「重启后生效」。
        """
        rec = self._installed.get(feature_id)
        if not rec:
            return
        rec["enabled"] = bool(on)
        self._save_state()
        self.logChanged.emit("已启用，重启主程序后生效" if on
                             else "已禁用，重启主程序后生效")
        self.stateChanged.emit()

    @Slot(str, result=bool)
    def enabledOf(self, feature_id: str) -> bool:
        rec = self._installed.get(feature_id) or {}
        return bool(rec.get("enabled", False))

    @Slot(result="QStringList")
    def enabledFeatureIds(self):
        """已安装且启用的功能 id —— 运行时按这个列表加载 payload。"""
        return [fid for fid, rec in self._installed.items()
                if rec.get("enabled", True)]

    @Slot(result="QVariantList")
    def enabledPayloads(self):
        """给插件的加载器用：已启用功能 + 它们的目录 + payload.json 内容。

        一次给全，省得加载器自己去拼路径、读文件。
        """
        out = []
        for fid in self.enabledFeatureIds():
            try:
                d = self._feature_dir(fid)
            except Exception:
                continue
            out.append({
                "id": fid,
                "dir": str(d),
                "exists": d.is_dir(),
                "meta": self._read_local_meta(fid),
            })
        return out

    @Slot(str, result=str)
    def featureDirOf(self, feature_id: str) -> str:
        """功能目录绝对路径，供 QML 用 Loader 加载它自己的设置页。"""
        try:
            if feature_id not in self._installed:
                return ""
            return str(self._feature_dir(feature_id))
        except Exception:
            return ""

    @Slot(result=bool)
    def takePendingWarning(self):
        """取出"有待提示的未测试 / 手动导入安装"标记，取出即清除（只提示一次）。"""
        hit = False
        for k, rec in list(self._installed.items()):
            if rec.get("pending_warning"):
                rec["pending_warning"] = False
                hit = True
        if hit:
            self._save_state()
        return hit

    # ── QML 属性 ──────────────────────────────────────────────
    def _get_state(self):
        return self._state

    def _get_error(self):
        return self._error

    def _get_busy(self):
        return self._busy

    def _get_log(self):
        return self._log

    def _get_features(self):
        return self._features()

    def _get_cw2(self):
        return self._cw2_version

    def _get_installer(self):
        return self._installer_version

    def _get_plugins_dir(self):
        try:
            return str(self._plugins_dir())
        except Exception:
            return ""

    def _get_last_check(self):
        return self._last_check

    installerVersion = Property(str, _get_installer, notify=stateChanged)
    cw2Version = Property(str, _get_cw2, notify=stateChanged)
    pluginsDir = Property(str, _get_plugins_dir, notify=stateChanged)
    lastCheck = Property(str, _get_last_check, notify=stateChanged)
    state = Property(str, _get_state, notify=stateChanged)
    errorText = Property(str, _get_error, notify=stateChanged)
    busy = Property(bool, _get_busy, notify=stateChanged)
    features = Property("QVariantList", _get_features, notify=stateChanged)
    logText = Property(str, _get_log, notify=logChanged)


def _now() -> str:
    import datetime
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")
