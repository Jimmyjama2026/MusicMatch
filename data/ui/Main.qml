import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Fusion
import QtQuick.Layouts

ApplicationWindow {
    id: window
    objectName: "musicmatchWindow"
    visible: true
    width: 1200
    height: 840
    minimumWidth: 560
    minimumHeight: 540
    title: "MusicMatch"
    color: "#111318"
    font.family: "Segoe UI"
    palette.window: "#111318"
    palette.windowText: "#F2F4F8"
    palette.base: "#202631"
    palette.text: "#F2F4F8"
    palette.button: "#242B36"
    palette.buttonText: "#F2F4F8"
    palette.highlight: "#1D4E9E"
    palette.highlightedText: "#FFFFFF"
    property int section: 0
    property bool compact: width < 1000
    property bool narrow: width < 780
    property bool reducedMotion: false
    property var detailSong: ({})
    function isFavorite(id) { return music.state.favorites.some(function(s) { return s.track_id === id; }); }
    function showDetails(song) { detailSong = song; technicalText.visible = false; steeringPicker.currentIndex = 0; whyDrawer.open(); }
    function historySongs() { return music.historyBatch.recommendations || []; }
    function friendlyDate(value) { var date = new Date(value); return isNaN(date.getTime()) ? String(value || "Saved session") : date.toLocaleString(Qt.locale(), "MMM d, yyyy · h:mm ap"); }
    Shortcut { sequence: "Ctrl+K"; onActivated: { window.section = 0; titleInput.forceActiveFocus(); } }
    Shortcut { sequence: "Escape"; onActivated: whyDrawer.close() }
    Connections {
        target: music
        function onProfileChanged() {
            titleInput.text = ""; artistInput.text = ""; likedFilter.text = ""; freshBox.checked = false;
            historyFilter.currentIndex = 0; whyDrawer.close(); contextDialog.close(); window.detailSong = ({});
            window.section = 0;
            steeringPicker.currentIndex = 0; comparisonPanel.expanded = false; resetComparisonsDialog.close();
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: window.narrow ? 88 : window.compact ? 150 : 205
            color: "#151922"
            ColumnLayout {
                anchors { fill: parent; margins: window.narrow ? 8 : 18 }
                spacing: window.height < 650 ? 8 : 12
                Label { text: window.narrow ? "MM" : "MUSICMATCH"; color: "#F4F6FA"; font.pixelSize: window.compact ? 15 : 19; font.bold: true; Layout.topMargin: 10; Layout.bottomMargin: window.height < 650 ? 12 : 22 }
                Repeater {
                    model: ["Discover", "Liked songs", "History", "Neighborhoods"]
                    ActionButton {
                        required property string modelData
                        required property int index
                        Layout.fillWidth: true
                        objectName: "navigation_" + index
                        text: window.narrow ? ["Find", "Liked", "History", "Map"][index] : modelData
                        Accessible.name: modelData
                        selected: window.section === index
                        onClicked: { window.section = index; if (index === 2) music.loadHistory(historyFilter.currentText.toLowerCase(), 0); }
                    }
                }
                Item { Layout.fillHeight: true }
                Label { text: window.narrow ? "PROFILE" : "YOUR SPACE"; color: "#A8B8CE"; font.pixelSize: 10; font.bold: true }
                ComboBox {
                    id: profilePicker
                    Layout.fillWidth: true
                    model: music.state.profiles
                    textRole: "name"
                    valueRole: "id"
                    enabled: !music.busy && music.initialized
                    currentIndex: Math.max(0, music.state.profiles.findIndex(function(p) { return p.id === music.state.profile_id; }))
                    onActivated: music.switchProfile(currentValue)
                    Accessible.name: "Listening profile"
                }
                ActionButton { objectName: "resetTestButton"; Layout.fillWidth: true; visible: music.state.profile_id === "test"; enabled: !music.busy; text: "Reset Test"; onClicked: resetDialog.open() }
                CheckBox { text: window.narrow ? "Still" : "Less motion"; checked: window.reducedMotion; onToggled: window.reducedMotion = checked; font.pixelSize: 11; Accessible.name: "Reduce interface motion" }
                Label { text: window.narrow ? "LOCAL" : "LOCAL LIBRARY"; color: "#A8B8CE"; font.pixelSize: 10; Layout.topMargin: 12 }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.fillHeight: true
            Layout.margins: window.compact ? 18 : 30
            spacing: 14
            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { text: ["Find your next favorite", "Your liked songs", "Your discovery history", "Your taste neighborhoods"][window.section]; color: "#F2F4F8"; font.pixelSize: window.compact ? 23 : 29; font.bold: true }
                    Label { Layout.fillWidth: true; text: music.state.profile_name + " · " + (music.state.favorites || []).length + " liked songs"; color: "#B6C0CF"; font.pixelSize: 13 }
                }
                BusyIndicator { running: music.busy; visible: running; Layout.preferredWidth: 30; Layout.preferredHeight: 30 }
            }
            ProgressBar { Layout.fillWidth: true; visible: music.busy; indeterminate: true; implicitHeight: 3 }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: errorRow.implicitHeight + 20
                visible: music.error.length > 0
                color: "#452B32"
                radius: 8
                RowLayout {
                    id: errorRow
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 10 }
                    Label { Layout.fillWidth: true; text: music.error; color: "#FFE1E5"; wrapMode: Text.Wrap }
                    ActionButton { text: "Retry loading"; visible: !music.initialized; enabled: !music.busy; onClicked: music.initialize() }
                    ActionButton { text: "Dismiss"; onClicked: music.clearError() }
                }
            }
            StackLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.maximumWidth: parent.width
                Layout.fillHeight: true
                currentIndex: window.section
                ColumnLayout {
                    spacing: 12
                    RowLayout {
                        Layout.fillWidth: true
                        MusicSearchField { id: titleInput; objectName: "titleInput"; Layout.fillWidth: true; Layout.minimumWidth: 40; placeholderText: "Search song title"; enabled: !music.busy && music.initialized; onAccepted: music.search(text, artistInput.text); Accessible.name: "Song title" }
                        MusicSearchField { id: artistInput; objectName: "artistInput"; Layout.preferredWidth: window.narrow ? 115 : Math.max(130, window.width * 0.16); placeholderText: window.narrow ? "Artist" : "Artist (optional)"; enabled: !music.busy && music.initialized; onAccepted: music.search(titleInput.text, text); Accessible.name: "Artist" }
                        ActionButton { objectName: "searchButton"; text: "Search"; enabled: !music.busy && music.initialized; onClicked: music.search(titleInput.text, artistInput.text) }
                    }
                    ListView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(240, contentHeight)
                        visible: count > 0
                        model: music.searchResults
                        clip: true
                        spacing: 6
                        reuseItems: true
                        ScrollBar.vertical: ScrollBar {}
                        delegate: SongRow {
                            required property var modelData
                            width: ListView.view.width
                            song: modelData
                            actionText: window.isFavorite(song.track_id) ? "Added" : "Add"
                            actionEnabled: !music.busy && !window.isFavorite(song.track_id)
                            onAction: music.addFavorite(song.track_id)
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        ActionButton { objectName: "suggestButton"; text: "Suggest songs"; primary: true; enabled: !music.busy && music.state.favorites.length > 0; onClicked: music.recommend(freshBox.checked) }
                        CheckBox { id: freshBox; text: "Fresh only"; enabled: !music.busy; Accessible.description: "Skip songs already shown" }
                    }
                    Label { Layout.fillWidth: true; text: music.state.message || music.state.model_status || ""; color: "#B6C0CF"; font.pixelSize: 12; wrapMode: Text.Wrap }
                    ComparisonPanel {
                        id: comparisonPanel
                        objectName: "comparisonPanel"
                        Layout.fillWidth: true
                        comparison: music.state.comparison || ({})
                        lastComparison: music.state.last_comparison || ({})
                        stats: music.state.comparison_stats || ({})
                        busy: music.busy
                        visible: hasPair || Number(stats.count || 0) > 0 || !!lastComparison.id
                        onChoose: function(id, choice) { music.chooseComparison(id, choice); }
                        onUndo: function(id) { music.undoComparison(id); }
                        onResetRequested: resetComparisonsDialog.open()
                    }
                    ListView {
                        id: discoveries
                        objectName: "discoveries"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: music.recommendationModel
                        spacing: 12
                        clip: true
                        reuseItems: true
                        ScrollBar.vertical: ScrollBar {}
                        delegate: MatchCard {
                            required property var modelData
                            width: ListView.view.width
                            song: modelData
                            batchId: String(music.state.batch_id || "")
                            busy: music.busy
                            onDetails: function(song) { window.showDetails(song); }
                            onVote: function(batchId, trackId, liked, reason) { music.rate(batchId, trackId, liked, reason); }
                        }
                        Label { anchors.centerIn: parent; visible: discoveries.count === 0; width: parent.width - 30; horizontalAlignment: Text.AlignHCenter; text: music.state.favorites.length ? "Ready when you are. Suggest songs to explore your taste." : "Add a few songs you love to start discovering."; color: "#B6C0CF"; wrapMode: Text.Wrap; font.pixelSize: 16 }
                    }
                }
                ColumnLayout {
                    spacing: 12
                    MusicSearchField { id: likedFilter; Layout.fillWidth: true; placeholderText: "Filter liked songs or artists"; Accessible.name: "Filter liked songs" }
                    ListView {
                        id: likedList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: music.state.favorites.filter(function(s) { return ((s.track_name || "") + " " + (s.artists || "")).toLowerCase().includes(likedFilter.text.toLowerCase()); })
                        spacing: 8
                        clip: true
                        reuseItems: true
                        ScrollBar.vertical: ScrollBar {}
                        delegate: SongRow { required property var modelData; width: ListView.view.width; song: modelData; actionText: "Remove"; actionEnabled: !music.busy; onAction: music.removeFavorite(song.track_id) }
                        Label { anchors.centerIn: parent; visible: likedList.count === 0; text: "No liked songs match this view."; color: "#B6C0CF" }
                    }
                }
                ColumnLayout {
                    RowLayout {
                        Layout.fillWidth: true
                        visible: !!music.historyBatch.batch_id
                        Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: window.friendlyDate(music.historyBatch.created_at) + " · " + (music.historyBatch.favorites || []).length + " original likes"; color: "#B6C0CF"; wrapMode: Text.Wrap }
                        ActionButton { text: "Original likes"; onClicked: contextDialog.open() }
                    }
                    RowLayout {
                        ComboBox { id: historyFilter; model: ["All", "Yes", "No", "Unrated"]; enabled: !music.busy; onActivated: music.loadHistory(currentText.toLowerCase(), 0); Accessible.name: "Filter history by rating" }
                        Item { Layout.fillWidth: true }
                        ActionButton { text: "Newer"; enabled: !music.busy && music.historyOffset > 0; onClicked: music.loadHistory(historyFilter.currentText.toLowerCase(), Math.max(0, music.historyOffset - 30)) }
                        ActionButton { text: "Older"; enabled: !music.busy && music.historyHasOlder; onClicked: music.loadHistory(historyFilter.currentText.toLowerCase(), music.historyOffset + 30) }
                    }
                    SplitView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        orientation: Qt.Horizontal
                        ListView {
                            id: historyList
                            SplitView.preferredWidth: window.narrow ? 120 : window.compact ? 165 : 230
                            SplitView.minimumWidth: 100
                            model: music.historyRows
                            spacing: 8
                            clip: true
                            reuseItems: true
                            ScrollBar.vertical: ScrollBar {}
                            delegate: ItemDelegate {
                                required property var modelData
                                width: ListView.view.width
                                height: 76
                                text: window.friendlyDate(modelData.created_at) + "\n" + String(modelData.count || "") + " suggestions"
                                enabled: !music.busy
                                highlighted: String(modelData.batch_id) === String(music.historyBatch.batch_id)
                                onClicked: music.openHistory(String(modelData.batch_id))
                            }
                        }
                        ListView {
                            id: oldSongs
                            SplitView.fillWidth: true
                            model: music.historyRecommendationModel
                            spacing: 10
                            clip: true
                            reuseItems: true
                            ScrollBar.vertical: ScrollBar {}
                            delegate: MatchCard { required property var modelData; width: ListView.view.width; song: modelData; batchId: String(music.historyBatch.batch_id || ""); busy: music.busy; onDetails: function(song) { window.showDetails(song); }; onVote: function(batchId, trackId, liked, reason) { music.rate(batchId, trackId, liked, reason); } }
                            Label { anchors.centerIn: parent; visible: oldSongs.count === 0; width: parent.width - 20; horizontalAlignment: Text.AlignHCenter; text: "Choose a saved session to revisit its matches."; color: "#B6C0CF"; wrapMode: Text.Wrap }
                        }
                    }
                }
                ScrollView {
                    id: overviewScroll
                    clip: true
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: overviewScroll.availableWidth
                        spacing: 14
                        Label { Layout.fillWidth: true; text: "Explore the separate parts of your taste. Suggestions can belong near one neighborhood without resembling every song you like."; color: "#B6C0CF"; wrapMode: Text.Wrap }
                        NeighborhoodMap {
                            objectName: "overviewNeighborhoodMap"
                            Layout.fillWidth: true
                            viewData: music.state.neighborhood_view || ({})
                            plotHeight: window.narrow ? 280 : 380
                        }
                    }
                }
            }
        }
    }
    Drawer {
        id: whyDrawer
        objectName: "whyDrawer"
        edge: Qt.RightEdge
        width: Math.min(450, window.width - 40)
        height: window.height
        modal: true
        enter: Transition { NumberAnimation { property: "position"; duration: window.reducedMotion ? 0 : 140 } }
        exit: Transition { NumberAnimation { property: "position"; duration: window.reducedMotion ? 0 : 100 } }
        background: Rectangle { color: "#191D24"; border.color: "#394454" }
        ColumnLayout {
            anchors { fill: parent; margins: 24 }
            spacing: 16
            Label { text: "Why this match?"; color: "#F2F4F8"; font.pixelSize: 23; font.bold: true }
            Label { Layout.fillWidth: true; text: window.detailSong.track_name || ""; color: "#D4E4FF"; font.pixelSize: 19; wrapMode: Text.Wrap }
            ScrollView {
                id: detailScroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: availableWidth
                clip: true
                ColumnLayout {
                    width: detailScroll.availableWidth
                    spacing: 14
                    Label { Layout.fillWidth: true; text: window.detailSong.reason_preview || "Saved match explanation"; color: "#D3DCEB"; wrapMode: Text.Wrap }
                    Label {
                        Layout.fillWidth: true
                        visible: !!window.detailSong.steering_context
                        text: {
                            var context = window.detailSong.steering_context || {};
                            var labels = {same: "Same feel", slower: "Slightly slower", faster: "Slightly faster", energetic: "More energetic", less_artist: "Less artist influence"};
                            var label = "Saved request: " + (labels[context.option] || context.option || "Same feel");
                            if (context.applied === false) return label + " · unavailable with these features";
                            if (context.target) return label + " · target " + (context.target.feature === "tempo" ? Number(context.target.target).toFixed(1) + " BPM" : (Number(context.target.target) * 100).toFixed(0) + "% energy");
                            return label;
                        }
                        color: "#AFCFFF"; wrapMode: Text.Wrap; font.pixelSize: 12
                    }
                    Label { Layout.fillWidth: true; visible: !!window.detailSong.pairwise_context && Number(window.detailSong.pairwise_context.active_count || 0) > 0; text: "Your saved A/B comparisons contributed a small adjustment in this neighborhood."; color: "#B6C0CF"; wrapMode: Text.Wrap; font.pixelSize: 12 }
                    NeighborhoodMap { objectName: "detailNeighborhoodMap"; Layout.fillWidth: true; viewData: window.detailSong.neighborhood_visual || ({message: "Neighborhood positions were not saved for this match."}); focusedTrackId: String(window.detailSong.track_id || ""); plotHeight: 160; compactView: true }
                    Label { Layout.fillWidth: true; text: window.detailSong.matched_anchor ? "Compared with " + String(window.detailSong.matched_anchor.track_name) + " · " + String(window.detailSong.matched_anchor.artists) : "Feature comparison"; color: "#D4E4FF"; font.bold: true; wrapMode: Text.Wrap }
                    MatchTable { objectName: "matchComparisonTable"; Layout.fillWidth: true; rows: window.detailSong.match_table || [] }
                    ActionButton { text: technicalText.visible ? "Hide technical details" : "Technical details"; onClicked: technicalText.visible = !technicalText.visible }
                    TextArea { id: technicalText; Layout.fillWidth: true; visible: false; text: window.detailSong.reason || "No additional explanation was saved for this song."; readOnly: true; wrapMode: TextEdit.Wrap; color: "#D3DCEB"; background: null; selectByMouse: true }
                }
            }
            Label { text: "Steer this request only"; color: "#B6C0CF"; font.pixelSize: 12 }
            ComboBox { id: steeringPicker; objectName: "steeringPicker"; Layout.fillWidth: true; enabled: !music.busy; model: ["Same feel", "Slightly slower", "Slightly faster", "More energetic", "Less artist influence"]; Accessible.name: "Steer more like this" }
            ActionButton { objectName: "steeredMoreButton"; text: "More like this"; primary: true; enabled: !music.busy && !!window.detailSong.track_id; onClicked: { music.steerMoreLikeThis(window.detailSong.track_id, freshBox.checked, ["same", "slower", "faster", "energetic", "less_artist"][steeringPicker.currentIndex]); window.section = 0; whyDrawer.close(); } }
            ActionButton { text: "Close"; onClicked: whyDrawer.close() }
        }
    }
    Dialog {
        id: resetComparisonsDialog
        objectName: "resetComparisonsDialog"
        title: "Reset comparison learning?"
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Yes | Dialog.Cancel
        Label { text: "Clear comparison choices for this profile?\nLiked songs and Yes/No ratings stay saved."; color: "#F2F4F8" }
        onAccepted: music.resetComparisons()
    }
    Dialog {
        id: contextDialog
        title: "Original liked-song context"
        anchors.centerIn: parent
        modal: true
        width: Math.min(550, window.width - 40)
        height: Math.min(500, window.height - 60)
        standardButtons: Dialog.Close
        ColumnLayout {
            anchors.fill: parent
            Label { Layout.fillWidth: true; text: "These songs shaped the saved session. Your current liked list is unchanged."; color: "#B6C0CF"; wrapMode: Text.Wrap }
            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                model: music.historyBatch.favorites || []
                clip: true
                reuseItems: true
                spacing: 8
                ScrollBar.vertical: ScrollBar {}
                delegate: SongRow { required property var modelData; width: ListView.view.width; song: modelData; actionText: "Saved"; actionEnabled: false }
            }
        }
    }
    Dialog {
        id: resetDialog
        objectName: "resetDialog"
        title: "Reset Test profile?"
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Yes | Dialog.Cancel
        Label { text: "Clear Test favorites, suggestions and ratings?\nYour Personal profile stays saved."; color: "#F2F4F8" }
        onAccepted: music.resetTest()
    }
}
