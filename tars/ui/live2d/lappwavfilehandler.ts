// TARS replacement for the Demo's WAV-file lip-sync source: the mouth follows
// the loudness of whatever TARS is saying, pushed in over the avatar bus.
import { IParameterProvider } from '@framework/motion/iparameterprovider';

declare global {
  interface Window { __tarsMouth?: number }
}

export class LAppWavFileHandler extends IParameterProvider {
  private _shown = 0;

  public update(): boolean {
    const target = window.__tarsMouth ?? 0;
    this._shown += (target - this._shown) * 0.45; // smooth 30 Hz updates into 60 fps
    return true;
  }

  public getParameter(): number {
    return Math.min(1, this._shown * 1.6);
  }

  public getRms(): number {
    return this.getParameter();
  }

  public start(): void {}

  public loadWavFile(): Promise<boolean> {
    return Promise.resolve(true);
  }

  public releasePcmData(): void {}

  public release(): void {}
}
