pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

Item {
  id: root

  property var shell: null
  property var manifest: null
  property bool opened: false
  property bool directoryReady: false
  property string pendingSaveText: ""
  property string statusLine: "CONFIGURATION SYNCHRONIZED"
  property string backdropPreviewPath: ""
  property string backdropPreviewError: ""
  property bool backdropPreviewDirty: false
  property bool backdropPreviewHandled: false
  property bool backdropPickerSelected: false
  property bool backdropPreviewPending: false
  property var defaults: ({
    schemaVersion: 1,
    species: { neon_tetra: 10, clownfish: 4, angelfish: 3, discus: 3, butterflyfish: 2, royal_tang: 3, betta: 1, puffer: 2 },
    art: { palette: "lagoon", bubbleDensity: 55, current: 1.0, showTelemetry: false, reefDensity: 50 },
    backdrop: { source: "plain", imagePath: "", fitMode: "cover", dimming: 45, effectsEnabled: false, effectIntensity: 55 },
    sound: { enabled: false, volume: 24, water: true, bubbles: true },
    integration: { idleEnabled: true, exitOnPointerMotion: true }
  })
  property var speciesDefinitions: [
    { key: "neon_tetra", name: "Neon tetra", callSign: "NEON//SHOAL", description: "electric schooling streaks", accent: "#45f3ff", max: 20 },
    { key: "clownfish", name: "Clownfish", callSign: "EMBER//CLOWN", description: "warm banded reef dancers", accent: "#ff8a3d", max: 12 },
    { key: "angelfish", name: "Angelfish", callSign: "VEIL//ANGEL", description: "tall, unhurried silhouettes", accent: "#f7e8a4", max: 10 },
    { key: "discus", name: "Discus", callSign: "DISC//SUN", description: "round chromatic drifters", accent: "#ff5ca8", max: 10 },
    { key: "butterflyfish", name: "Butterflyfish", callSign: "PRISM//WING", description: "sharp reef geometry", accent: "#ffe45d", max: 10 },
    { key: "royal_tang", name: "Royal tang", callSign: "COBALT//TANG", description: "blue current runners", accent: "#5899ff", max: 12 },
    { key: "betta", name: "Betta", callSign: "SILK//BETTA", description: "solitary trailing fins", accent: "#c681ff", max: 6 },
    { key: "puffer", name: "Puffer", callSign: "ORB//PUFFER", description: "curious buoyant sentries", accent: "#a9f37d", max: 10 }
  ]
  property var config: JSON.parse(JSON.stringify(defaults))
  property real driftPhase: 0

  readonly property string pluginId: "dailen.omarcharium"
  function fromFileUrl(url) {
    var path = String(url || "").replace(/^file:\/\//, "").replace(/\/$/, "")
    try { return decodeURIComponent(path) } catch (error) { return path }
  }

  function toFileUrl(path) {
    var text = String(path || "")
    if (!text) return ""
    var segments = text.split("/").map(function(segment) { return encodeURIComponent(segment) })
    return "file://" + segments.join("/")
  }

  readonly property string pluginDir: root.fromFileUrl(Qt.resolvedUrl("."))
  readonly property string configDir: Quickshell.env("HOME") + "/.config/omarcharium"
  readonly property string configPath: configDir + "/config.json"
  readonly property string launcherPath: pluginDir + "/scripts/launch-aquarium"
  readonly property string selectorPath: pluginDir + "/scripts/select-backdrop"
  readonly property string fontFamily: "monospace"
  readonly property color accent: paletteAccent(config && config.art ? config.art.palette : "lagoon")
  readonly property int totalFish: countFish()
  readonly property var paletteDefinitions: [
    { key: "lagoon", label: "LAGOON", accent: "#5ce6df", deep: "#061b25" },
    { key: "midnight", label: "MIDNIGHT", accent: "#8ea7ff", deep: "#070b1d" },
    { key: "coral", label: "CORAL", accent: "#ff956f", deep: "#200b1b" },
    { key: "phosphor", label: "PHOSPHOR", accent: "#75ffad", deep: "#03130d" }
  ]

  function paletteAccent(key) {
    for (var i = 0; i < paletteDefinitions.length; i++)
      if (paletteDefinitions[i].key === key) return paletteDefinitions[i].accent
    return paletteDefinitions[0].accent
  }

  function paletteDeep(key) {
    for (var i = 0; i < paletteDefinitions.length; i++)
      if (paletteDefinitions[i].key === key) return paletteDefinitions[i].deep
    return paletteDefinitions[0].deep
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value))
  }

  function clamp(value, minimum, maximum, fallback) {
    var number = Number(value)
    if (!isFinite(number)) number = fallback
    return Math.max(minimum, Math.min(maximum, number))
  }

  function normalise(raw) {
    var incoming = raw && typeof raw === "object" ? raw : ({})
    var next = clone(defaults)
    var incomingSpecies = incoming.species && typeof incoming.species === "object" ? incoming.species : ({})
    for (var i = 0; i < speciesDefinitions.length; i++) {
      var definition = speciesDefinitions[i]
      var fallback = Number(defaults.species[definition.key] || 0)
      next.species[definition.key] = Math.round(clamp(incomingSpecies[definition.key], 0, definition.max, fallback))
    }
    var art = incoming.art && typeof incoming.art === "object" ? incoming.art : ({})
    var palette = String(art.palette || defaults.art.palette)
    var knownPalette = false
    for (var p = 0; p < paletteDefinitions.length; p++)
      if (paletteDefinitions[p].key === palette) knownPalette = true
    next.art.palette = knownPalette ? palette : defaults.art.palette
    next.art.bubbleDensity = Math.round(clamp(art.bubbleDensity, 0, 100, defaults.art.bubbleDensity))
    next.art.current = Math.round(clamp(art.current, 0.35, 1.8, defaults.art.current) * 100) / 100
    next.art.showTelemetry = art.showTelemetry === undefined ? defaults.art.showTelemetry : !!art.showTelemetry
    next.art.reefDensity = Math.round(clamp(art.reefDensity === undefined ? art.vegetationVolume : art.reefDensity, 0, 100, defaults.art.reefDensity))
    var backdrop = incoming.backdrop && typeof incoming.backdrop === "object" ? incoming.backdrop : ({})
    var backdropSource = String(backdrop.source || defaults.backdrop.source)
    next.backdrop.source = ["pelagic", "image"].indexOf(backdropSource) >= 0 ? backdropSource : "plain"
    next.backdrop.imagePath = typeof backdrop.imagePath === "string" ? backdrop.imagePath : defaults.backdrop.imagePath
    var fitMode = String(backdrop.fitMode || defaults.backdrop.fitMode)
    next.backdrop.fitMode = ["cover", "contain", "center"].indexOf(fitMode) >= 0 ? fitMode : "cover"
    next.backdrop.dimming = Math.round(clamp(backdrop.dimming, 0, 90, defaults.backdrop.dimming))
    next.backdrop.effectsEnabled = typeof backdrop.effectsEnabled === "boolean" ? backdrop.effectsEnabled : defaults.backdrop.effectsEnabled
    next.backdrop.effectIntensity = Math.round(clamp(backdrop.effectIntensity, 0, 100, defaults.backdrop.effectIntensity))
    var sound = incoming.sound && typeof incoming.sound === "object" ? incoming.sound : ({})
    next.sound.enabled = sound.enabled === undefined ? defaults.sound.enabled : !!sound.enabled
    next.sound.volume = Math.round(clamp(sound.volume, 0, 100, defaults.sound.volume))
    next.sound.water = sound.water === undefined ? (sound.waterFlow === undefined ? (sound.waterEnabled === undefined ? defaults.sound.water : !!sound.waterEnabled) : !!sound.waterFlow) : !!sound.water
    next.sound.bubbles = sound.bubbles === undefined ? (sound.bubblesEnabled === undefined ? defaults.sound.bubbles : !!sound.bubblesEnabled) : !!sound.bubbles
    var integration = incoming.integration && typeof incoming.integration === "object" ? incoming.integration : ({})
    next.integration.idleEnabled = integration.idleEnabled === undefined ? defaults.integration.idleEnabled : !!integration.idleEnabled
    next.integration.exitOnPointerMotion = typeof integration.exitOnPointerMotion === "boolean" ? integration.exitOnPointerMotion : defaults.integration.exitOnPointerMotion
    return next
  }

  function countFish() {
    var total = 0
    if (!config || !config.species) return total
    for (var key in config.species) total += Number(config.species[key] || 0)
    return total
  }

  function speciesCount(key) {
    return config && config.species ? Number(config.species[key] || 0) : 0
  }

  function ensureDirectory() {
    if (!ensureDir.running) ensureDir.running = true
  }

  function finishDirectorySetup(exitCode) {
    directoryReady = exitCode === 0
    if (directoryReady && pendingSaveText) {
      configFile.setText(pendingSaveText)
      pendingSaveText = ""
      statusLine = "CONFIGURATION SYNCHRONIZED"
    }
  }

  function persist() {
    pendingSaveText = JSON.stringify(normalise(config), null, 2) + "\n"
    statusLine = "WRITING HABITAT PARAMETERS..."
    if (!directoryReady) {
      ensureDirectory()
      return
    }
    configFile.setText(pendingSaveText)
    pendingSaveText = ""
    statusLine = "CONFIGURATION SYNCHRONIZED"
  }

  function changeSpecies(key, delta, maximum) {
    var next = clone(config)
    next.species[key] = Math.round(clamp(Number(next.species[key] || 0) + delta, 0, maximum, 0))
    config = next
    persist()
  }

  function changeArt(key, value) {
    var next = clone(config)
    next.art[key] = value
    config = normalise(next)
    persist()
  }

  function changeBackdrop(key, value) {
    var next = clone(config)
    next.backdrop[key] = value
    config = normalise(next)
    backdropPreviewPending = true
    persist()
  }

  function selectBackdropImage() {
    if (!pluginDir || backdropPicker.running) return
    backdropPickerSelected = false
    statusLine = "OPENING OMARCHY IMAGE PICKER..."
    backdropPicker.command = [selectorPath, config.backdrop.imagePath]
    backdropPicker.running = true
  }

  function clearBackdropImage() {
    var next = clone(config)
    next.backdrop.imagePath = ""
    if (next.backdrop.source === "image") next.backdrop.source = "plain"
    config = normalise(next)
    backdropPreviewPending = true
    persist()
  }

  function refreshBackdropPreview() {
    if (!pluginDir) return
    if (config.backdrop.source !== "image" || !config.backdrop.imagePath) {
      backdropPreview.running = false
      backdropPreviewDirty = false
      backdropPreviewPath = ""
      backdropPreviewError = ""
      return
    }
    if (backdropPreview.running) {
      backdropPreviewPath = ""
      backdropPreviewError = ""
      backdropPreviewDirty = true
      return
    }
    backdropPreviewPath = ""
    backdropPreviewError = ""
    backdropPreviewHandled = false
    backdropPreview.command = [
      "python3", pluginDir + "/scripts/aquarium.py",
      "--config", configPath, "--check-backdrop", "--json",
    ]
    backdropPreview.running = true
  }

  function changeSound(key, value) {
    var next = clone(config)
    next.sound[key] = value
    config = normalise(next)
    persist()
  }

  function changeIntegration(key, value) {
    var next = clone(config)
    next.integration[key] = !!value
    config = normalise(next)
    persist()
  }

  function restoreDefaults() {
    config = clone(defaults)
    statusLine = "DEFAULT REEF RESTORED"
    backdropPreviewPending = true
    persist()
  }

  function open(payloadJson) {
    opened = true
    statusLine = "READING HABITAT PARAMETERS..."
    ensureDirectory()
    configFile.reload()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function close() {
    opened = false
  }

  function dismiss() {
    opened = false
    if (shell && typeof shell.hide === "function") shell.hide(pluginId)
  }

  function launchAquarium() {
    persist()
    dismiss()
    if (pluginDir) Quickshell.execDetached(["bash", launcherPath, "force"])
  }

  function stopAquarium() {
    Quickshell.execDetached(["pkill", "-f", "[o]rg.omarchy.screensaver"])
    statusLine = "SURFACE SEQUENCE REQUESTED"
  }

  function testAudio() {
    if (!pluginDir || audioTest.running) return
    persist()
    statusLine = "PIPEWIRE AUDIO TEST · LISTEN FOR THREE RISING TONES"
    audioTest.command = ["python3", pluginDir + "/scripts/aquarium.py", "--audio-test", "8"]
    audioTest.running = true
  }

  Process {
    id: ensureDir
    command: ["mkdir", "-p", root.configDir]
    onExited: function(exitCode) {
      if (exitCode === 0) secureDir.running = true
      else root.finishDirectorySetup(exitCode)
    }
  }

  Process {
    id: secureDir
    command: ["chmod", "700", root.configDir]
    onExited: function(exitCode) { root.finishDirectorySetup(exitCode) }
  }

  Process {
    id: audioTest
    onExited: function(exitCode) {
      root.statusLine = exitCode === 0
        ? "AUDIO TEST COMPLETE"
        : "AUDIO TEST FAILED · RUN --audio-test IN A TERMINAL FOR DETAILS"
    }
  }

  Process {
    id: backdropPicker
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var selected = String(text || "").replace(/\n+$/, "")
        if (!selected) return
        root.backdropPickerSelected = true
        var next = root.clone(root.config)
        next.backdrop.imagePath = selected
        next.backdrop.source = "image"
        root.config = root.normalise(next)
        root.backdropPreviewPending = true
        root.persist()
      }
    }
    onExited: function(exitCode) {
      if (!root.backdropPickerSelected)
        root.statusLine = "IMAGE PICKER CLOSED WITHOUT A SELECTION"
    }
  }

  Process {
    id: backdropPreview
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        root.backdropPreviewHandled = true
        if (root.backdropPreviewPending || root.backdropPreviewDirty || root.config.backdrop.source !== "image") return
        var parsed = null
        try { parsed = JSON.parse(String(text || "")) } catch (error) { parsed = null }
        if (parsed && parsed.ok && typeof parsed.path === "string" && parsed.path) {
          root.backdropPreviewPath = parsed.path
          root.backdropPreviewError = ""
        } else {
          root.backdropPreviewPath = ""
          root.backdropPreviewError = (parsed && typeof parsed.error === "string" && parsed.error)
            ? parsed.error
            : "custom image preview unavailable"
        }
      }
    }
    onExited: function(exitCode) {
      if (root.backdropPreviewPending) return
      if (root.backdropPreviewDirty) {
        root.backdropPreviewDirty = false
        root.refreshBackdropPreview()
      } else if (!root.backdropPreviewHandled && root.config.backdrop.source === "image") {
        root.backdropPreviewPath = ""
        root.backdropPreviewError = "custom image preview unavailable"
      }
    }
  }



  FileView {
    id: defaultsFile
    path: root.pluginDir ? root.pluginDir + "/defaults.json" : ""
    printErrors: false
    onLoaded: {
      try {
        root.defaults = root.normalise(JSON.parse(text()))
      } catch (error) {
        console.warn("Omarcharium defaults parse failed:", error)
      }
    }
  }

  FileView {
    id: speciesFile
    path: root.pluginDir ? root.pluginDir + "/species.json" : ""
    printErrors: false
    onLoaded: {
      try {
        var parsed = JSON.parse(text())
        if (Array.isArray(parsed) && parsed.length > 0) root.speciesDefinitions = parsed
      } catch (error) {
        console.warn("Omarcharium species parse failed:", error)
      }
    }
  }

  FileView {
    id: configFile
    path: root.configPath
    watchChanges: false
    atomicWrites: true
    onSaved: {
      if (root.backdropPreviewPending) {
        root.backdropPreviewPending = false
        root.refreshBackdropPreview()
      }
    }
    onSaveFailed: {
      if (root.backdropPreviewPending) {
        root.backdropPreviewPending = false
        root.backdropPreviewDirty = false
        root.backdropPreviewHandled = true
        backdropPreview.running = false
        root.backdropPreviewPath = ""
        root.backdropPreviewError = "configuration save failed"
      }
      root.statusLine = "CONFIGURATION SAVE FAILED"
    }
    printErrors: false
    onLoaded: {
      try {
        root.config = root.normalise(JSON.parse(text()))
        root.statusLine = "CONFIGURATION SYNCHRONIZED"
      } catch (error) {
        root.config = root.clone(root.defaults)
        root.statusLine = "INVALID CONFIGURATION · SAFE DEFAULTS ACTIVE"
      }
      root.refreshBackdropPreview()
    }
    onLoadFailed: {
      root.config = root.clone(root.defaults)
      root.statusLine = "NEW HABITAT · DEFAULT PARAMETERS ACTIVE"
      root.refreshBackdropPreview()
    }
  }

  Timer {
    interval: 50
    running: root.opened
    repeat: true
    onTriggered: {
      root.driftPhase += 0.025
      habitatCanvas.requestPaint()
    }
  }


  Component.onCompleted: ensureDirectory()

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omarcharium-control-room"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      color: "#d9030912"

      Canvas {
        id: habitatCanvas
        anchors.fill: parent
        opacity: 0.62
        onPaint: {
          var context = getContext("2d")
          context.reset()
          var gradient = context.createLinearGradient(0, 0, 0, height)
          gradient.addColorStop(0, root.paletteDeep(root.config.art.palette))
          gradient.addColorStop(1, "#02070b")
          context.fillStyle = gradient
          context.fillRect(0, 0, width, height)
          context.strokeStyle = root.accent
          context.globalAlpha = 0.12
          context.lineWidth = 1
          for (var band = 0; band < 9; band++) {
            context.beginPath()
            for (var x = -20; x < width + 20; x += 18) {
              var y = 55 + band * 74 + Math.sin(x * 0.017 + root.driftPhase * (1 + band * 0.07)) * (9 + band)
              if (x < 0) context.moveTo(x, y)
              else context.lineTo(x, y)
            }
            context.stroke()
          }
          context.globalAlpha = 0.18
          for (var bubble = 0; bubble < 34; bubble++) {
            var bx = (bubble * 137 + root.driftPhase * (12 + bubble % 5)) % Math.max(1, width)
            var by = height - ((bubble * 83 + root.driftPhase * (42 + bubble % 7)) % Math.max(1, height))
            var radius = 1 + bubble % 5
            context.beginPath()
            context.arc(bx, by, radius, 0, Math.PI * 2)
            context.stroke()
          }
        }
      }

      Repeater {
        model: Math.ceil(panel.height / 5)
        Rectangle {
          required property int index
          x: 0
          y: index * 5
          width: panel.width
          height: 1
          color: "#08ffffff"
        }
      }
    }

    MouseArea {
      anchors.fill: parent
      onClicked: root.dismiss()
    }

    Rectangle {
      id: card
      anchors.centerIn: parent
      width: Math.min(900, panel.width - 40)
      height: Math.min(920, panel.height - 34)
      radius: 18
      color: "#ee07161e"
      border.width: 1
      border.color: root.accent
      clip: true

      MouseArea {
        anchors.fill: parent
        onClicked: function(mouse) { mouse.accepted = true }
      }

      Rectangle {
        id: header
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: 118
        color: "#3318b6c9"

        Text {
          x: 28
          y: 18
          text: "OMARCHARIUM"
          color: root.accent
          font.family: root.fontFamily
          font.pixelSize: 32
          font.bold: true
          font.letterSpacing: 5
        }
        Text {
          x: 31
          y: 62
          text: "PELAGIC TERMINAL ENVIRONMENT // CONTROL ROOM"
          color: "#b8dce5"
          font.family: root.fontFamily
          font.pixelSize: 12
          font.letterSpacing: 1.6
        }
        Text {
          anchors { right: closeButton.left; rightMargin: 24; verticalCenter: parent.verticalCenter }
          text: String(root.totalFish).padStart(2, "0") + " LIFE FORMS"
          color: "#86aeb7"
          font.family: root.fontFamily
          font.pixelSize: 12
        }
        Rectangle {
          id: closeButton
          anchors { right: parent.right; rightMargin: 20; verticalCenter: parent.verticalCenter }
          width: 38
          height: 38
          radius: 19
          color: closeHover.containsMouse ? "#33ffffff" : "#14ffffff"
          border.width: 1
          border.color: "#667a9199"
          Text {
            anchors.centerIn: parent
            text: "×"
            color: "#d5edf2"
            font.family: root.fontFamily
            font.pixelSize: 23
          }
          MouseArea {
            id: closeHover
            anchors.fill: parent
            hoverEnabled: true
            onClicked: root.dismiss()
          }
        }
      }

      Flickable {
        id: scroll
        anchors { top: header.bottom; bottom: footer.top; left: parent.left; right: parent.right }
        contentWidth: width
        contentHeight: content.implicitHeight + 40
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
          id: content
          x: 26
          y: 22
          width: scroll.width - 52
          spacing: 18

          Rectangle {
            width: parent.width
            height: 138
            radius: 12
            color: "#4a041016"
            border.width: 1
            border.color: "#334fc9d5"
            clip: true

            Repeater {
              model: 16
              Text {
                required property int index
                x: (index * 83 + root.driftPhase * (8 + index % 3)) % Math.max(1, parent.width)
                y: 18 + (index * 37) % 96
                text: index % 4 === 0 ? "o" : index % 3 === 0 ? "." : "·"
                color: "#427dced8"
                font.family: root.fontFamily
                font.pixelSize: 10 + index % 4
              }
            }
            Text {
              x: (root.driftPhase * 24) % (parent.width + 150) - 150
              y: 29
              text: "<==_o_>"
              color: "#45f3ff"
              font.family: root.fontFamily
              font.pixelSize: 19
            }
            Text {
              x: parent.width - ((root.driftPhase * 13 + 90) % (parent.width + 180))
              y: 78
              text: "< (o ) =~>"
              color: "#ff8a3d"
              font.family: root.fontFamily
              font.pixelSize: 22
            }
            Text {
              anchors { right: parent.right; rightMargin: 18; top: parent.top; topMargin: 14 }
              text: "LIVE BIOSPHERE PREVIEW\nANSI TRUECOLOR · 24 FPS"
              visible: root.config.art.showTelemetry
              horizontalAlignment: Text.AlignRight
              color: "#678e99"
              font.family: root.fontFamily
              font.pixelSize: 10
              lineHeight: 1.35
            }
          }

          Text {
            text: "SPECIES MANIFEST"
            color: "#8baab2"
            font.family: root.fontFamily
            font.pixelSize: 11
            font.bold: true
            font.letterSpacing: 2
          }

          Column {
            width: parent.width
            spacing: 7

            Repeater {
              model: root.speciesDefinitions
              Rectangle {
                id: speciesRow
                required property var modelData
                width: content.width
                height: 56
                radius: 9
                color: rowHover.containsMouse ? "#261bb8c8" : "#160c252d"
                border.width: 1
                border.color: rowHover.containsMouse ? modelData.accent : "#263e6670"

                Rectangle {
                  x: 12
                  anchors.verticalCenter: parent.verticalCenter
                  width: 4
                  height: 30
                  radius: 2
                  color: speciesRow.modelData.accent
                }
                Text {
                  x: 29
                  y: 9
                  text: speciesRow.modelData.name.toUpperCase()
                  color: "#d7eef2"
                  font.family: root.fontFamily
                  font.pixelSize: 13
                  font.bold: true
                }
                Text {
                  x: 29
                  y: 31
                  text: speciesRow.modelData.callSign + " · " + speciesRow.modelData.description
                  color: "#718f98"
                  font.family: root.fontFamily
                  font.pixelSize: 10
                }
                Row {
                  anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
                  spacing: 8

                  Rectangle {
                    width: 32
                    height: 32
                    radius: 7
                    color: minusHover.containsMouse ? "#335ce6df" : "#1cffffff"
                    Text { anchors.centerIn: parent; text: "−"; color: "#cce8ec"; font.family: root.fontFamily; font.pixelSize: 18 }
                    MouseArea {
                      id: minusHover
                      anchors.fill: parent
                      hoverEnabled: true
                      onClicked: root.changeSpecies(speciesRow.modelData.key, -1, speciesRow.modelData.max)
                    }
                  }
                  Text {
                    width: 34
                    height: 32
                    text: String(root.speciesCount(speciesRow.modelData.key)).padStart(2, "0")
                    color: speciesRow.modelData.accent
                    font.family: root.fontFamily
                    font.pixelSize: 18
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                  }
                  Rectangle {
                    width: 32
                    height: 32
                    radius: 7
                    color: plusHover.containsMouse ? "#335ce6df" : "#1cffffff"
                    Text { anchors.centerIn: parent; text: "+"; color: "#cce8ec"; font.family: root.fontFamily; font.pixelSize: 17 }
                    MouseArea {
                      id: plusHover
                      anchors.fill: parent
                      hoverEnabled: true
                      onClicked: root.changeSpecies(speciesRow.modelData.key, 1, speciesRow.modelData.max)
                    }
                  }
                }
                MouseArea {
                  id: rowHover
                  anchors { left: parent.left; right: parent.right; top: parent.top; bottom: parent.bottom; rightMargin: 128 }
                  hoverEnabled: true
                  acceptedButtons: Qt.NoButton
                }
              }
            }
          }

          Text {
            text: "WATER COLUMN"
            color: "#8baab2"
            font.family: root.fontFamily
            font.pixelSize: 11
            font.bold: true
            font.letterSpacing: 2
          }

          Rectangle {
            width: parent.width
            height: 258
            radius: 11
            color: "#160c252d"
            border.width: 1
            border.color: "#263e6670"

            Text {
              x: 16; y: 14
              text: "CHROMATIC DEPTH"
              color: "#d7eef2"
              font.family: root.fontFamily
              font.pixelSize: 12
              font.bold: true
            }
            Row {
              x: 16; y: 43
              spacing: 8
              Repeater {
                model: root.paletteDefinitions
                Rectangle {
                  id: paletteChip
                  required property var modelData
                  width: Math.floor((content.width - 32 - 24) / 4)
                  height: 34
                  radius: 7
                  color: root.config.art.palette === paletteChip.modelData.key ? paletteChip.modelData.accent : "#16ffffff"
                  border.width: 1
                  border.color: modelData.accent
                  Text {
                    anchors.centerIn: parent
                    text: paletteChip.modelData.label
                    color: root.config.art.palette === paletteChip.modelData.key ? "#071218" : paletteChip.modelData.accent
                    font.family: root.fontFamily
                    font.pixelSize: 10
                    font.bold: true
                  }
                  MouseArea {
                    anchors.fill: parent
                    onClicked: root.changeArt("palette", paletteChip.modelData.key)
                  }
                }
              }
            }

            Text { x: 16; y: 96; text: "BUBBLE DENSITY"; color: "#a9c6cc"; font.family: root.fontFamily; font.pixelSize: 11 }
            Text { x: 16; y: 143; text: "CURRENT VELOCITY"; color: "#a9c6cc"; font.family: root.fontFamily; font.pixelSize: 11 }
            Text { x: 16; y: 190; text: "REEF DENSITY"; color: "#a9c6cc"; font.family: root.fontFamily; font.pixelSize: 11 }

            Row {
              anchors { right: parent.right; rightMargin: 16; top: parent.top; topMargin: 88 }
              spacing: 8
              Rectangle {
                width: 34; height: 30; radius: 6; color: "#1cffffff"
                Text { anchors.centerIn: parent; text: "−"; color: "#cce8ec"; font.family: root.fontFamily; font.pixelSize: 17 }
                MouseArea { anchors.fill: parent; onClicked: root.changeArt("bubbleDensity", root.config.art.bubbleDensity - 5) }
              }
              Text { width: 54; height: 30; text: root.config.art.bubbleDensity + "%"; color: root.accent; font.family: root.fontFamily; font.pixelSize: 14; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
              Rectangle {
                width: 34; height: 30; radius: 6; color: "#1cffffff"
                Text { anchors.centerIn: parent; text: "+"; color: "#cce8ec"; font.family: root.fontFamily; font.pixelSize: 16 }
                MouseArea { anchors.fill: parent; onClicked: root.changeArt("bubbleDensity", root.config.art.bubbleDensity + 5) }
              }
            }

            Row {
              anchors { right: parent.right; rightMargin: 16; top: parent.top; topMargin: 135 }
              spacing: 8
              Rectangle {
                width: 34; height: 30; radius: 6; color: "#1cffffff"
                Text { anchors.centerIn: parent; text: "−"; color: "#cce8ec"; font.family: root.fontFamily; font.pixelSize: 17 }
                MouseArea { anchors.fill: parent; onClicked: root.changeArt("current", root.config.art.current - 0.1) }
              }
              Text { width: 54; height: 30; text: Number(root.config.art.current).toFixed(1) + "×"; color: root.accent; font.family: root.fontFamily; font.pixelSize: 14; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
              Rectangle {
                width: 34; height: 30; radius: 6; color: "#1cffffff"
                Text { anchors.centerIn: parent; text: "+"; color: "#cce8ec"; font.family: root.fontFamily; font.pixelSize: 16 }
                MouseArea { anchors.fill: parent; onClicked: root.changeArt("current", root.config.art.current + 0.1) }
              }
            }

            Row {
              anchors { right: parent.right; rightMargin: 16; top: parent.top; topMargin: 182 }
              spacing: 8
              Rectangle {
                width: 34; height: 30; radius: 6; color: "#1cffffff"
                Text { anchors.centerIn: parent; text: "−"; color: "#cce8ec"; font.family: root.fontFamily; font.pixelSize: 17 }
                MouseArea { anchors.fill: parent; onClicked: root.changeArt("reefDensity", root.config.art.reefDensity - 5) }
              }
              Text { width: 54; height: 30; text: root.config.art.reefDensity + "%"; color: root.accent; font.family: root.fontFamily; font.pixelSize: 14; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
              Rectangle {
                width: 34; height: 30; radius: 6; color: "#1cffffff"
                Text { anchors.centerIn: parent; text: "+"; color: "#cce8ec"; font.family: root.fontFamily; font.pixelSize: 16 }
                MouseArea { anchors.fill: parent; onClicked: root.changeArt("reefDensity", root.config.art.reefDensity + 5) }
              }
            }

            Rectangle {
              x: 16; y: 228
              width: 18; height: 18; radius: 4
              color: root.config.art.showTelemetry ? root.accent : "transparent"
              border.width: 1; border.color: root.accent
              Text { anchors.centerIn: parent; text: root.config.art.showTelemetry ? "✓" : ""; color: "#061219"; font.family: root.fontFamily; font.pixelSize: 13; font.bold: true }
              MouseArea { anchors.fill: parent; onClicked: root.changeArt("showTelemetry", !root.config.art.showTelemetry) }
            }
            Text { x: 43; y: 230; text: "show status display"; color: "#78959d"; font.family: root.fontFamily; font.pixelSize: 10 }
          }
          Text {
            text: "BACKDROP LAYERS"
            color: "#8baab2"
            font.family: root.fontFamily
            font.pixelSize: 11
            font.bold: true
            font.letterSpacing: 2
          }

          Rectangle {
            width: parent.width
            height: 334
            radius: 11
            color: "#160c252d"
            border.width: 1
            border.color: "#263e6670"

            Text { x: 16; y: 14; text: "BACKGROUND SOURCE"; color: "#d7eef2"; font.family: root.fontFamily; font.pixelSize: 12; font.bold: true }
            Row {
              x: 16; y: 39
              spacing: 8
              Repeater {
                model: [
                  { key: "plain", label: "PLAIN" },
                  { key: "pelagic", label: "PELAGIC" },
                  { key: "image", label: "IMAGE" }
                ]
                Rectangle {
                  id: backdropChip
                  required property var modelData
                  width: 82; height: 32; radius: 7
                  color: root.config.backdrop.source === backdropChip.modelData.key ? root.accent : "#16ffffff"
                  border.width: 1
                  border.color: root.accent
                  Text { anchors.centerIn: parent; text: backdropChip.modelData.label; color: root.config.backdrop.source === backdropChip.modelData.key ? "#071218" : root.accent; font.family: root.fontFamily; font.pixelSize: 10; font.bold: true }
                  MouseArea {
                    anchors.fill: parent
                    onClicked: {
                      if (backdropChip.modelData.key === "image" && !root.config.backdrop.imagePath) root.selectBackdropImage()
                      else root.changeBackdrop("source", backdropChip.modelData.key)
                    }
                  }
                }
              }
            }

            Rectangle {
              x: 16; y: 82
              width: 176; height: 92; radius: 7
              color: "#0d020b10"
              border.width: 1; border.color: "#35596b73"
              clip: true
              Image {
                anchors.fill: parent
                source: root.config.backdrop.source === "image" && root.backdropPreviewPath
                  ? root.toFileUrl(root.backdropPreviewPath) : ""
                sourceSize.width: 352
                sourceSize.height: 184
                fillMode: Image.PreserveAspectCrop
                visible: root.backdropPreviewPath !== ""
                asynchronous: true
                cache: false
              }
              Rectangle { anchors.fill: parent; color: "#59000000"; visible: root.config.backdrop.imagePath !== "" }
              Text {
                anchors.centerIn: parent
                width: parent.width - 18
                text: root.config.backdrop.imagePath === ""
                  ? "NO IMAGE SELECTED"
                  : (root.backdropPreviewPath !== ""
                      ? "SELECTED IMAGE"
                      : (root.backdropPreviewError !== "" ? root.backdropPreviewError.toUpperCase() : "PREPARING PREVIEW..."))
                color: "#b8d4d8"
                font.family: root.fontFamily
                font.pixelSize: 10
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
              }
            }

            Rectangle {
              x: 208; y: 82
              width: 118; height: 36; radius: 7
              color: backdropPicker.running ? "#335ce6df" : "#1cffffff"
              border.width: 1; border.color: "#47778a92"
              Text { anchors.centerIn: parent; text: backdropPicker.running ? "OPENING..." : "SELECT IMAGE"; color: "#b6d0d5"; font.family: root.fontFamily; font.pixelSize: 10; font.bold: true }
              MouseArea { anchors.fill: parent; enabled: !backdropPicker.running; onClicked: root.selectBackdropImage() }
            }
            Rectangle {
              x: 208; y: 128
              width: 118; height: 36; radius: 7
              color: "#1cffffff"
              border.width: 1; border.color: "#47778a92"
              Text { anchors.centerIn: parent; text: "CLEAR IMAGE"; color: "#b6d0d5"; font.family: root.fontFamily; font.pixelSize: 10; font.bold: true }
              MouseArea { anchors.fill: parent; enabled: root.config.backdrop.imagePath !== ""; onClicked: root.clearBackdropImage() }
            }
            Text { x: 342; y: 87; width: parent.width - 358; text: root.config.backdrop.imagePath || "Omarchy picker scans Pictures, Downloads, and Home"; color: "#718f98"; font.family: root.fontFamily; font.pixelSize: 9; elide: Text.ElideMiddle; wrapMode: Text.Wrap }
            Text { x: 342; y: 139; width: parent.width - 358; text: "native raster: Ghostty + Kitty · plain fallback: Alacritty + Foot"; color: "#5f8993"; font.family: root.fontFamily; font.pixelSize: 9; wrapMode: Text.Wrap }

            Text { x: 16; y: 194; text: "IMAGE FIT"; color: "#a9c6cc"; font.family: root.fontFamily; font.pixelSize: 11 }
            Row {
              x: 104; y: 184
              spacing: 7
              Repeater {
                model: ["cover", "contain", "center"]
                Rectangle {
                  id: fitChip
                  required property string modelData
                  width: 82; height: 30; radius: 6
                  color: root.config.backdrop.fitMode === fitChip.modelData ? "#335ce6df" : "#1cffffff"
                  Text { anchors.centerIn: parent; text: fitChip.modelData.toUpperCase(); color: root.config.backdrop.fitMode === fitChip.modelData ? root.accent : "#91adb3"; font.family: root.fontFamily; font.pixelSize: 9; font.bold: true }
                  MouseArea { anchors.fill: parent; onClicked: root.changeBackdrop("fitMode", fitChip.modelData) }
                }
              }
            }

            Text { x: 16; y: 239; text: "IMAGE DIMMING"; color: "#a9c6cc"; font.family: root.fontFamily; font.pixelSize: 11 }
            Row {
              anchors { right: parent.right; rightMargin: 16; top: parent.top; topMargin: 229 }
              spacing: 8
              Rectangle {
                width: 34; height: 30; radius: 6; color: "#1cffffff"
                Text { anchors.centerIn: parent; text: "−"; color: "#cce8ec"; font.family: root.fontFamily; font.pixelSize: 17 }
                MouseArea { anchors.fill: parent; onClicked: root.changeBackdrop("dimming", root.config.backdrop.dimming - 5) }
              }
              Text { width: 54; height: 30; text: root.config.backdrop.dimming + "%"; color: root.accent; font.family: root.fontFamily; font.pixelSize: 14; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
              Rectangle {
                width: 34; height: 30; radius: 6; color: "#1cffffff"
                Text { anchors.centerIn: parent; text: "+"; color: "#cce8ec"; font.family: root.fontFamily; font.pixelSize: 16 }
                MouseArea { anchors.fill: parent; onClicked: root.changeBackdrop("dimming", root.config.backdrop.dimming + 5) }
              }
            }


            Text { x: 16; y: 286; text: "PELAGIC EFFECT OVERLAY"; color: "#a9c6cc"; font.family: root.fontFamily; font.pixelSize: 11 }
            Rectangle {
              x: 180; y: 278
              width: 48; height: 26; radius: 13
              color: root.config.backdrop.effectsEnabled ? root.accent : "#31454b"
              Rectangle { x: root.config.backdrop.effectsEnabled ? parent.width - width - 3 : 3; anchors.verticalCenter: parent.verticalCenter; width: 20; height: 20; radius: 10; color: root.config.backdrop.effectsEnabled ? "#071218" : "#aec4c9"; Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } } }
              MouseArea { anchors.fill: parent; onClicked: root.changeBackdrop("effectsEnabled", !root.config.backdrop.effectsEnabled) }
            }
            Row {
              anchors { right: parent.right; rightMargin: 16; top: parent.top; topMargin: 276 }
              spacing: 8
              Rectangle {
                width: 34; height: 30; radius: 6; color: "#1cffffff"
                Text { anchors.centerIn: parent; text: "−"; color: "#cce8ec"; font.family: root.fontFamily; font.pixelSize: 17 }
                MouseArea { anchors.fill: parent; onClicked: root.changeBackdrop("effectIntensity", root.config.backdrop.effectIntensity - 5) }
              }
              Text { width: 54; height: 30; text: root.config.backdrop.effectIntensity + "%"; color: root.accent; font.family: root.fontFamily; font.pixelSize: 14; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
              Rectangle {
                width: 34; height: 30; radius: 6; color: "#1cffffff"
                Text { anchors.centerIn: parent; text: "+"; color: "#cce8ec"; font.family: root.fontFamily; font.pixelSize: 16 }
                MouseArea { anchors.fill: parent; onClicked: root.changeBackdrop("effectIntensity", root.config.backdrop.effectIntensity + 5) }
              }
            }
          }

          Text {
            text: "HYDROPHONIC AMBIENCE"
            color: "#8baab2"
            font.family: root.fontFamily
            font.pixelSize: 11
            font.bold: true
            font.letterSpacing: 2
          }

          Rectangle {
            width: parent.width
            height: 148
            radius: 11
            color: root.config.sound.enabled ? "#241bb8c8" : "#160c252d"
            border.width: 1
            border.color: root.config.sound.enabled ? root.accent : "#263e6670"

            Text { x: 16; y: 14; text: "PROCEDURAL AMBIENCE SYNTHESIS"; color: "#d7eef2"; font.family: root.fontFamily; font.pixelSize: 12; font.bold: true }
            Text { x: 16; y: 39; text: "generated locally · streamed to PipeWire · no audio files"; color: "#718f98"; font.family: root.fontFamily; font.pixelSize: 10 }

            Rectangle {
              anchors { right: soundToggle.left; rightMargin: 12; top: parent.top; topMargin: 18 }
              width: 74; height: 30; radius: 6
              color: audioTest.running ? "#335ce6df" : "#1cffffff"
              border.width: 1; border.color: "#47778a92"
              Text {
                anchors.centerIn: parent
                text: audioTest.running ? "PLAYING" : "TEST 8S"
                color: audioTest.running ? root.accent : "#b6d0d5"
                font.family: root.fontFamily
                font.pixelSize: 10
                font.bold: true
              }
              MouseArea { anchors.fill: parent; enabled: !audioTest.running; onClicked: root.testAudio() }
            }

            Rectangle {
              id: soundToggle
              anchors { right: volumeRow.left; rightMargin: 18; top: parent.top; topMargin: 20 }
              width: 48; height: 26; radius: 13
              color: root.config.sound.enabled ? root.accent : "#31454b"
              Rectangle {
                x: root.config.sound.enabled ? parent.width - width - 3 : 3
                anchors.verticalCenter: parent.verticalCenter
                width: 20; height: 20; radius: 10
                color: root.config.sound.enabled ? "#071218" : "#aec4c9"
                Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
              }
              MouseArea { anchors.fill: parent; onClicked: root.changeSound("enabled", !root.config.sound.enabled) }
            }

            Row {
              id: volumeRow
              anchors { right: parent.right; rightMargin: 16; top: parent.top; topMargin: 19 }
              spacing: 7
              Rectangle {
                width: 30; height: 28; radius: 6; color: "#1cffffff"
                Text { anchors.centerIn: parent; text: "−"; color: "#cce8ec"; font.family: root.fontFamily; font.pixelSize: 16 }
                MouseArea { anchors.fill: parent; onClicked: root.changeSound("volume", root.config.sound.volume - 5) }
              }
              Text { width: 46; height: 28; text: root.config.sound.volume + "%"; color: root.accent; font.family: root.fontFamily; font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
              Rectangle {
                width: 30; height: 28; radius: 6; color: "#1cffffff"
                Text { anchors.centerIn: parent; text: "+"; color: "#cce8ec"; font.family: root.fontFamily; font.pixelSize: 15 }
                MouseArea { anchors.fill: parent; onClicked: root.changeSound("volume", root.config.sound.volume + 5) }
              }
            }

            Rectangle {
              x: 16
              y: 70
              width: parent.width - 32
              height: 1
              color: "#263e6670"
            }

            Row {
              x: 16
              y: 82
              width: parent.width - 32
              spacing: 20

              Item {
                width: Math.floor((parent.width - 20) / 2)
                height: 52

                Rectangle {
                  id: waterToggle
                  x: 0
                  y: 12
                  width: 44; height: 24; radius: 12
                  color: root.config.sound.water ? root.accent : "#31454b"
                  Rectangle {
                    x: root.config.sound.water ? parent.width - width - 2 : 2
                    anchors.verticalCenter: parent.verticalCenter
                    width: 18; height: 18; radius: 9
                    color: root.config.sound.water ? "#071218" : "#aec4c9"
                    Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                  }
                }

                Column {
                  anchors { left: waterToggle.right; leftMargin: 12; top: parent.top; topMargin: 7; right: parent.right }
                  spacing: 4
                  Text {
                    text: "WATER FLOW"
                    color: root.config.sound.water ? "#d7eef2" : "#718f98"
                    font.family: root.fontFamily
                    font.pixelSize: 11
                    font.bold: true
                  }
                  Text {
                    text: "continuous ambient filtered motion"
                    color: "#718f98"
                    font.family: root.fontFamily
                    font.pixelSize: 10
                  }
                }

                MouseArea {
                  anchors.fill: parent
                  onClicked: root.changeSound("water", !root.config.sound.water)
                }
              }

              Item {
                width: Math.floor((parent.width - 20) / 2)
                height: 52

                Rectangle {
                  id: bubblesToggle
                  x: 0
                  y: 12
                  width: 44; height: 24; radius: 12
                  color: root.config.sound.bubbles ? root.accent : "#31454b"
                  Rectangle {
                    x: root.config.sound.bubbles ? parent.width - width - 2 : 2
                    anchors.verticalCenter: parent.verticalCenter
                    width: 18; height: 18; radius: 9
                    color: root.config.sound.bubbles ? "#071218" : "#aec4c9"
                    Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                  }
                }

                Column {
                  anchors { left: bubblesToggle.right; leftMargin: 12; top: parent.top; topMargin: 7; right: parent.right }
                  spacing: 4
                  Text {
                    text: "BUBBLE CHIRPS"
                    color: root.config.sound.bubbles ? "#d7eef2" : "#718f98"
                    font.family: root.fontFamily
                    font.pixelSize: 11
                    font.bold: true
                  }
                  Text {
                    text: "sparse rising-pitch bubble bursts"
                    color: "#718f98"
                    font.family: root.fontFamily
                    font.pixelSize: 10
                  }
                }

                MouseArea {
                  anchors.fill: parent
                  onClicked: root.changeSound("bubbles", !root.config.sound.bubbles)
                }
              }
            }
          }

          Text {
            text: "OMARCHY IDLE LINK"
            color: "#8baab2"
            font.family: root.fontFamily
            font.pixelSize: 11
            font.bold: true
            font.letterSpacing: 2
          }

          Rectangle {
            width: parent.width
            height: 76
            radius: 11
            color: root.config.integration.idleEnabled ? "#241bb8c8" : "#160c252d"
            border.width: 1
            border.color: root.config.integration.idleEnabled ? root.accent : "#263e6670"

            Text { x: 16; y: 13; text: "AUTOMATIC IDLE IMMERSION"; color: "#d7eef2"; font.family: root.fontFamily; font.pixelSize: 12; font.bold: true }
            Text { x: 16; y: 39; text: "uses shell.json idle.screensaver · preserves Omarchy lock timing"; color: "#718f98"; font.family: root.fontFamily; font.pixelSize: 10 }

            Rectangle {
              anchors { right: parent.right; rightMargin: 17; verticalCenter: parent.verticalCenter }
              width: 48; height: 26; radius: 13
              color: root.config.integration.idleEnabled ? root.accent : "#31454b"
              Rectangle {
                x: root.config.integration.idleEnabled ? parent.width - width - 3 : 3
                anchors.verticalCenter: parent.verticalCenter
                width: 20; height: 20; radius: 10
                color: root.config.integration.idleEnabled ? "#071218" : "#aec4c9"
                Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
              }
              MouseArea { anchors.fill: parent; onClicked: root.changeIntegration("idleEnabled", !root.config.integration.idleEnabled) }
            }
          }

          Text {
            text: "SURFACE CONTROL"
            color: "#8baab2"
            font.family: root.fontFamily
            font.pixelSize: 11
            font.bold: true
            font.letterSpacing: 2
          }

          Rectangle {
            width: parent.width
            height: 76
            radius: 11
            color: root.config.integration.exitOnPointerMotion ? "#241bb8c8" : "#160c252d"
            border.width: 1
            border.color: root.config.integration.exitOnPointerMotion ? root.accent : "#263e6670"

            Text { x: 16; y: 13; text: "EXIT ON POINTER MOVEMENT"; color: "#d7eef2"; font.family: root.fontFamily; font.pixelSize: 12; font.bold: true }
            Text { x: 16; y: 39; text: "clicks and keyboard input always return to the desktop"; color: "#718f98"; font.family: root.fontFamily; font.pixelSize: 10 }

            Rectangle {
              anchors { right: parent.right; rightMargin: 17; verticalCenter: parent.verticalCenter }
              width: 48; height: 26; radius: 13
              color: root.config.integration.exitOnPointerMotion ? root.accent : "#31454b"
              Rectangle {
                x: root.config.integration.exitOnPointerMotion ? parent.width - width - 3 : 3
                anchors.verticalCenter: parent.verticalCenter
                width: 20; height: 20; radius: 10
                color: root.config.integration.exitOnPointerMotion ? "#071218" : "#aec4c9"
                Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
              }
              MouseArea { anchors.fill: parent; onClicked: root.changeIntegration("exitOnPointerMotion", !root.config.integration.exitOnPointerMotion) }
            }
          }
        }
      }

      Rectangle {
        id: footer
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: 82
        color: "#f0071218"
        border.width: 0

        Text {
          x: 24
          anchors.verticalCenter: parent.verticalCenter
          text: root.statusLine
          color: "#6688929a"
          font.family: root.fontFamily
          font.pixelSize: 10
          font.letterSpacing: 1
        }

        Rectangle {
          id: resetButton
          anchors { right: stopButton.left; rightMargin: 10; verticalCenter: parent.verticalCenter }
          width: 96; height: 40; radius: 8
          color: resetHover.containsMouse ? "#2affffff" : "#14ffffff"
          border.width: 1; border.color: "#3c82919a"
          Text { anchors.centerIn: parent; text: "RESET"; color: "#a8c5ca"; font.family: root.fontFamily; font.pixelSize: 11; font.bold: true }
          MouseArea { id: resetHover; anchors.fill: parent; hoverEnabled: true; onClicked: root.restoreDefaults() }
        }
        Rectangle {
          id: stopButton
          anchors { right: launchButton.left; rightMargin: 10; verticalCenter: parent.verticalCenter }
          width: 104; height: 40; radius: 8
          color: stopHover.containsMouse ? "#30ff7990" : "#14ffffff"
          border.width: 1; border.color: "#5bd56d83"
          Text { anchors.centerIn: parent; text: "SURFACE"; color: "#e79aaa"; font.family: root.fontFamily; font.pixelSize: 11; font.bold: true }
          MouseArea { id: stopHover; anchors.fill: parent; hoverEnabled: true; onClicked: root.stopAquarium() }
        }
        Rectangle {
          id: launchButton
          anchors { right: parent.right; rightMargin: 20; verticalCenter: parent.verticalCenter }
          width: 174; height: 44; radius: 9
          color: launchHover.containsMouse ? Qt.lighter(root.accent, 1.12) : root.accent
          border.width: 1; border.color: "#b9ffffff"
          Text { anchors.centerIn: parent; text: "BEGIN IMMERSION  ›"; color: "#071218"; font.family: root.fontFamily; font.pixelSize: 12; font.bold: true; font.letterSpacing: 0.6 }
          MouseArea { id: launchHover; anchors.fill: parent; hoverEnabled: true; onClicked: root.launchAquarium() }
        }
      }

      Item {
        id: keyCatcher
        anchors.fill: parent
        focus: root.opened
        Keys.onEscapePressed: root.dismiss()
        Keys.onReturnPressed: root.launchAquarium()
        Keys.onEnterPressed: root.launchAquarium()
        Keys.onDownPressed: scroll.contentY = Math.min(scroll.contentHeight - scroll.height, scroll.contentY + 64)
        Keys.onUpPressed: scroll.contentY = Math.max(0, scroll.contentY - 64)
        Keys.onPressed: function(event) {
          if (event.key === Qt.Key_PageDown) {
            scroll.contentY = Math.min(scroll.contentHeight - scroll.height, scroll.contentY + scroll.height * 0.82)
            event.accepted = true
          } else if (event.key === Qt.Key_PageUp) {
            scroll.contentY = Math.max(0, scroll.contentY - scroll.height * 0.82)
            event.accepted = true
          } else if (event.key === Qt.Key_Home) {
            scroll.contentY = 0
            event.accepted = true
          } else if (event.key === Qt.Key_End) {
            scroll.contentY = Math.max(0, scroll.contentHeight - scroll.height)
            event.accepted = true
          }
        }
      }
    }
  }
}
