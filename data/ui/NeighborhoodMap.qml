import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: map
    property var viewData: ({})
    property string focusedTrackId: ""
    property var selectedPoint: null
    readonly property var points: viewData.points || []
    readonly property bool hasPoints: viewData.available !== false && points.length > 0
    property int plotHeight: 250
    property bool compactView: false
    color: "#151922"
    border.color: "#344154"
    radius: 12
    implicitHeight: content.implicitHeight + 28
    function groupColor(group) {
        var colors = ["#8CB9FA", "#B2CCF0", "#709CE0", "#D0DDF3", "#A1ACD9", "#84B7CF"];
        var value = String(group || "0"), hash = 0;
        for (var i = 0; i < value.length; i++) hash = (hash * 31 + value.charCodeAt(i)) >>> 0;
        return colors[hash % colors.length];
    }
    function groupLabel(group) {
        var groups = viewData.groups || [];
        for (var i = 0; i < groups.length; i++) if (String(groups[i].id) === String(group)) return String(groups[i].label || groups[i].id);
        return "Neighborhood " + String(group === undefined ? "unassigned" : group);
    }
    onViewDataChanged: selectedPoint = null
    ColumnLayout {
        id: content
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 14 }
        spacing: 10
        Flow {
            Layout.fillWidth: true
            spacing: 12
            Label { text: "● Liked anchors"; color: "#B8D3FA"; font.pixelSize: 11 }
            Label { text: "○ Positive feedback"; color: "#B8D3FA"; font.pixelSize: 11 }
            Row {
                spacing: 5
                Rectangle { width: 7; height: 7; rotation: 45; color: "#F1F5FC"; anchors.verticalCenter: parent.verticalCenter }
                Label { text: "Suggestions"; color: "#F1F5FC"; font.pixelSize: 11 }
            }
        }
        Rectangle {
            id: plot
            objectName: "neighborhoodPlot"
            Layout.fillWidth: true
            Layout.preferredHeight: map.plotHeight
            color: "#11151C"
            radius: 8
            border.color: "#2B3645"
            clip: true
            Item {
                id: plotArea
                anchors.centerIn: parent
                width: Math.min(plot.width, plot.height)
                height: width
            Canvas {
                anchors.fill: parent
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
                onPaint: {
                    var ctx = getContext("2d"); ctx.reset(); ctx.strokeStyle = "#202B3A"; ctx.lineWidth = 1;
                    for (var x = 1; x < 6; x++) { ctx.beginPath(); ctx.moveTo(width * x / 6, 0); ctx.lineTo(width * x / 6, height); ctx.stroke(); }
                    for (var y = 1; y < 4; y++) { ctx.beginPath(); ctx.moveTo(0, height * y / 4); ctx.lineTo(width, height * y / 4); ctx.stroke(); }
                }
            }
            Repeater {
                model: map.hasPoints ? map.points : []
                delegate: AbstractButton {
                    id: point
                    required property var modelData
                    required property int index
                    objectName: "neighborhoodPoint_" + index
                    property bool suggestion: modelData.kind === "suggestion"
                    property bool highlighted: activeFocus || map.focusedTrackId === modelData.track_id || (map.selectedPoint && map.selectedPoint.track_id === modelData.track_id)
                    width: 30
                    height: 30
                    x: 16 + Math.max(0, Math.min(1, Number(modelData.x))) * Math.max(0, plotArea.width - 62)
                    y: 16 + (1 - Math.max(0, Math.min(1, Number(modelData.y)))) * Math.max(0, plotArea.height - 62)
                    hoverEnabled: true
                    activeFocusOnTab: true
                    Accessible.name: String(modelData.track_name || "Song") + " by " + String(modelData.artists || "Unknown artist") + ", " + (suggestion ? "suggestion" : modelData.kind === "positive" ? "positive feedback" : "liked anchor") + ", " + map.groupLabel(modelData.group)
                    Accessible.description: "Approximate position in a two-dimensional feature projection. Activate to show the song label."
                    background: Rectangle {
                        anchors.centerIn: parent
                        width: point.highlighted ? 20 : 14
                        height: width
                        radius: point.suggestion ? 3 : width / 2
                        rotation: point.suggestion ? 45 : 0
                        color: point.suggestion ? "#F1F5FC" : point.modelData.kind === "positive" ? "#11151C" : map.groupColor(point.modelData.group)
                        border.width: point.highlighted ? 3 : 2
                        border.color: point.highlighted ? "#FFFFFF" : map.groupColor(point.modelData.group)
                    }
                    ToolTip.visible: hovered
                    ToolTip.text: Accessible.name
                    onClicked: map.selectedPoint = modelData
                    Keys.onReturnPressed: function(event) { map.selectedPoint = modelData; event.accepted = true; }
                    Keys.onEnterPressed: function(event) { map.selectedPoint = modelData; event.accepted = true; }
                }
            }
            }
            Label {
                anchors { centerIn: parent; left: parent.left; right: parent.right; margins: 22 }
                visible: !map.hasPoints
                text: map.viewData.message || "Add songs with local audio features to see your neighborhoods."
                color: "#B6C0CF"
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
            }
        }
        Label {
            objectName: "mapSelectionLabel"
            Layout.fillWidth: true
            text: map.selectedPoint ? String(map.selectedPoint.track_name) + " · " + String(map.selectedPoint.artists) + " · " + map.groupLabel(map.selectedPoint.group) + (map.selectedPoint.discovery ? " · Discovery" : "") : "Select a point to see its song. Tab and Enter also work."
            color: "#D7E6FC"
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
        Label {
            objectName: "projectionNote"
            Layout.fillWidth: true
            text: map.compactView ? "Approximate 2D view; hidden dimensions still affect similarity. Full map and projection notes are in Neighborhoods." : map.viewData.projection_note || "Approximate 2D projection. Recommendation distance uses the full feature vector; visual closeness here can be misleading."
            color: "#ADBBD0"
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
        Label { Layout.fillWidth: true; visible: !map.compactView && map.hasPoints && !!map.viewData.message; text: String(map.viewData.message || ""); color: "#ADBBD0"; font.pixelSize: 11; wrapMode: Text.Wrap }
        Flow {
            visible: !map.compactView
            Layout.fillWidth: true
            spacing: 10
            Repeater {
                model: (map.viewData.groups || []).slice(0, 12)
                Label { required property var modelData; text: "● " + String(modelData.label || modelData.id) + " (" + String(modelData.anchor_count || 0) + ")"; color: map.groupColor(modelData.id); font.pixelSize: 11 }
            }
        }
        Label { Layout.fillWidth: true; visible: !map.compactView && (map.viewData.groups || []).length > 12; text: "Select a point to identify its neighborhood; the legend shows the first 12 groups."; color: "#ADBBD0"; font.pixelSize: 11; wrapMode: Text.Wrap }
    }
}
