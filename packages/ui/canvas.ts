export interface Point {
  x: number;
  y: number;
}
export class Viewport {
  ctx: CanvasRenderingContext2D;
  width = 1;
  height = 1;
  x = 0;
  y = 0;
  zoom = 1;
  private key: string;
  constructor(
    public canvas: HTMLCanvasElement,
    public name: string,
  ) {
    this.ctx = canvas.getContext("2d")!;
    this.key = "spiking-bug.camera." + name;
    try {
      const saved = JSON.parse(localStorage.getItem(this.key) || "null");
      if (saved && [saved.x, saved.y, saved.zoom].every(Number.isFinite)) {
        this.x = saved.x;
        this.y = saved.y;
        this.zoom = Math.min(5, Math.max(0.05, saved.zoom));
      }
    } catch {}
    new ResizeObserver(() => this.resize()).observe(canvas);
    canvas.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        this.scale(Math.exp(-e.deltaY * 0.001), { x: e.offsetX, y: e.offsetY });
      },
      { passive: false },
    );
  }
  resize() {
    const r = this.canvas.getBoundingClientRect();
    const dpr = Math.min(2, devicePixelRatio || 1);
    this.width = r.width;
    this.height = r.height;
    this.canvas.width = Math.round(r.width * dpr);
    this.canvas.height = Math.round(r.height * dpr);
  }
  save() {
    localStorage.setItem(
      this.key,
      JSON.stringify({ x: this.x, y: this.y, zoom: this.zoom }),
    );
  }
  point(e: PointerEvent): Point {
    const r = this.canvas.getBoundingClientRect();
    return this.world({ x: e.clientX - r.left, y: e.clientY - r.top });
  }
  world(p: Point): Point {
    return { x: (p.x - this.x) / this.zoom, y: (p.y - this.y) / this.zoom };
  }
  screen(p: Point): Point {
    return { x: p.x * this.zoom + this.x, y: p.y * this.zoom + this.y };
  }
  scale(factor: number, p = { x: this.width / 2, y: this.height / 2 }) {
    const before = this.world(p);
    this.zoom = Math.min(5, Math.max(0.05, this.zoom * factor));
    this.x = p.x - before.x * this.zoom;
    this.y = p.y - before.y * this.zoom;
    this.save();
  }
  fit(x: number, y: number, w: number, h: number) {
    this.zoom = Math.min(
      1.5,
      Math.max(
        0.05,
        Math.min(
          (this.width - 100) / Math.max(1, w),
          (this.height - 100) / Math.max(1, h),
        ),
      ),
    );
    this.x = this.width / 2 - (x + w / 2) * this.zoom;
    this.y = this.height / 2 - (y + h / 2) * this.zoom;
    this.save();
  }
  begin() {
    const c = this.ctx;
    const dpr = Math.min(2, devicePixelRatio || 1);
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, this.width, this.height);
    c.translate(this.x, this.y);
    c.scale(this.zoom, this.zoom);
    c.lineWidth = 1 / this.zoom;
  }
  visible(p: Point, margin = 80) {
    const s = this.screen(p);
    return (
      s.x > -margin &&
      s.x < this.width + margin &&
      s.y > -margin &&
      s.y < this.height + margin
    );
  }
  grid(spacing = 50) {
    const c = this.ctx;
    const left = this.world({ x: 0, y: 0 }),
      right = this.world({ x: this.width, y: this.height });
    const step = spacing * (this.zoom < 0.3 ? 4 : this.zoom < 0.6 ? 2 : 1);
    c.fillStyle = "#263032";
    for (let x = Math.floor(left.x / step) * step; x < right.x; x += step)
      for (let y = Math.floor(left.y / step) * step; y < right.y; y += step) {
        c.beginPath();
        c.arc(x, y, 1 / this.zoom, 0, Math.PI * 2);
        c.fill();
      }
  }
}
export function circle(
  c: CanvasRenderingContext2D,
  x: number,
  y: number,
  r: number,
  fill: string,
  stroke?: string,
) {
  c.beginPath();
  c.arc(x, y, r, 0, Math.PI * 2);
  c.fillStyle = fill;
  c.fill();
  if (stroke) {
    c.strokeStyle = stroke;
    c.stroke();
  }
}
