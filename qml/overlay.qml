import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import QtQuick.Window
import RinUI
import ClassWidgets.Theme 1.0

// 堆叠组件（灵动岛）：多个成员组件叠放，按设定间隔循环滚动展示（轮播模式）；
// 在主程序"编辑堆叠组件"时切换为纵列列表模式，成员依次列出，
// 右键成员可单独编辑其设置，成员左上角减号移除成员。
// 容器本身无标题无背景（不继承 Widget 卡片），成员组件自带卡片，
// 成员内容即组件内容，不会被标题栏挤下去。

Item {
    id: root

    // 主程序 WidgetLoader 注入的属性
    property var backend: null
    property var settings: null
    property bool editMode: false
    // 主程序"编辑重叠组件"模式：true 时成员纵列列出（由 WidgetLoader 转发）
    property bool overlayListMode: false
    // 实例 id（WidgetLoader 注入）：桌面上多个堆叠组件实例各自独立
    // 管理成员列表、成员设置与自定义框尺寸，互不干扰
    property string instanceId: ""

    // WidgetLoader 在组件创建完成后才注入 backend（Loader.Ready），
    // 因此不能用 onCompleted 刷新，改为 backend 注入时触发。
    // 注意：WidgetLoader 先注入 backend、后注入 instanceId，若立刻读取
    // 会拿空实例 ID 误读 default 组 → 延迟一帧到 instanceId 就绪后再刷。
    onBackendChanged: {
        if (backend) Qt.callLater(function() { root.refresh() })
    }

    // 实例 ID 注入/变化（桌面组件重载、模型刷新）后按实例重新读取
    onInstanceIdChanged: {
        if (backend) Qt.callLater(function() { root.refresh() })
    }

    // ── 上课期间隐藏切换条 ──────────────────────────────
    // 配置由插件后端自持久化（backend.classHide*），组件加载/设置页保存后
    // 通过 classHideChanged 信号刷新，不依赖主程序组件 settings 的保存时机
    property bool classHideEnabled: backend && backend.classHideEnabled
    property string classHideDays: backend ? backend.classHideDays : ""
    property string classHideStart: backend ? backend.classHideStart : ""
    property string classHideEnd: backend ? backend.classHideEnd : ""
    // 自定义时段是否上课中（由 updateClassState 计算）
    property bool classHideInClass: false
    // 课表/灵动通知状态：主程序内置课表运行时 currentStatus === "class" 即上课中
    // （灵动通知的上下课信息与它同源；绑定自动响应变化，上课/下课瞬间生效）
    property bool scheduleInClass: typeof AppCentral !== "undefined"
        && AppCentral.scheduleRuntime && AppCentral.scheduleRuntime.currentStatus === "class"
    // 灵动通知内容触发：收到含"上课"的通知隐藏切换条，含"下课"的通知显示
    property bool notificationInClass: false
    property bool inClass: root.scheduleInClass || root.notificationInClass || root.classHideInClass

    function containsClassStart(txt) {
        return txt.indexOf("上课") >= 0 || txt.indexOf("开始上课") >= 0
            || txt.indexOf("class starts") >= 0 || txt.indexOf("class begins") >= 0
    }

    function containsClassEnd(txt) {
        return txt.indexOf("下课") >= 0 || txt.indexOf("放学") >= 0
            || txt.indexOf("下课啦") >= 0 || txt.indexOf("课间") >= 0
            || txt.indexOf("休息") >= 0
            || txt.indexOf("class over") >= 0 || txt.indexOf("class ends") >= 0
            || txt.indexOf("class dismissed") >= 0 || txt.indexOf("class finished") >= 0
            || txt.indexOf("end of class") >= 0 || txt.indexOf("break") >= 0
    }

    // 监听灵动通知（与主程序 dynamicNotification.qml 同一信号源 AppCentral.notification）
    Connections {
        target: typeof AppCentral !== "undefined" && AppCentral.notification ? AppCentral.notification : null
        function onNotified(payload) {
            if (!payload) return
            var txt = String(payload.title || "") + " " + String(payload.message || "")
            if (root.containsClassStart(txt)) {
                root.notificationInClass = true
                notifRecoverTimer.restart()
            } else if (root.containsClassEnd(txt)) {
                root.notificationInClass = false
                notifRecoverTimer.stop()
            }
        }
    }

    // 兜底：收到"上课"通知后若一节课时长（90 分钟）内没有新的上下课通知，
    // 自动恢复显示切换条（防止下课通知文本不同/未触发导致永久隐藏）
    Timer {
        id: notifRecoverTimer
        interval: 90 * 60 * 1000
        repeat: false
        onTriggered: root.notificationInClass = false
    }

    function parseTimeStr(t) {
        var m = /^(\d{1,2}):(\d{2})$/.exec(String(t || "").trim())
        if (!m) return -1
        return parseInt(m[1], 10) * 60 + parseInt(m[2], 10)
    }

    function computeInClass() {
        if (!root.classHideEnabled) return false
        var now = new Date()
        var wd = now.getDay()
        var day = wd === 0 ? 7 : wd  // 1=周一 … 7=周日
        if (root.classHideDays.indexOf(String(day)) < 0) return false
        var s = root.parseTimeStr(root.classHideStart)
        var e = root.parseTimeStr(root.classHideEnd)
        if (s < 0 || e < 0 || s >= e) return false
        var cur = now.getHours() * 60 + now.getMinutes()
        return cur >= s && cur < e
    }

    function updateClassState() { root.classHideInClass = root.computeInClass() }

    onClassHideEnabledChanged: root.updateClassState()
    onClassHideDaysChanged: root.updateClassState()
    onClassHideStartChanged: root.updateClassState()
    onClassHideEndChanged: root.updateClassState()

    // 上课开始/结束瞬间生效：每分钟重算一次（running 始终开启，
    // 不依赖组件 settings 绑定的刷新可靠性；设置页保存后也有信号立即重算）
    Timer {
        interval: 30000
        running: true
        repeat: true
        onTriggered: root.updateClassState()
    }

    // 设置页保存"上课隐藏切换条"配置后立即重算（settings 注入时机不固定，
    // 信号比绑定刷新可靠）
    Connections {
        target: backend
        function onClassHideChanged() {
            root.updateClassState()
        }
    }

    property var members: []
    property int activeIndex: 0
    property var defs: WidgetsModel ? WidgetsModel.definitionsList : []
    property int maxW: 0
    property int maxH: 0
    property int listSpacing: 10
    readonly property int autoW: Math.max(96, root.maxW + root.switchBarSpace)
    readonly property int autoH: Math.max(80, root.maxH)

    // 自定义组件框宽高（0 = 跟随内容自适应；按实例持久化于后端）
    property int frameW: 0
    property int frameH: 0

    // 右侧切换条占位宽度（仅显示切换条时预留，保证不超出组件边界被裁剪）
    property int switchBarSpace: root.showSwitchBar && root.members.length > 0 ? 48 : 0

    // 迷你模式（主程序全局配置）：容器与切换条高度跟随，与其它组件保持一致
    readonly property bool miniMode: Configs.data.preferences.mini_mode

    // 轮播模式框尺寸：frameW/H > 0 时用自定义值，否则自动；迷你模式保持全局一致
    implicitWidth: root.frameW > 0 ? root.frameW : root.autoW
    implicitHeight: root.overlayListMode
        ? Math.max(80, root.listTotalH())
        : (root.miniMode ? 56 : (root.frameH > 0 ? root.frameH : root.autoH))

    // 轮播间隔由组件设置 interval_ms 控制（列表模式 / 编辑模式暂停）
    property int carouselInterval: settings && settings.interval_ms ? settings.interval_ms : 5000

    // 右侧“切换”条显示开关（组件设置 show_switch_bar 控制，默认显示）
    property bool showSwitchBar: settings && settings.show_switch_bar !== false

    Timer {
        id: carouselTimer
        interval: root.carouselInterval
        repeat: true
        // 隐藏（主程序交互设置）或编辑/列表模式下暂停成员切换
        running: root.members.length > 1 && !root.editMode && !root.overlayListMode
            && !Configs.data.interactions.hide.state
        onTriggered: {
            root.activeIndex = (root.activeIndex + 1) % root.members.length
        }
    }

    Connections {
        target: backend
        function onMembersChanged() { root.refresh() }
        function onFrameChanged() { root.reloadFrame() }
    }

    function findDef(widgetId) {
        for (var i = 0; i < root.defs.length; i++) {
            if (root.defs[i].id === widgetId) return root.defs[i]
        }
        return null
    }

    function refresh() {
        if (!backend) return
        var list = backend.getMembers(root.instanceId)
        root.members = list
        if (root.activeIndex >= list.length) root.activeIndex = 0
        root.reloadFrame()
    }

    // 读取该实例的自定义框尺寸（0 = 自适应）
    function reloadFrame() {
        if (!backend) return
        var f = backend.getFrameSize(root.instanceId)
        root.frameW = f ? (f.w || 0) : 0
        root.frameH = f ? (f.h || 0) : 0
    }

    // 步进调整框宽/高（px）；自适应(0)时首次步进以当前实际尺寸起步
    function stepFrame(dw, dh) {
        if (!backend) return
        var w = root.frameW
        if (dw !== 0) {
            w = w > 0 ? w + dw : root.autoW + (dw > 0 ? dw : 0)
            if (w < 60) w = 60
        }
        var h = root.frameH
        if (dh !== 0) {
            h = h > 0 ? h + dh : root.autoH + (dh > 0 ? dh : 0)
            if (h < 40) h = 40
        }
        backend.setFrameSize(root.instanceId, w, h)
        root.reloadFrame()
    }

    // 恢复为跟随内容自适应
    function resetFrame() {
        if (!backend) return
        backend.setFrameSize(root.instanceId, 0, 0)
        root.frameW = 0
        root.frameH = 0
    }

    // 列表模式下第 i 个成员的 y：固定行高（maxH + 间距），不依赖高度缓存，
    // 成员增删后 delegate 重载/加载期间也不会归零导致成员叠放
    function listY(i) {
        return i * (root.maxH + root.listSpacing)
    }

    function listTotalH() {
        var n = root.members.length
        if (n <= 0) return 0
        return n * root.maxH + root.listSpacing * (n - 1)
    }

    // 成员设置的最终值 = 默认设置 + 个性化设置覆盖（保证未保存过的字段
    // 显示组件默认值，与组件实际运行状态一致）
    function mergedMemberSettings(key, typeId) {
        var d = root.findDef(typeId)
        var defaults0 = d ? (d.default_settings || {}) : {}
        var saved0 = (root.backend && root.backend.getMemberSettings)
            ? (root.backend.getMemberSettings(root.instanceId, key) || {})
            : {}
        var merged = {}
        for (var k in defaults0) merged[k] = defaults0[k]
        for (var k2 in saved0) merged[k2] = saved0[k2]
        return merged
    }

    // 点击“切换”条：切到下一个成员并重置轮播计时（不触发组件自动隐藏）
    function nextMember() {
        if (root.members.length > 1) {
            root.activeIndex = (root.activeIndex + 1) % root.members.length
            if (carouselTimer.running) carouselTimer.restart()
        }
    }

    // 成员显示名
    function nameOf(typeId) {
        var d = root.findDef(typeId)
        return d ? (d.name || typeId) : typeId
    }

    function removeMemberByKey(k) {
        if (root.backend) root.backend.removeMember(root.instanceId, k)
    }

    // 打开本堆叠组件实例自己的居中编辑窗口
    function openOverlayEditor() {
        root.refresh()
        overlayEditDialog.open()
    }

    // 右键成员 → 单独编辑该组件设置
    function openMemberSettings(i) {
        var m = root.members[i]
        if (!m) return
        var typeId = m.typeId
        var key = m.key
        var d = root.findDef(typeId)
        if (!d || !root.backend) return
        // 字段兜底：不同来源的定义列表字段名可能不同
        var sq = d.settingsQml || d.settings_qml || ""
        console.log("[overlay] openMemberSettings:", key, "settingsQml:", sq)
        if (!sq) return
        var merged = root.mergedMemberSettings(key, typeId)
        memberSettingsDialog.currentMemberId = key
        memberSettingsDialog.currentMemberTypeId = typeId
        settingsLoader.setSource(sq, {
            "settings": merged,
            "instanceId": ""
        })
        memberSettingsDialog.open()
    }

    // 保存成员设置后同步到已加载的成员实例
    function applyMemberSettings(key, typeId) {
        var merged = root.mergedMemberSettings(key, typeId)
        for (var k = 0; k < memberRepeater.count; k++) {
            var obj = memberRepeater.itemAt(k)
            if (obj && obj.memberId === key && obj.item
                    && obj.item.settings !== undefined) {
                obj.item.settings = merged
            }
        }
    }

    Component.onCompleted: {
        if (backend) refresh()
        root.updateClassState()
    }

    // 空状态提示（无成员时）
    Text {
        anchors.centerIn: parent
        visible: root.members.length === 0
        text: "堆叠组件\n右键编辑添加成员"
        horizontalAlignment: Text.AlignHCenter
        color: Theme.isDark() ? Qt.rgba(1, 1, 1, 0.55) : Qt.rgba(0, 0, 0, 0.55)
        font.pixelSize: 13
        lineHeight: 1.4
    }

    // 成员：轮播模式叠放居中（仅 activeIndex 显示，交叉淡化 + 缩放）；
    // 列表模式纵列依次排列（全部显示，右键可编辑成员设置）
    Repeater {
        id: memberRepeater
        anchors.fill: parent
        model: root.members

        Loader {
            id: memberLoader
            asynchronous: true
            z: index === root.activeIndex ? 1 : 0
            // 轮播模式在内容区（排除右侧切换条）居中；列表模式纵列
            x: root.overlayListMode ? 0 : (Math.max(0, parent.width - root.switchBarSpace - width)) / 2
            y: root.overlayListMode ? root.listY(index) : (parent.height - height) / 2
            opacity: root.overlayListMode
                ? 1
                : (index === root.activeIndex ? 1 : 0)
            scale: root.overlayListMode
                ? 1
                : (index === root.activeIndex ? 1 : 0.9)

            Behavior on opacity {
                NumberAnimation { duration: 420; easing.type: Easing.InOutQuad }
            }
            Behavior on scale {
                NumberAnimation { duration: 420; easing.type: Easing.OutCubic }
            }

            // 右键成员 → 单独编辑该组件设置（仅编辑堆叠组件模式生效；
            // 非编辑状态禁用，右键交还堆叠组件菜单）
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.RightButton
                enabled: root.overlayListMode
                onClicked: (mouse) => {
                    if (mouse.button === Qt.RightButton) root.openMemberSettings(index)
                }
            }

            // 列表模式下成员左上角的移除按钮（与原版组件删除按钮一致）
            ToolButton {
                visible: root.overlayListMode
                icon.name: "ic_fluent_line_horizontal_1_20_filled"
                size: 12
                width: 24
                height: 24
                anchors.top: parent.top
                anchors.left: parent.left
                onClicked: {
                    if (root.backend) root.backend.removeMember(root.instanceId, memberId)
                }
            }

            property string memberId: modelData.key
            property string memberTypeId: modelData.typeId
            source: {
                var d = root.findDef(memberTypeId)
                return d && d.qml_path ? d.qml_path : ""
            }

            onLoaded: {
                var d = root.findDef(memberTypeId)
                if (d) {
                    if (d.backend_obj && item) item.backend = d.backend_obj
                    if (item) {
                        // 禁用成员自身的尺寸动画，保证堆叠布局稳定（不随成员尺寸变化抖动）
                        if (item.hasOwnProperty("animateSize")) item.animateSize = false
                        // 成员设置 = 默认设置 + 个性化覆盖，保证开关等控件的
                        // 初始显示与组件实际运行状态一致
                        item.settings = root.mergedMemberSettings(memberId, memberTypeId)
                    }
                }
                // 记录成员尺寸（容器随之固定；列表模式用固定行高排布）
                if (item) {
                    root.maxW = Math.max(root.maxW, item.implicitWidth)
                    root.maxH = Math.max(root.maxH, item.height)
                }
            }

            // 成员尺寸实际变化（迷你模式切换等）：延迟到绑定传播完成后
            // 全量重测，避免同步重测读到旧高度导致容器偏小裁切成员
            onHeightChanged: {
                if (!item) return
                Qt.callLater(function() {
                    root.maxW = 0
                    root.maxH = 0
                    for (var k = 0; k < memberRepeater.count; k++) {
                        var obj = memberRepeater.itemAt(k)
                        if (obj && obj.item) {
                            root.maxW = Math.max(root.maxW, obj.item.implicitWidth)
                            root.maxH = Math.max(root.maxH, obj.item.height)
                        }
                    }
                })
            }

            onStatusChanged: {
                if (status === Loader.Error && source !== "") {
                    console.error("[overlay] 成员组件加载失败:", memberId, source)
                }
            }
        }
    }

    // 右侧“切换”竖条：点击切换到下一个成员（消费点击，不触发组件自动隐藏）；
    // 无成员 / 编辑堆叠组件（成员列表与增删界面）时隐藏，可在组件设置中开关
    Rectangle {
        id: switchBar
        objectName: "switchBar"
        // 显示条件（true/false）；显隐通过 opacity 渐变动画过渡，避免生硬
        readonly property bool barVisible: root.showSwitchBar && root.members.length > 0
            && !root.overlayListMode
            // 小组件隐藏（主程序交互设置）或上课时段内，切换条同步隐藏
            && !Configs.data.interactions.hide.state && !root.inClass
        // 淡出动画结束后再真正隐藏（opacity 为 0 时不可见、不渲染交互）
        visible: opacity > 0.01
        opacity: barVisible ? 1 : 0
        Behavior on opacity {
            NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
        }
        z: 5
        width: 36
        // 高度跟随容器（迷你模式下容器 56px，切换条同步变矮，保证与其它组件一致）
        height: Math.min(120, Math.max(40, root.height))
        // 圆角跟随主程序"小组件外观"设置（Corner Radius）；
        // 迷你模式等窄高场景自动收小，避免圆角超过短边
        radius: Math.min(width, height, Configs.data.preferences.widget_corner_radius)
        // 背景不透明度跟随主程序小组件外观设置
        opacity: Configs.data.preferences.opacity
        // 固定在组件内部右侧（组件宽度已为其预留空间，不被外层裁剪）
        x: root.width - 48
        y: (root.height - height) / 2
        color: Theme.isDark() ? Qt.rgba(0.14, 0.14, 0.16, 0.9) : Qt.rgba(0.98, 0.98, 1, 0.92)
        border.color: Theme.isDark() ? Qt.rgba(1, 1, 1, 0.18) : Qt.rgba(0, 0, 0, 0.12)
        border.width: 1

        Text {
            anchors.centerIn: parent
            // 竖排显示（不旋转，字头朝上）
            text: "切\n换"
            color: Theme.isDark() ? Qt.rgba(1, 1, 1, 0.85) : Qt.rgba(0, 0, 0, 0.75)
            font.pixelSize: 13
            font.weight: Font.DemiBold
        }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            // 淡出期间（opacity 动画中）禁止点击，避免误触
            enabled: switchBar.barVisible
            onClicked: root.nextMember()
        }
    }

    // 成员设置对话框：用 Dialog（主程序窗口管理，天然屏幕居中，
    // 不受堆叠组件自身位置影响；内容按钮自绘，不依赖 RinUI 遮蔽类型）
    Dialog {
        id: memberSettingsDialog
        objectName: "memberSettingsDialog"
        title: qsTr("Member Settings")
        modal: true
        width: Math.min(520, Screen.width * 0.6)
        height: 420
        property string currentMemberId: ""
        property string currentMemberTypeId: ""

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 10

            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentHeight: settingsLoader.height
                clip: true

                Loader {
                    id: settingsLoader
                    width: parent.width
                }
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: 8

                // 取消（自绘按钮）
                Rectangle {
                    width: 76
                    height: 32
                    radius: 8
                    color: cancelHovered
                        ? Qt.rgba(255, 255, 255, 0.12)
                        : "transparent"
                    border.color: Qt.rgba(255, 255, 255, 0.2)
                    border.width: 1
                    property bool cancelHovered: false

                    Text {
                        anchors.centerIn: parent
                        text: qsTr("Cancel")
                        font.pixelSize: 13
                        color: Theme.isDark() ? "#ddd" : "#333"
                    }
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        onEntered: parent.cancelHovered = true
                        onExited: parent.cancelHovered = false
                        onClicked: memberSettingsDialog.close()
                    }
                }

                // 保存（自绘按钮）
                Rectangle {
                    width: 76
                    height: 32
                    radius: 8
                    color: saveHovered
                        ? Qt.rgba(0, 120, 212, 0.9)
                        : "#0078D4"
                    property bool saveHovered: false

                    Text {
                        anchors.centerIn: parent
                        text: qsTr("Save")
                        font.pixelSize: 13
                        color: "#fff"
                    }
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        onEntered: parent.saveHovered = true
                        onExited: parent.saveHovered = false
                        onClicked: {
                            if (settingsLoader.item && settingsLoader.item.settings
                                    && root.backend) {
                                root.backend.saveMemberSettings(
                                    root.instanceId,
                                    memberSettingsDialog.currentMemberId,
                                    settingsLoader.item.settings)
                                root.applyMemberSettings(
                                    memberSettingsDialog.currentMemberId,
                                    memberSettingsDialog.currentMemberTypeId)
                            }
                            memberSettingsDialog.close()
                        }
                    }
                }
            }
        }
    }

    // ── 堆叠组件自己的居中编辑窗口（成员管理 + 框宽高 + 添加成员）─────────
    Dialog {
        id: overlayEditDialog
        title: qsTr("编辑堆叠组件")
        modal: true
        standardButtons: Dialog.Close
        width: 620
        height: 520

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 10

            Text {
                Layout.fillWidth: true
                visible: root.members.length === 0
                text: qsTr("暂无成员，点击下方“添加成员”加入组件")
                color: Theme.isDark() ? Qt.rgba(1, 1, 1, 0.55) : Qt.rgba(0, 0, 0, 0.55)
                font.pixelSize: 13
            }

            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentHeight: memberListColumn.height

                Column {
                    id: memberListColumn
                    width: parent.width
                    spacing: 8

                    Repeater {
                        model: root.members
                        delegate: RowLayout {
                            width: memberListColumn.width
                            spacing: 8

                            Text {
                                Layout.fillWidth: true
                                text: root.nameOf(modelData.typeId)
                                elide: Text.ElideRight
                                font.pixelSize: 13
                                color: Theme.isDark() ? "#eee" : "#222"
                            }
                            Button {
                                text: qsTr("设置")
                                onClicked: root.openMemberSettings(index)
                            }
                            Button {
                                text: qsTr("移除")
                                onClicked: root.removeMemberByKey(modelData.key)
                            }
                        }
                    }
                }
            }

            // 自定义组件框宽高（0 = 自适应；按实例保存）
            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: 6

                Text {
                    Layout.alignment: Qt.AlignVCenter
                    text: {
                        var w = root.frameW
                        var h = root.frameH
                        if (w > 0 && h > 0) return w + "×" + h
                        if (w > 0) return w + "×自动"
                        if (h > 0) return "自动×" + h
                        return qsTr("自适应")
                    }
                    font.pixelSize: 13
                    color: Theme.isDark() ? Qt.rgba(1, 1, 1, 0.6) : Qt.rgba(0, 0, 0, 0.6)
                }
                Button { text: qsTr("宽−"); onClicked: root.stepFrame(-10, 0) }
                Button { text: qsTr("宽+"); onClicked: root.stepFrame(10, 0) }
                Button { text: qsTr("高−"); onClicked: root.stepFrame(0, -10) }
                Button { text: qsTr("高+"); onClicked: root.stepFrame(0, 10) }
                Button { text: qsTr("自适应"); onClicked: root.resetFrame() }
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: 8

                Button {
                    text: qsTr("添加成员")
                    highlighted: true
                    onClicked: addMemberDialog.open()
                }
                Button {
                    text: qsTr("完成")
                    onClicked: overlayEditDialog.close()
                }
            }
        }
    }

    // 成员选择子对话框（候选组件列表）
    Dialog {
        id: addMemberDialog
        title: qsTr("添加成员组件")
        modal: true
        standardButtons: Dialog.Close
        width: 560
        height: 480

        property var candidates: {
            var list = []
            if (typeof WidgetsModel !== "undefined" && WidgetsModel.definitionsList) {
                var raw = WidgetsModel.definitionsList
                for (var i = 0; i < raw.length; i++) {
                    if (raw[i].id === "com.overlay") continue
                    list.push(raw[i])
                }
            }
            return list
        }
        property var selected: widgetsListView.currentIndex >= 0
            ? widgetsListView.model[widgetsListView.currentIndex] : null

        onOpened: {
            widgetsListView.currentIndex = -1
            widgetsListView.currentIndex = 0
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 10

            ListView {
                id: widgetsListView
                Layout.fillWidth: true
                Layout.fillHeight: true
                model: addMemberDialog.candidates
                clip: true

                delegate: ItemDelegate {
                    width: widgetsListView.width
                    text: modelData.name || modelData.id
                    highlighted: index === widgetsListView.currentIndex
                    onClicked: widgetsListView.currentIndex = index
                }
            }

            Button {
                Layout.alignment: Qt.AlignRight
                text: qsTr("添加")
                highlighted: true
                enabled: addMemberDialog.selected !== null
                onClicked: {
                    if (root.backend && addMemberDialog.selected) {
                        root.backend.addMember(root.instanceId, addMemberDialog.selected.id)
                    }
                    addMemberDialog.close()
                }
            }
        }
    }
}
