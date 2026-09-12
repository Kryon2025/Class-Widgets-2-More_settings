"""Kryon 的更多设置 —— 统一配置模型。

配置经官方插件配置通道持久化，存储于
``configs.json -> plugins.configs.com.kryon.more_settings``。

字段说明：
- countdown_animation：内置"事件倒计时"组件数字滚动动画开关
- time_*：内置"时间"组件的显示选项（动画 / 秒 / 日期 / 星期 / 布局 / 交替）
- display_height：组件距屏幕顶部距离（顶部停靠时生效；-1 = 跟随主程序默认偏移）
- hide_depth：隐藏时保留在屏幕边缘的宽度（px）

模块名刻意用 ``more_settings_config`` 而非 ``config``，避免与其它插件的
``config.py`` 在顶层命名空间冲突。
"""

from __future__ import annotations

from ClassWidgets.SDK import ConfigBaseModel


class MoreSettingsConfig(ConfigBaseModel):
    """Kryon 的更多设置配置。"""

    # 事件倒计时
    countdown_animation: bool = True

    # 时间组件（官方内置组件增强）
    time_animation: bool = True            # 数字滚动动画开关
    time_show_seconds: bool = True         # 显示秒
    time_show_date: bool = True            # 显示日期（总开关）
    time_show_year: bool = True            # 日期显示年
    time_show_month: bool = True           # 日期显示月
    time_show_day: bool = True             # 日期显示日
    time_show_weekday: bool = True         # 显示星期
    time_title_mode: str = "side_by_side"  # 日期与星期布局：side_by_side / alternate
    time_alternate_interval: int = 3000    # 交替间隔（毫秒）
    time_alternate_animation: bool = False  # 交替切换淡入淡出

    # 小组件高度/深度
    display_height: float = -1             # 展示高度（px；-1 = 跟随默认偏移）
    hide_depth: float = 24                 # 隐藏深度（px）

    # 特定课程不隐藏（仅在主程序"在课堂中隐藏"时生效；按课表所选科目判定）
    hide_excluded_enabled: bool = False    # 开关
    hide_excluded_lessons: str = ""        # 旧版：课程名列表（逗号分隔，保留兼容）
    hide_excluded_subjects: str = "[]"     # 科目列表（JSON 数组，如 ["自习","体育"]）
