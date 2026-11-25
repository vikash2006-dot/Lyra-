// Starts the LYRA backend (FastAPI) and frontend (Vite) together with prefixed logs.
// Ctrl+C stops both. Refuses to start a second copy if a port is already in use.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const python = [path.join(root, "backend/.venv/bin/python"), path.join(root, ".venv/bin/python")]
  .find(existsSync) || "python3";

const portBusy = (port) =>
  new Promise((resolve) => {
    const s = net.connect({ port, host: "127.0.0.1" }, () => { s.destroy(); resolve(true); });
    s.on("error", () => resolve(false));
  });

const apps = [
  { name: "backend ", color: 35, port: 8000, cmd: python, args: ["main.py"], cwd: path.join(root, "backend") },
  { name: "frontend", color: 36, port: 5173, cmd: "npm", args: ["run", "dev"], cwd: path.join(root, "frontend") },
];

if (!existsSync(path.join(root, "frontend/node_modules"))) {
  console.error("Frontend dependencies missing. Run: npm run setup");
  process.exit(1);
}
for (const app of apps) {
  if (await portBusy(app.port)) {
    console.error(`Port ${app.port} is already in use — is LYRA's ${app.name.trim()} already running? Stop it first.`);
    process.exit(1);
  }
}

const children = [];
let stopping = false;
const stopAll = (code = 0) => {
  if (stopping) return;
  stopping = true;
  for (const c of children) if (c.exitCode === null) c.kill("SIGINT");
  setTimeout(() => process.exit(code), 1500).unref();
};

for (const app of apps) {
  const child = spawn(app.cmd, app.args, { cwd: app.cwd, env: { ...process.env, FORCE_COLOR: "1" } });
  const prefix = `\x1b[${app.color}m[${app.name}]\x1b[0m `;
  const pipe = (stream, out) => {
    let buf = "";
    stream.on("data", (d) => {
      buf += d;
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const l of lines) out.write(prefix + l + "\n");
    });
  };
  pipe(child.stdout, process.stdout);
  pipe(child.stderr, process.stderr);
  child.on("exit", (code) => {
    if (!stopping) {
      console.error(`${prefix}exited with code ${code}; stopping LYRA.`);
      stopAll(code || 1);
    }
  });
  children.push(child);
}
console.log("LYRA starting — frontend http://localhost:5173 · backend http://127.0.0.1:8000/docs  (Ctrl+C to stop)");
process.on("SIGINT", () => stopAll(0));
process.on("SIGTERM", () => stopAll(0));
