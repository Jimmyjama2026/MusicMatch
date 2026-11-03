import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: panel
    property var comparison: ({})
    property var lastComparison: ({})
    property var stats: ({})
    property bool busy: false
    property bool expanded: false
    readonly property bool hasPair: !!(comparison && comparison.id && comparison.a && comparison.b && comparison.anchor)
    signal choose(string comparisonId, string choice)
    signal undo(string comparisonId)
    signal resetRequested()
    color: "#191D24"
    radius: 10
    implicitHeight: contents.implicitHeight + 20
    ColumnLayout {
        id: contents
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 10 }
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            ActionButton { objectName: "comparisonToggle"; text: (panel.expanded ? "− " : "+ ") + "Compare two songs (optional)"; Layout.fillWidth: true; enabled: !panel.busy; onClicked: panel.expanded = !panel.expanded }
            ActionButton { objectName: "comparisonUndo"; text: "Undo"; visible: !!(panel.lastComparison && panel.lastComparison.id); enabled: !panel.busy; onClicked: panel.undo(String(panel.lastComparison.id)) }
        }
        ColumnLayout {
            Layout.fillWidth: true
            visible: panel.expanded
            spacing: 8
            Label { Layout.fillWidth: true; text: panel.hasPair ? "Which fits “" + (panel.comparison.anchor.track_name || "this neighborhood") + "” better?" : "Generate suggestions to find a pair from the same neighborhood."; color: "#CFDCEE"; wrapMode: Text.Wrap; font.pixelSize: 12 }
            RowLayout {
                Layout.fillWidth: true
                visible: panel.hasPair
                Repeater {
                    model: panel.hasPair ? [panel.comparison.a, panel.comparison.b] : []
                    ActionButton {
                        required property var modelData
                        required property int index
                        objectName: index === 0 ? "comparisonA" : "comparisonB"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: 58
                        enabled: !panel.busy
                        Accessible.name: (index === 0 ? "Choose A: " : "Choose B: ") + modelData.track_name + " by " + modelData.artists
                        contentItem: Label { text: (index === 0 ? "A · " : "B · ") + modelData.track_name + "\n" + modelData.artists; color: "#E7EEFA"; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter; font.pixelSize: 12 }
                        onClicked: panel.choose(String(panel.comparison.id), index === 0 ? "a" : "b")
                    }
                }
            }
            Flow {
                Layout.fillWidth: true
                spacing: 6
                ActionButton { objectName: "comparisonEqual"; text: "About equal"; visible: panel.hasPair; enabled: !panel.busy; onClicked: panel.choose(String(panel.comparison.id), "equal") }
                ActionButton { objectName: "comparisonSkip"; text: "Skip"; visible: panel.hasPair; enabled: !panel.busy; onClicked: panel.choose(String(panel.comparison.id), "skip") }
                ActionButton { objectName: "comparisonReset"; text: "Reset comparisons"; visible: Number(panel.stats.count || 0) > 0; enabled: !panel.busy; onClicked: panel.resetRequested() }
            }
            Label { Layout.fillWidth: true; text: "Choose only when you know both songs. The other song is not marked as disliked."; color: "#AAB8CC"; wrapMode: Text.Wrap; font.pixelSize: 11 }
        }
    }
}
