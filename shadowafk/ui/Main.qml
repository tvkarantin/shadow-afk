import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Window

ApplicationWindow {
    id: root
    width: 1320
    height: 850
    minimumWidth: 820
    minimumHeight: 600
    visible: true
    title: "Shadow AFK"
    color: "#0b0e15"

    property bool trayAvailable: false
    property int page: 0
    property var session: backend.status
    property var pages: ["Обзор", "Мониторинг", "Награды", "Шаблоны", "Статистика", "Настройки", "Журнал"]
    property var subtitles: ["Контроль циклов, прогресса и состояния сессии",
        "Видимый кадр и подтверждённое состояние", "Ручной учёт прогресса заданий",
        "Образцы экранов и кнопок", "История сессий и экспорт", "Параметры наблюдения и симуляции", "События приложения"]
    property var icons: ["▦", "◎", "◈", "▧", "▥", "⚙", "≡"]
    property var screenshot: ""
    property var beforeImage: ""
    property var afterImage: ""
    property string stopKey: "Ctrl+Alt+Q"

    palette.window: "#171e29"
    palette.windowText: "#f2f5fc"
    palette.base: "#1c2635"
    palette.text: "#f2f5fc"
    palette.button: "#263245"
    palette.buttonText: "#f2f5fc"
    palette.highlight: "#9cafff"
    palette.highlightedText: "#151d33"

    onClosing: function(event) {
        event.accepted = false
        if (trayAvailable) hide()
        else Qt.quit()
    }
    Shortcut { sequence: "Ctrl+B"; onActivated: backend.pause() }
    Shortcut { sequence: root.stopKey; onActivated: backend.stop() }
    Shortcut { sequence: "W"; enabled: preview.activeFocus; onActivated: backend.simulateKey("W") }
    Shortcut { sequence: "A"; enabled: preview.activeFocus; onActivated: backend.simulateKey("A") }
    Shortcut { sequence: "S"; enabled: preview.activeFocus; onActivated: backend.simulateKey("S") }
    Shortcut { sequence: "D"; enabled: preview.activeFocus; onActivated: backend.simulateKey("D") }

    function duration(value) {
        const s = Math.floor(value)
        return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60]
            .map(n => String(n).padStart(2, "0")).join(":")
    }
    function total(field, mode) {
        return backend.history.filter(row => row.mode === mode)
            .reduce((sum, row) => sum + row[field], 0)
    }

    component Caption: Label {
        color: "#96a5b8"
        font.pixelSize: 12
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
    }
    component Heading: Caption {
        color: "#f2f5fc"
        font.pixelSize: 15
        font.bold: true
    }
    component Action: Button {
        id: actionButton
        property bool primary: false
        property bool danger: false
        property bool selected: false
        property bool nav: false
        implicitHeight: 42
        leftPadding: 14
        rightPadding: 14
        opacity: enabled ? 1 : 0.4
        hoverEnabled: true
        contentItem: Label {
            text: actionButton.text
            color: actionButton.primary ? "#151d33" : actionButton.danger ? "#ffacb1" : "#d5e0ff"
            font.bold: true
            font.pixelSize: 13
            textFormat: Text.PlainText
            horizontalAlignment: actionButton.nav ? Text.AlignLeft : Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 10
            color: actionButton.primary ? (actionButton.hovered ? "#b7c6ff" : "#9cafff")
                : actionButton.selected ? "#27365b" : actionButton.hovered ? "#334158"
                : actionButton.nav ? "transparent" : "#263245"
            border.color: actionButton.visualFocus ? "#9cafff" : "#3b4b62"
            border.width: actionButton.nav && !actionButton.visualFocus ? 0 : 1
        }
    }
    component Card: Rectangle {
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignTop
        default property alias body: bodyColumn.data
        radius: 16
        border.color: "#2a3445"
        implicitHeight: bodyColumn.implicitHeight + 44
        gradient: Gradient {
            GradientStop { position: 0; color: "#171e29" }
            GradientStop { position: 1; color: "#131922" }
        }
        ColumnLayout {
            id: bodyColumn
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 22 }
            spacing: 15
        }
    }
    component Meter: ProgressBar {
        id: meter
        Layout.fillWidth: true
        implicitHeight: 8
        padding: 0
        background: Rectangle { color: "#2d384a"; radius: 4 }
        contentItem: Item {
            Rectangle {
                width: meter.visualPosition * parent.width
                height: parent.height
                radius: 4
                color: "#9cafff"
                Behavior on width { NumberAnimation { duration: 160 } }
            }
        }
    }
    component Metric: Rectangle {
        property string label
        property string value
        property string hint
        Layout.fillWidth: true
        implicitHeight: 95
        color: "#1b2330"
        radius: 12
        border.color: "#303a4c"
        Column {
            anchors { left: parent.left; top: parent.top; margins: 13 }
            spacing: 4
            Caption { text: label }
            Heading { text: value; font.pixelSize: 23 }
            Caption { text: hint; font.pixelSize: 11 }
        }
    }
    component Field: TextField {
        Layout.fillWidth: true
        color: "#f2f5fc"
        placeholderTextColor: "#96a5b8"
        selectByMouse: true
        padding: 10
        background: Rectangle { color: "#1c2635"; radius: 8; border.color: "#39465b" }
    }
    component LogRow: RowLayout {
        property var event
        Layout.fillWidth: true
        spacing: 14
        Caption { text: event.time; font.family: "Consolas" }
        Caption { text: event.message; color: "#c9d4e6"; Layout.fillWidth: true }
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0; color: "#1a2540" }
            GradientStop { position: 0.50; color: "#0b0e15" }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 242
            color: "#10151e"
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: "#2a3445" }
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 5
                RowLayout {
                    Layout.topMargin: 11
                    Layout.leftMargin: 12
                    Layout.bottomMargin: 20
                    spacing: 11
                    Image { source: "shadow.png"; Layout.preferredWidth: 40; Layout.preferredHeight: 40; smooth: true }
                    Column {
                        Heading { text: "SHADOW AFK"; font.pixelSize: 17; font.letterSpacing: 0.6 }
                        Caption { text: "SQUADS ASSISTANT"; font.pixelSize: 10; font.letterSpacing: 1.2 }
                    }
                }
                Repeater {
                    model: root.pages
                    Action {
                        required property string modelData
                        required property int index
                        Layout.fillWidth: true
                        nav: true
                        selected: root.page === index
                        text: root.icons[index] + "    " + modelData
                        onClicked: root.page = index
                    }
                }
                Item { Layout.fillHeight: true }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.bottomMargin: 10
                    implicitHeight: 74
                    color: "#1c2431"
                    border.color: "#2c394e"
                    radius: 13
                    Column {
                        anchors.fill: parent
                        anchors.margins: 13
                        spacing: 6
                        Heading { text: "●  Локальный режим"; font.pixelSize: 12 }
                        Caption { text: "Данные хранятся на устройстве"; font.pixelSize: 11 }
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 34
            Layout.rightMargin: 34
            Layout.topMargin: 30
            spacing: 24

            RowLayout {
                Layout.fillWidth: true
                Column {
                    spacing: 7
                    Caption { text: "FORTNITE · BATTLE ROYALE · SQUADS"; color: "#9cafff"; font.bold: true; font.letterSpacing: 1.8; font.pixelSize: 11 }
                    Heading { text: root.pages[root.page]; font.pixelSize: 32 }
                    Caption { text: root.subtitles[root.page]; font.pixelSize: 14 }
                }
                Item { Layout.fillWidth: true }
                Rectangle {
                    Layout.alignment: Qt.AlignTop
                    implicitHeight: 34
                    implicitWidth: badge.implicitWidth + 24
                    color: "#293a5d"
                    border.color: "#41547e"
                    radius: 17
                    Caption {
                        id: badge
                        anchors.centerIn: parent
                        text: root.session.active && root.session.mode === "live" ? "● НАБЛЮДЕНИЕ" : "● ОФЛАЙН"
                        color: "#bfd2ff"; font.bold: true; font.pixelSize: 11
                    }
                }
            }

            ScrollView {
                id: scroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical.policy: ScrollBar.AsNeeded
                clip: true
                ColumnLayout {
                    width: scroll.availableWidth
                    spacing: 20
                    GridLayout {
                        visible: root.page === 0
                        Layout.fillWidth: true
                        columns: width >= 790 ? 2 : 1
                        columnSpacing: 20
                        rowSpacing: 20
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 530
                            Layout.alignment: Qt.AlignTop
                            spacing: 20
                            Card {
                                RowLayout {
                                    Layout.fillWidth: true
                                    Heading { text: "Текущая сессия" }
                                    Item { Layout.fillWidth: true }
                                    Caption { text: root.session.mode === "live" ? "Fortnite" : "Симулятор Squads" }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: 115
                                    radius: 13
                                    border.color: "#344969"
                                    gradient: Gradient {
                                        GradientStop { position: 0; color: "#24395b" }
                                        GradientStop { position: 1; color: "#1e293a" }
                                    }
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.margins: 17
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 6
                                            Caption { text: "СТАТУС СИСТЕМЫ"; color: "#a3b7d3"; font.letterSpacing: 1; font.bold: true; font.pixelSize: 11 }
                                            RowLayout {
                                                spacing: 11
                                                Rectangle {
                                                    implicitWidth: 10; implicitHeight: 10; radius: 5
                                                    color: root.session.paused ? "#ffd17a" : root.session.active ? "#56d7b4" : "#96a5b8"
                                                }
                                                Heading { text: root.session.title; font.pixelSize: 23; Layout.fillWidth: true }
                                            }
                                            Caption { text: root.session.hint; Layout.fillWidth: true; color: "#acbfd7" }
                                        }
                                        Rectangle {
                                            implicitWidth: 55; implicitHeight: 55; radius: 17
                                            color: "#243853"; border.color: "#4a6da0"
                                            Heading { anchors.centerIn: parent; text: "◉"; font.pixelSize: 25 }
                                        }
                                    }
                                }
                                Flow {
                                    Layout.fillWidth: true
                                    spacing: 9
                                    Action {
                                        text: "▶ Запустить симуляцию"
                                        primary: true
                                        enabled: !root.session.active
                                        onClicked: backend.start("sim", -1)
                                    }
                                    Action {
                                        text: root.session.paused ? "▶ Продолжить" : "Ⅱ Пауза"
                                        enabled: root.session.active
                                        onClicked: backend.pause()
                                    }
                                    Action { text: "■ Стоп"; danger: true; enabled: root.session.active; onClicked: backend.stop() }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 12
                                    Metric { label: "Матчей"; value: String(root.session.games); hint: "обнаружено" }
                                    Metric { label: "Циклов"; value: String(root.session.cycles); hint: "завершено" }
                                    Metric { label: "Время"; value: root.duration(root.session.seconds); hint: "текущая сессия" }
                                }
                                Caption { text: "Прогресс текущего цикла" }
                                Meter { value: (root.session.stage + 1) / backend.stages.length }
                            }
                            Card {
                                RowLayout {
                                    Layout.fillWidth: true
                                    Heading { text: "Последние события" }
                                    Item { Layout.fillWidth: true }
                                    Action { text: "Весь журнал ↗"; onClicked: root.page = 6 }
                                }
                                Caption { visible: backend.logs.length === 0; text: "Событий пока нет" }
                                Repeater {
                                    model: backend.logs.slice(0, 4)
                                    LogRow { required property var modelData; event: modelData }
                                }
                            }
                        }
                        Card {
                            Layout.preferredWidth: 310
                            RowLayout {
                                Layout.fillWidth: true
                                Heading { text: "Этапы матча" }
                                Item { Layout.fillWidth: true }
                                Caption { text: (root.session.stage + 1) + " / " + backend.stages.length }
                            }
                            Repeater {
                                model: backend.stages
                                RowLayout {
                                    required property var modelData
                                    required property int index
                                    Layout.fillWidth: true
                                    spacing: 12
                                    Rectangle {
                                        implicitWidth: 10; implicitHeight: 10; radius: 5
                                        color: index === root.session.stage ? "#9cafff" : index < root.session.stage ? "#56d7b4" : "#3e4d66"
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        Heading { text: modelData.title; font.pixelSize: 12; Layout.fillWidth: true }
                                        Caption { text: modelData.hint; font.pixelSize: 11; Layout.fillWidth: true }
                                    }
                                }
                            }
                        }
                    }

                    Card {
                        visible: root.page === 1
                        Heading { text: "Визуальный монитор" }
                        RowLayout {
                            Layout.fillWidth: true
                            ComboBox {
                                id: windowsList
                                Layout.fillWidth: true
                                model: backend.windowTitles
                                enabled: !root.session.active
                                displayText: count ? currentText : "Окно Fortnite не выбрано"
                            }
                            Action { text: "Найти окна"; enabled: backend.windowsSupported && !root.session.active; onClicked: backend.refreshWindows() }
                            Action {
                                text: "Начать наблюдение"
                                primary: true
                                enabled: backend.windowsSupported && windowsList.currentIndex >= 0 && !root.session.active
                                onClicked: backend.start("live", windowsList.currentIndex)
                            }
                        }
                        Rectangle {
                            id: preview
                            Layout.fillWidth: true
                            implicitHeight: 290
                            radius: 13
                            color: "#1a2533"
                            border.color: activeFocus ? "#9cafff" : "#344159"
                            Image { anchors.fill: parent; anchors.margins: 6; source: root.session.preview; fillMode: Image.PreserveAspectFit; cache: false }
                            Column {
                                anchors.centerIn: parent
                                visible: !root.session.preview
                                spacing: 8
                                Heading { anchors.horizontalCenter: parent.horizontalCenter; text: root.session.active ? root.session.title : "Экран не выбран"; font.pixelSize: 23 }
                                Caption {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: root.session.mode === "sim" && root.session.active
                                        ? (root.session.action || "Нажмите на экран, затем используйте WASD в матче")
                                        : "Выберите видимое окно Fortnite в Windows"
                                }
                            }
                            TapHandler { onTapped: preview.forceActiveFocus() }
                        }
                        Caption {
                            Layout.fillWidth: true
                            text: root.session.mode === "live"
                                ? "Состояние: " + root.session.state + "   ·   Совпадение: " + Math.round(root.session.confidence * 100) + "%"
                                : "Тестовые состояния Squads"
                        }
                        Caption {
                            Layout.fillWidth: true
                            text: backend.windowsSupported
                                ? "Для захвата используйте оконный режим без рамки. Кадры поступают, пока Fortnite на переднем плане."
                                : "На macOS доступны симулятор, цели, шаблоны и статистика."
                        }
                    }

                    Card {
                        visible: root.page === 2
                        Heading { text: "Цели и задания" }
                        Field { id: goalName; placeholderText: "Название задания" }
                        RowLayout {
                            Caption { text: "Выполнено" }
                            SpinBox { id: goalProgress; from: 0; to: 1000000; editable: true }
                            Caption { text: "Цель" }
                            SpinBox { id: goalTarget; from: 1; to: 1000000; value: 10; editable: true }
                            Action {
                                text: "+ Добавить задание"; primary: true; enabled: goalName.text.trim().length > 0
                                onClicked: { backend.addGoal(goalName.text, goalProgress.value, goalTarget.value); goalName.clear() }
                            }
                        }
                        Repeater {
                            model: backend.goals
                            ColumnLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                RowLayout {
                                    Heading { text: modelData.name; Layout.fillWidth: true }
                                    Caption { text: modelData.progress + " / " + modelData.target + "   ·   Δ " + modelData.delta }
                                    Action { text: "−1"; onClicked: backend.updateGoal(modelData.id, modelData.progress - 1) }
                                    Action { text: "+1"; onClicked: backend.updateGoal(modelData.id, modelData.progress + 1) }
                                    Action { text: "Удалить"; danger: true; onClicked: backend.removeGoal(modelData.id) }
                                }
                                Meter { value: Math.min(1, modelData.progress / modelData.target) }
                            }
                        }
                        Heading { text: "Сравнение скриншотов" }
                        RowLayout {
                            Layout.fillWidth: true
                            ColumnLayout {
                                Layout.fillWidth: true
                                Action { text: "Выбрать кадр до"; onClicked: { evidence.after = false; evidence.open() } }
                                Image { Layout.fillWidth: true; Layout.preferredHeight: 165; source: root.beforeImage; fillMode: Image.PreserveAspectFit }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                Action { text: "Выбрать кадр после"; onClicked: { evidence.after = true; evidence.open() } }
                                Image { Layout.fillWidth: true; Layout.preferredHeight: 165; source: root.afterImage; fillMode: Image.PreserveAspectFit }
                            }
                        }
                    }

                    Card {
                        visible: root.page === 3
                        Heading { text: "Образцы экранов и кнопок" }
                        Caption { text: "Выберите PNG и выделите характерный фрагмент состояния. Для готового обрезанного шаблона укажите ширину исходного игрового кадра."; Layout.fillWidth: true }
                        Flow {
                            Layout.fillWidth: true
                            spacing: 9
                            Action { text: "+ Открыть изображение"; primary: true; onClicked: templateFile.open() }
                            ComboBox { id: templateState; model: backend.stages; textRole: "title"; valueRole: "key" }
                            SpinBox { id: referenceWidth; from: 6; to: 16000; value: 1920; editable: true }
                            Action {
                                text: "Сохранить шаблон"
                                enabled: sample.status === Image.Ready && !root.session.active
                                onClicked: {
                                    const sx = sample.sourceSize.width / sample.paintedWidth
                                    const sy = sample.sourceSize.height / sample.paintedHeight
                                    const rect = selector.selection
                                    backend.importTemplate(root.screenshot, templateState.currentValue, referenceWidth.value,
                                        Math.round(rect.x * sx), Math.round(rect.y * sy),
                                        Math.round(rect.width * sx), Math.round(rect.height * sy))
                                }
                            }
                        }
                        Item {
                            Layout.fillWidth: true
                            Layout.preferredHeight: root.screenshot ? 260 : 0
                            visible: !!root.screenshot
                            Image {
                                id: sample
                                anchors.fill: parent
                                source: root.screenshot
                                fillMode: Image.PreserveAspectFit
                                onStatusChanged: if (status === Image.Ready) {
                                    referenceWidth.value = sourceSize.width
                                    selector.selection = Qt.rect(0, 0, 0, 0)
                                }
                                MouseArea {
                                    id: selector
                                    width: sample.paintedWidth
                                    height: sample.paintedHeight
                                    anchors.centerIn: parent
                                    property rect selection: Qt.rect(0, 0, 0, 0)
                                    property point origin
                                    onPressed: function(event) {
                                        origin = Qt.point(event.x, event.y)
                                        selection = Qt.rect(event.x, event.y, 0, 0)
                                    }
                                    onPositionChanged: function(event) {
                                        if (!pressed) return
                                        const x = Math.max(0, Math.min(width, event.x))
                                        const y = Math.max(0, Math.min(height, event.y))
                                        selection = Qt.rect(Math.min(x, origin.x), Math.min(y, origin.y),
                                            Math.abs(x - origin.x), Math.abs(y - origin.y))
                                    }
                                    Rectangle {
                                        x: selector.selection.x; y: selector.selection.y
                                        width: selector.selection.width; height: selector.selection.height
                                        color: "#339cafff"; border.color: "#9cafff"
                                    }
                                }
                            }
                        }
                        Repeater {
                            model: backend.templates
                            RowLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                Image { source: modelData.url; Layout.preferredWidth: 130; Layout.preferredHeight: 65; fillMode: Image.PreserveAspectFit }
                                Caption { text: modelData.name + " · " + modelData.state; Layout.fillWidth: true }
                                Action { text: "Удалить"; danger: true; visible: !modelData.builtin; enabled: !root.session.active; onClicked: backend.removeTemplate(modelData.id) }
                            }
                        }
                    }

                    Card {
                        visible: root.page === 4
                        RowLayout {
                            Layout.fillWidth: true
                            Heading { text: "Общая статистика" }
                            Item { Layout.fillWidth: true }
                            ComboBox { id: statsMode; model: ["Fortnite", "Симулятор"] }
                            Action { text: "↓ Экспорт CSV"; onClicked: csvDialog.open() }
                        }
                        property string mode: statsMode.currentIndex === 0 ? "live" : "sim"
                        id: statistics
                        RowLayout {
                            Layout.fillWidth: true
                            Metric { label: "Матчей"; value: String(root.total("games", statistics.mode)) }
                            Metric { label: "Завершено"; value: String(root.total("cycles", statistics.mode)) }
                            Metric { label: "Время"; value: root.duration(root.total("seconds", statistics.mode)) }
                        }
                        Caption {
                            Layout.fillWidth: true
                            text: "Средний матч: " + root.duration(root.total("match_seconds", statistics.mode)
                                / Math.max(1, root.total("cycles", statistics.mode)))
                                + "   ·   Наблюдение: " + root.duration(root.total("spectating_seconds", statistics.mode))
                                + "   ·   Ошибки: " + root.total("errors", statistics.mode)
                        }
                        Repeater {
                            model: backend.history.filter(row => row.mode === statistics.mode)
                            Caption {
                                required property var modelData
                                Layout.fillWidth: true
                                text: modelData.date.replace("T", " ") + "   ·   " + modelData.games + " матчей   ·   "
                                    + modelData.cycles + " завершено   ·   " + root.duration(modelData.seconds) + "   ·   " + modelData.result
                            }
                        }
                    }

                    Card {
                        visible: root.page === 5
                        Heading { text: "Симулятор и распознавание" }
                        RowLayout {
                            Layout.fillWidth: true
                            Caption { text: "Скорость симуляции" }
                            Slider { id: speed; Layout.fillWidth: true; from: 1; to: 5; stepSize: 1; snapMode: Slider.SnapAlways; value: backend.settings.speed }
                            Caption { text: speed.value + "×" }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Caption { text: "Порог распознавания" }
                            Slider { id: threshold; Layout.fillWidth: true; from: 50; to: 99; stepSize: 1; snapMode: Slider.SnapAlways; value: backend.settings.threshold }
                            Caption { text: (threshold.value / 100).toFixed(2) }
                        }
                        CheckBox { id: repeat; text: "Повторять тестовые циклы"; checked: backend.settings.repeat; palette.windowText: "#f2f5fc" }
                        Heading { text: "Горячие клавиши в окне" }
                        Caption { text: "Ctrl+B   ·   Пауза / продолжить" }
                        RowLayout {
                            Caption { text: "Стоп" }
                            ComboBox {
                                id: stopCombo
                                model: ["Ctrl+Alt+Q", "Ctrl+Shift+Q", "Ctrl+C"]
                                currentIndex: model.indexOf(backend.settings.stopKey)
                            }
                        }
                        Action {
                            text: "Сохранить настройки"; primary: true
                            onClicked: backend.saveSettings(speed.value, threshold.value, repeat.checked, stopCombo.currentText)
                        }
                        Action { text: "Удалить локальную статистику"; danger: true; enabled: !root.session.active; onClicked: confirmReset.open() }
                    }

                    Card {
                        visible: root.page === 6
                        RowLayout {
                            Layout.fillWidth: true
                            Heading { text: "Журнал событий" }
                            Item { Layout.fillWidth: true }
                            Action { text: "Очистить журнал"; onClicked: backend.clearLogs() }
                        }
                        Caption { visible: backend.logs.length === 0; text: "Событий пока нет" }
                        Repeater {
                            model: backend.logs
                            LogRow { required property var modelData; event: modelData }
                        }
                    }
                    Item { implicitHeight: 22 }
                }
            }
        }
    }

    Component.onCompleted: root.stopKey = backend.settings.stopKey
    FileDialog {
        id: templateFile
        title: "Открыть шаблон"
        nameFilters: ["Изображения (*.png *.jpg *.jpeg *.webp)"]
        onAccepted: root.screenshot = selectedFile
    }
    FileDialog {
        id: evidence
        property bool after: false
        title: "Открыть скриншот"
        nameFilters: ["Изображения (*.png *.jpg *.jpeg *.webp)"]
        onAccepted: if (after) root.afterImage = selectedFile; else root.beforeImage = selectedFile
    }
    FileDialog {
        id: csvDialog
        title: "Экспортировать статистику"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "csv"
        nameFilters: ["CSV (*.csv)"]
        onAccepted: backend.exportHistory(selectedFile)
    }
    Dialog {
        id: confirmReset
        anchors.centerIn: parent
        title: "Удалить всю историю сессий?"
        standardButtons: Dialog.Yes | Dialog.No
        onAccepted: backend.reset()
    }
    Popup {
        id: toast
        parent: Overlay.overlay
        x: parent.width - width - 20
        y: parent.height - height - 18
        padding: 12
        background: Rectangle { color: "#243649"; border.color: "#4b6885"; radius: 12 }
        contentItem: Caption { id: toastText; color: "#e4eeff"; wrapMode: Text.NoWrap }
    }
    Timer { id: toastTimer; interval: 3500; onTriggered: toast.close() }
    Connections {
        target: backend
        function onNotify(message) {
            toastText.text = message
            toast.open()
            toastTimer.restart()
        }
        function onSettingsChanged() { root.stopKey = backend.settings.stopKey }
    }
}
