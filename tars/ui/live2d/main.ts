// TARS avatar entry point (replaces the Cubism Demo's main.ts).
// Drives the official Cubism 5 framework from the voice service's state.
import { CubismFramework } from '@framework/live2dcubismframework';
import { LAppDelegate } from './lappdelegate';
import { LAppModel } from './lappmodel';

type Info = { heard?: string; note?: string };

// Mao PRO: exp_01 neutral, exp_07 wide-eyed (attentive), exp_08 frown.
const EXPRESSION: Record<string, string> = {
  idle: 'exp_01', listening: 'exp_07', thinking: 'exp_01', speaking: 'exp_01', error: 'exp_08',
};
const STATE_TEXT: Record<string, string> = {
  idle: 'ready', listening: 'listening…', thinking: 'thinking…', speaking: 'speaking', error: 'something went wrong',
};

const pill = document.getElementById('pill') as HTMLDivElement;
const label = document.getElementById('label') as HTMLSpanElement;
let state = 'idle';

function model(): LAppModel | undefined {
  // The Demo keeps these private; reach them at runtime.
  const delegate = LAppDelegate.getInstance() as any;
  return delegate._subdelegates?.[0]?.getLive2DManager()?._models?.[0];
}

function setPill(cls: string, text: string): void {
  pill.className = cls;
  label.textContent = text;
}

function setState(next: string, info: Info = {}): void {
  state = next;
  const m = model();
  if (m && EXPRESSION[next]) m.setExpression(EXPRESSION[next]);
  if (next !== 'speaking') window.__tarsMouth = 0;
  const extra = info.heard ? ` — “${info.heard}”` : info.note ? ` — ${info.note}` : '';
  setPill(next, (STATE_TEXT[next] ?? next) + extra);
}

// Posture per state, applied after motions/expressions each frame.
const original = LAppModel.prototype.update;
LAppModel.prototype.update = function (this: any): void {
  original.call(this);
  const ids = CubismFramework.getIdManager();
  const set = (id: string, v: number) => this._model.setParameterValueById(ids.getId(id), v);
  const t = performance.now() / 1000;
  if (state === 'thinking') {
    set('ParamEyeBallY', 0.7);
    set('ParamAngleZ', 6 * Math.sin(t * 1.3));
  } else if (state === 'listening') {
    set('ParamAngleY', 8);
    set('ParamBodyAngleX', 3);
  } else {
    return;
  }
  this._model.update();
};

function connect(url: string): void {
  const ws = new WebSocket(url);
  ws.onopen = () => setState('idle');
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'mouth') window.__tarsMouth = state === 'speaking' ? msg.v : 0;
    else if (msg.type === 'state') setState(msg.state, msg);
  };
  ws.onclose = () => {
    setPill('offline', 'voice service offline');
    window.__tarsMouth = 0;
    setTimeout(() => connect(url), 2000);
  };
}

// Framing: zoom toward the upper body (an assistant reads better head-and-shoulders).
// ?zoom=1 shows the full body; ?y moves the model down (negative) or up. Read by the
// patched LAppView.initialize(), so it survives the view re-initialising on resize.
declare global {
  interface Window { __tarsZoom?: number; __tarsY?: number }
}
const query = new URLSearchParams(location.search);
window.__tarsZoom = Number(query.get('zoom') ?? 2.2);
window.__tarsY = Number(query.get('y') ?? -1.1);

window.addEventListener('load', () => {
  if (!LAppDelegate.getInstance().initialize()) {
    setPill('error', 'WebGL unavailable');
    return;
  }
  LAppDelegate.getInstance().run();
  const ws = query.get('ws');
  if (ws) connect(ws);
  else setPill('offline', 'no voice service');
}, { passive: true });

window.addEventListener('beforeunload', () => LAppDelegate.releaseInstance(), { passive: true });
