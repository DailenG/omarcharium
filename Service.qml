import QtQuick
import Qt.labs.platform 1.1 as Platform
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

Item {
  id: root

  property var shell: null
  property var manifest: null
  property bool configLoaded: false
  property bool shellConfigLoaded: false
  property bool idleIntegrationEnabled: true
  readonly property string pluginId: "dailen.omarcharium"
  function fromFileUrl(url) {
    var path = String(url || "").replace(/^file:\/\//, "").replace(/\/$/, "")
    try { return decodeURIComponent(path) } catch (error) { return path }
  }

  readonly property string pluginDir: root.fromFileUrl(Qt.resolvedUrl("."))
  readonly property string launcherPath: pluginDir + "/scripts/launch-aquarium"
  readonly property string integrationPath: pluginDir + "/scripts/idle-integration"
  readonly property string stayAwakeStateDir: Quickshell.env("HOME") + "/.local/state/omarchy/indicators"
  readonly property string toggleStateDir: Quickshell.env("HOME") + "/.local/state/omarchy/toggles"
  readonly property bool automaticImmersionEnabled: root.configLoaded
    && root.shellConfigLoaded && root.idleIntegrationEnabled
    && root.stayAwakeStateLoaded && !root.stayAwake
    && root.integrationStatus === "owned"
    && root.integrationConfirmedEpoch === root.integrationEpoch
    && !integrationApply.running && !integrationStatusProbe.running
  property var idleConfig: ({})
  readonly property int screensaverTimeout: {
    var value = Number(idleConfig.screensaver)
    return isFinite(value) && value >= 1 ? Math.round(value) : 150
  }
  property bool stayAwake: false
  property bool stayAwakeStateLoaded: false
  property string integrationStatus: "unknown"
  property bool integrationDesiredEnabled: true
  // Bumped on every event that can change ownership (an apply request or an
  // externally observed toggle change). automaticImmersionEnabled requires
  // integrationConfirmedEpoch to have caught up and no apply/probe to be
  // running, so stale or in-flight state fails closed.
  property int integrationEpoch: 0
  property int integrationConfirmedEpoch: -1
  property bool integrationReprobePending: false

  function openControlRoom() {
    if (shell && typeof shell.summon === "function") {
      shell.summon(pluginId, "{}")
      return
    }
    Quickshell.execDetached(["omarchy-shell", "shell", "summon", pluginId, "{}"])
  }

  function launchAquarium(mode) {
    if (!pluginDir) {
      console.warn("Omarcharium launch called but pluginDir is empty")
      return
    }
    console.log("Omarcharium launching screensaver: " + launcherPath + " (" + mode + ")")
    Quickshell.execDetached(["bash", launcherPath, mode])
  }

  function startAquarium() {
    launchAquarium("force")
  }

  function startAutomaticAquarium() {
    if (automaticImmersionEnabled) launchAquarium("automatic")
  }

  function stopAquarium() {
    Quickshell.execDetached(["pkill", "-f", "[o]rg.omarchy.screensaver"])
  }

  function applyIdleIntegration(enabled) {
    if (!pluginDir) return
    integrationDesiredEnabled = !!enabled
    integrationEpoch += 1
    // A run is already in flight; it re-checks integrationDesiredEnabled
    // against what it just applied when it exits, so this call is not lost.
    if (integrationApply.running) return
    integrationApply.appliedEnabled = integrationDesiredEnabled
    integrationApply.command = ["bash", integrationPath, integrationDesiredEnabled ? "enable" : "disable"]
    integrationApply.running = true
  }

  function refreshIntegrationStatus() {
    if (!pluginDir) return
    if (integrationStatusProbe.running) {
      integrationReprobePending = true
      return
    }
    integrationStatusProbe.requestEpoch = integrationEpoch
    integrationStatusProbe.lastValue = ""
    integrationStatusProbe.running = true
  }

  function applyStayAwake(value) {
    var enabled = !!value
    if (!stayAwakeStateLoaded || stayAwake !== enabled)
      console.log("Omarcharium keep-awake state: " + (enabled ? "enabled" : "disabled"))
    stayAwake = enabled
    stayAwakeStateLoaded = true
  }

  function refreshStayAwakeState() {
    if (!stayAwakeStateProbe.running) stayAwakeStateProbe.running = true
  }

  function loadConfig(raw) {
    var enabled = true
    try {
      var parsed = JSON.parse(raw)
      if (parsed.integration && parsed.integration.idleEnabled !== undefined)
        enabled = !!parsed.integration.idleEnabled
    } catch (error) {
      enabled = true
    }
    idleIntegrationEnabled = enabled
    configLoaded = true
    applyIdleIntegration(enabled)
  }

  function loadShellConfig(raw) {
    var idle = ({})
    try {
      var parsed = JSON.parse(raw)
      if (parsed && parsed.version === 1 && parsed.idle && typeof parsed.idle === "object")
        idle = parsed.idle
    } catch (error) {
      console.warn("Omarcharium shell.json parse failed:", error)
    }
    idleConfig = idle
    shellConfigLoaded = true
    console.log("Omarcharium idle timeout: " + screensaverTimeout + "s")
  }

  onPluginDirChanged: {
    if (configLoaded) applyIdleIntegration(idleIntegrationEnabled)
  }

  FileView {
    id: configFile
    path: Quickshell.env("HOME") + "/.config/omarcharium/config.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.loadConfig(text())
    onFileChanged: reload()
    onLoadFailed: root.loadConfig("{}")
  }

  FileView {
    id: shellConfigFile
    path: Quickshell.env("HOME") + "/.config/omarchy/shell.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.loadShellConfig(text())
    onFileChanged: reload()
    onLoadFailed: root.loadShellConfig("{}")
  }

  IdleMonitor {
    enabled: root.automaticImmersionEnabled
    timeout: root.screensaverTimeout
    respectInhibitors: true
    onIsIdleChanged: {
      console.log("Omarcharium idle state changed: isIdle=" + isIdle + " (timeout=" + root.screensaverTimeout + "s)")
      if (isIdle && root.automaticImmersionEnabled) root.startAutomaticAquarium()
    }
  }

  Process {
    id: stayAwakeStateProbe
    command: ["bash", "-c", "mkdir -p \"$HOME/.local/state/omarchy/indicators\"; if [[ -f $HOME/.local/state/omarchy/indicators/stay-awake ]]; then echo yes; else echo no; fi"]
    stdout: SplitParser {
      onRead: function(line) { root.applyStayAwake(String(line).trim() === "yes") }
    }
    onExited: function() { stayAwakeStateDirWatcher.reload() }
  }

  FileView {
    id: stayAwakeStateDirWatcher
    path: root.stayAwakeStateDir
    watchChanges: true
    printErrors: false
    onFileChanged: root.refreshStayAwakeState()
  }

  Process {
    id: integrationApply
    property bool appliedEnabled: true
    onExited: function(exitCode) {
      if (exitCode !== 0)
        console.warn("Omarcharium idle-integration " + (appliedEnabled ? "enable" : "disable") + " failed (exit " + exitCode + ")")
      if (root.integrationDesiredEnabled !== appliedEnabled) {
        appliedEnabled = root.integrationDesiredEnabled
        command = ["bash", root.integrationPath, appliedEnabled ? "enable" : "disable"]
        running = true
        return
      }
      root.refreshIntegrationStatus()
    }
  }

  Process {
    id: integrationStatusProbe
    property int requestEpoch: 0
    property string lastValue: ""
    command: ["bash", root.integrationPath, "status"]
    stdout: SplitParser {
      onRead: function(line) { integrationStatusProbe.lastValue = String(line).trim() }
    }
    onExited: function(exitCode) {
      var epoch = requestEpoch
      var value = lastValue
      var staleAlready = root.integrationReprobePending || epoch !== root.integrationEpoch
      root.integrationReprobePending = false
      if (exitCode === 0 && epoch === root.integrationEpoch) {
        root.integrationStatus = (value === "owned" || value === "user-disabled" || value === "stock-enabled") ? value : "unknown"
        root.integrationConfirmedEpoch = epoch
      }
      // Something changed (or a recheck was explicitly requested) while
      // this probe was running: chase the latest state instead of leaving a
      // stale result in place. A probe that simply failed with nothing new
      // pending is left unconfirmed (fails closed) rather than retried in a
      // tight loop.
      if (staleAlready) root.refreshIntegrationStatus()
    }
  }

  FileView {
    id: toggleStateDirWatcher
    path: root.toggleStateDir
    watchChanges: true
    printErrors: false
    onFileChanged: {
      root.integrationEpoch += 1
      root.refreshIntegrationStatus()
    }
  }

  Platform.SystemTrayIcon {
    id: trayIcon
    visible: true
    tooltip: "Omarcharium · click to configure · middle-click to immerse"
    icon.source: Qt.resolvedUrl("assets/tray.svg")
    menu: Platform.Menu {
      Platform.MenuItem {
        text: "Open Control Room"
        onTriggered: root.openControlRoom()
      }
      Platform.MenuItem {
        text: "Immerse Now"
        onTriggered: root.startAquarium()
      }
      Platform.MenuSeparator { }
      Platform.MenuItem {
        text: "Report Bug"
        onTriggered: Qt.openUrlExternally("https://github.com/DailenG/omarcharium/issues")
      }
    }

    onActivated: function(reason) {
      if (reason === Platform.SystemTrayIcon.MiddleClick) {
        root.startAquarium()
      } else if (reason === Platform.SystemTrayIcon.Trigger
                 || reason === Platform.SystemTrayIcon.DoubleClick) {
        root.openControlRoom()
      }
    }
  }

  IpcHandler {
    target: "omarcharium"

    function configure(): void { root.openControlRoom() }
    function start(): void { root.startAquarium() }
    function stop(): void { root.stopAquarium() }
    function pluginDirectory(): string { return root.pluginDir }
  }

  Component.onDestruction: {
    if (root.pluginDir) Quickshell.execDetached(["bash", root.integrationPath, "disable"])
  }

  Component.onCompleted: {
    configFile.reload()
    shellConfigFile.reload()
    refreshStayAwakeState()
  }
}
