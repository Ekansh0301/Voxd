// TARS bridge: answers the local TARS assistant about this VS Code window.
// Read-only. One Unix socket per window at $XDG_RUNTIME_DIR/tars-vscode-<pid>.sock
// (that directory is private to the user). One JSON request per line:
//   {"get": "state"}     active file, cursor line, selection, workspace, last focus time
//   {"get": "problems"}  diagnostics (errors/warnings) from all open files
//   {"get": "terminal"}  recent commands in the integrated terminal: command, output, exit code
const vscode = require("vscode");
const net = require("net");
const fs = require("fs");
const path = require("path");

const MAX_RUNS = 6;
const MAX_OUTPUT = 6000;
const runs = []; // recent terminal command executions
let focusedAt = Date.now();

function state() {
  const ed = vscode.window.activeTextEditor;
  return {
    workspace: (vscode.workspace.workspaceFolders || []).map((f) => f.uri.fsPath),
    file: ed ? ed.document.uri.fsPath : null,
    line: ed ? ed.selection.active.line + 1 : null,
    selection: ed && !ed.selection.isEmpty ? ed.document.getText(ed.selection).slice(0, 2000) : "",
    dirty: ed ? ed.document.isDirty : false,
    language: ed ? ed.document.languageId : null,
    focused: vscode.window.state.focused,
    focusedAt,
  };
}

function problems() {
  const sev = ["error", "warning", "info", "hint"];
  const out = [];
  for (const [uri, diags] of vscode.languages.getDiagnostics()) {
    for (const d of diags) {
      if (d.severity > 1) continue; // errors and warnings
      out.push({
        file: uri.fsPath,
        line: d.range.start.line + 1,
        severity: sev[d.severity],
        message: d.message,
        source: d.source || "",
      });
    }
  }
  out.sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "error" ? -1 : 1));
  return out.slice(0, 50);
}

function activate(context) {
  const dir = process.env.XDG_RUNTIME_DIR;
  if (!dir) return;
  const sock = path.join(dir, `tars-vscode-${process.pid}.sock`);
  try { fs.unlinkSync(sock); } catch (_) {}

  context.subscriptions.push(
    vscode.window.onDidChangeWindowState((s) => { if (s.focused) focusedAt = Date.now(); })
  );
  if (vscode.window.onDidStartTerminalShellExecution) {
    context.subscriptions.push(
      vscode.window.onDidStartTerminalShellExecution(async (e) => {
        const run = { terminal: e.terminal.name, command: e.execution.commandLine.value, output: "", exitCode: null, cwd: e.execution.cwd ? e.execution.cwd.fsPath : null };
        runs.push(run);
        if (runs.length > MAX_RUNS) runs.shift();
        try {
          for await (const data of e.execution.read()) {
            run.output = (run.output + data).slice(-MAX_OUTPUT);
          }
        } catch (_) {}
      }),
      vscode.window.onDidEndTerminalShellExecution((e) => {
        const run = [...runs].reverse().find((r) => r.command === e.execution.commandLine.value && r.exitCode === null);
        if (run) run.exitCode = e.exitCode === undefined ? null : e.exitCode;
      })
    );
  }

  const server = net.createServer((conn) => {
    let buf = "";
    conn.on("data", (chunk) => {
      buf += chunk;
      if (!buf.includes("\n")) return;
      let reply;
      try {
        const req = JSON.parse(buf.split("\n")[0]);
        reply = req.get === "problems" ? problems() : req.get === "terminal" ? runs : state();
      } catch (e) {
        reply = { error: String(e) };
      }
      conn.end(JSON.stringify(reply) + "\n");
    });
    conn.on("error", () => {});
  });
  server.listen(sock, () => { try { fs.chmodSync(sock, 0o600); } catch (_) {} });
  context.subscriptions.push({ dispose: () => { server.close(); try { fs.unlinkSync(sock); } catch (_) {} } });
}

function deactivate() {}

module.exports = { activate, deactivate };
