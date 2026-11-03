import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: card
    required property var song
    required property string batchId
    property bool busy: false
    signal details(var song)
    signal vote(string batchId, string trackId, bool liked, string reason)
    color: "#191D24"
    radius: 14
    border.color: "#2B3442"
    implicitHeight: content.implicitHeight + 36
    ColumnLayout {
        id: content
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 18 }
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Label { Layout.fillWidth: true; text: card.song.display_title || card.song.track_name || "Untitled"; color: "#F2F4F8"; font.pixelSize: 19; font.bold: true; wrapMode: Text.Wrap }
                Label { Layout.fillWidth: true; text: card.song.artists || "Unknown artist"; color: "#BAC5D5"; font.pixelSize: 14; wrapMode: Text.Wrap }
            }
            Label { visible: card.song.liked === true || card.song.liked === false; text: card.song.liked === true ? "LIKED" : "REVIEWED"; color: "#AFCFFF"; font.pixelSize: 10; font.bold: true }
        }
        Label { Layout.fillWidth: true; text: card.song.reason_preview || "A match from your listening neighborhoods"; color: "#B6C0CF"; font.pixelSize: 13; wrapMode: Text.Wrap }
        Label { visible: !!(card.song.selection_context && card.song.selection_context.discovery); text: "DISCOVERY · artist outside your liked-song context"; color: "#B3CFFF"; font.pixelSize: 11; font.bold: true; Layout.fillWidth: true; wrapMode: Text.Wrap }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            ActionButton { objectName: "yesVote_" + card.song.track_id; text: "Yes"; selected: card.song.liked === true; enabled: !card.busy; onClicked: card.vote(card.batchId, card.song.track_id, true, "") }
            ActionButton { objectName: "noVote_" + card.song.track_id; text: "No"; selected: card.song.liked === false; enabled: !card.busy; onClicked: card.vote(card.batchId, card.song.track_id, false, "") }
            Item { Layout.fillWidth: true }
            ActionButton { text: card.width < 430 ? "Why?" : "Why this match?"; onClicked: card.details(card.song) }
        }
        ComboBox {
            visible: card.song.liked === false
            Layout.fillWidth: true
            enabled: !card.busy
            model: ["Optional: what missed?", "Too slow", "Too fast", "Wrong mood", "Not my style", "Already know it", "Other"]
            currentIndex: card.song.feedback_reason ? Math.max(0, model.indexOf(card.song.feedback_reason)) : 0
            onActivated: card.vote(card.batchId, card.song.track_id, false, currentIndex > 0 ? currentText : "")
            Accessible.name: "Reason for this rating"
        }
    }
}
